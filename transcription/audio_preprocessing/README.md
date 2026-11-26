# Модуль предобработки аудио и детекции речи (Preprocess + VAD)

Модуль `audio_preprocessing/` реализует компонент первичной подготовки аудиосигнала телефонных звонков и детекции голосовой активности. Он объединяет конвертацию разнородных форматов в стандартизированный поток 16 kHz Mono float32, спектральную очистку от стационарных шумов телефонии, удаление пауз/тишины через VAD. Модуль возвращает речевой поток и интервалы речи на шкале исходного звонка; таймкоды транскрибации восстанавливает [оркестратор](../orchestrator/README.md).

---

## 1. Архитектура и принципы проектирования

- **Паттерн Strategy / Adapter:** Все внешние библиотеки (`torchaudio`, `ffmpeg`, `librosa`, `noisereduce`, `silero-vad`, `webrtcvad`) инкапсулированы за абстрактными интерфейсами `BaseConverter`, `BaseDenoiser` и `BaseVAD`. Переключение адаптеров происходит через конфигурацию или переменные окружения без изменения бизнес-логики.
- **Утвержденный Production R&D стек:**
  1. **Конвертация:** `TorchAudioConverter` (быстрое декодирование в память, нормализация амплитуды до `[-1.0, 1.0]`, приведение к 16 kHz Mono float32).
  2. **Шумоподавление:** `StationarySpectralDenoiser` на базе спектрального вычитания (подавление стационарного телефонного гула/шипения).
  3. **Детекция речи:** `SileroVADAdapter` (`threshold=0.5`) — глубокая нейросетевая сегментация речи и вырезание неинформативных пауз.
- **Обработка в памяти:** Промежуточные результаты конвертации, шумоподавления и VAD передаются как NumPy-массивы / Torch Tensors. HTTP-загрузка сохраняется во временный файл, который удаляется после обработки. Маршрут по пути также позволяет сохранить итоговый WAV.
- **Исходная шкала времени:** `speech_segments` содержит границы речи до удаления пауз. Оркестратор использует их для пересчёта `start` и `end` сегментов и слов транскрибации.
- **HTTP REST API (FastAPI):** Готовый микросервис с поддержкой Dependency Injection, валидацией через Pydantic v2 и документацией OpenAPI 3.0.3.

---

## 2. Структура модуля

```text
audio_preprocessing/
├── __init__.py                 # Публичный экспорт: фабрики, интерфейсы, конвейер
├── api.py                      # FastAPI HTTP REST API сервис (порт 8002)
├── interfaces.py               # Абстрактные интерфейсы BaseConverter и BaseDenoiser
├── converters.py               # Реализации конвертеров: TorchAudio, FFmpeg, Librosa
├── denoisers.py                # Шумоподавление: Stationary, NonStationary, TelephonyBandpass
├── pipeline.py                 # Единое ядро AudioPreprocessVADPipeline и пересчёт отдельной метки времени
├── openapi.yaml                # Спецификация OpenAPI 3.0.3 REST API
├── requirements.txt            # Зависимости модуля предобработки
├── input_test_call.mp3         # Реальный аудиофайл для тестов и валидации
├── README.md                   # Документация модуля и API
└── tests/
    ├── __init__.py
    ├── test_pipeline.py        # Интеграционные тесты конвейера и пересчета таймкодов
    ├── test_api.py             # Тесты эндпоинтов REST API, валидации и OpenAPI
    └── test_security.py        # Тесты ограничений HTTP и доступа по пути
```

---

## 3. Спецификация API и схемы данных

### 3.1. Переменные окружения микросервиса

Сервис настраивается через переменные окружения (с поддержкой переопределения в DI):

| Переменная | По умолчанию | Описание |
| :--- | :--- | :--- |
| `AUDIO_PREP_CONVERTER` | `"torchaudio"` | Адаптер конвертации (`torchaudio`, `ffmpeg`, `librosa`) |
| `AUDIO_PREP_DENOISER` | `"stat_spectral"` | Алгоритм шумоподавления (`stat_spectral`, `nonstat_spectral`, `telephony_bandpass`, `none`) |
| `AUDIO_PREP_VAD` | `"silero"` | Детектор голосовой активности (`silero`, `webrtc`, `energy`, `none`) |
| `AUDIO_PREP_TARGET_SR` | `16000` | Целевая частота дискретизации (Гц) |

---

### 3.2. Pydantic-схемы данных

#### `SpeechSegmentDTO`
```python
class SpeechSegmentDTO(BaseModel):
    start: float  # Начало речи в исходном файле (сек)
    end: float    # Конец речи в исходном файле (сек)
```

#### `PreprocessResponse`
```python
class PreprocessResponse(BaseModel):
    sample_rate: int                         # Частота дискретизации (16000 Гц)
    original_duration: float                 # Исходный хронометраж (сек)
    speech_duration: float                   # Хронометраж чистой речи после VAD (сек)
    retention_pct: float                     # Процент сохраненной речи (0..100%)
    segments_count: int                      # Количество речевых интервалов
    speech_segments: list[SpeechSegmentDTO]  # Границы речи на шкале исходного файла
    output_wav_path: Optional[str] = None    # Путь к сохраненному WAV (если запрашивался)
    audio_wav_base64: Optional[str] = None   # Base64 речевого аудио (если запрашивалось)
```

#### `PreprocessByPathRequest`
```python
class PreprocessByPathRequest(BaseModel):
    file_path: str                          # Путь к аудиофайлу в файловой системе / общем томе
    output_wav_path: Optional[str] = None   # Путь для сохранения очищенного 16kHz WAV
    include_audio_base64: bool = False      # Включить ли аудио в формате Base64 в ответ
```

---

## 4. Python-интерфейс конвейера

### 4.1. Предобработка аудиозаписи звонка

```python
from pathlib import Path
from audio_preprocessing import get_audio_pipeline, AudioPipelineConfig

# Инициализация конвейера с конфигурацией по умолчанию
pipeline = get_audio_pipeline()

# Обработка аудиофайла
audio_path = Path("audio_preprocessing/input_test_call.mp3")
result = pipeline.process_detailed(audio_path)

print(f"Исходная длительность: {result.original_duration:.2f} сек")
print(f"Длительность речи: {result.speech_duration:.2f} сек")
print(f"Удержание речи: {result.retention_pct:.1f}%")
print(f"Найдено сегментов: {len(result.speech_segments)}")
```

### 4.2. Передача результата в оркестратор

Передайте конвейер как `preprocessor` в `CallProcessingPipeline`: оркестратор вызовет STT и пересчитает таймкоды сегментов при `remap_timestamps=True`. Пример приведён в [README оркестратора](../orchestrator/README.md). Пересчёт готового `TranscriptionResult` доступен через Python-функцию `orchestrator.remap_transcription_result`.

---

## 5. Запуск HTTP REST API сервера

Установите зависимости из корневого `requirements.txt`. Все команды и Python-примеры выполняются из корня репозитория.

Запуск веб-сервиса через Uvicorn:

```bash
uvicorn audio_preprocessing.api:app --host 0.0.0.0 --port 8002 --reload
```

Интерактивная документация Swagger UI доступна по адресу: `http://localhost:8002/docs`  
Спецификация OpenAPI в формате JSON: `http://localhost:8002/openapi.json`

Экспорт актуальной спецификации OpenAPI в YAML:
```bash
python -c "from audio_preprocessing.api import export_openapi_yaml; export_openapi_yaml()"
```

---

## 6. Примеры запросов через `curl`

### 6.1. Проверка состояния сервиса (`GET /api/v1/health`)

```bash
curl -X GET "http://localhost:8002/api/v1/health" \
  -H "Accept: application/json"
```

**Ответ (200 OK):**
```json
{
  "status": "ok",
  "converter": "torchaudio",
  "denoiser": "stat_spectral",
  "vad": "silero",
  "target_sr": 16000
}
```

---

### 6.2. Предобработка через загрузку файла (`POST /api/v1/preprocess`)

```bash
curl -X POST "http://localhost:8002/api/v1/preprocess" \
  -F "file=@audio_preprocessing/input_test_call.mp3" \
  -F "include_audio_base64=false"
```

**Ответ (200 OK):**
```json
{
  "sample_rate": 16000,
  "original_duration": 35.07,
  "speech_duration": 28.74,
  "retention_pct": 81.95,
  "segments_count": 8,
  "speech_segments": [
    { "start": 1.762, "end": 6.398 },
    { "start": 7.124, "end": 11.450 }
  ],
  "output_wav_path": null,
  "audio_wav_base64": null
}
```

---

### 6.3. Предобработка по локальному пути (`POST /api/v1/preprocess/by-path`)

Маршрут по пути включается переменными `AUDIO_SHARED_ROOT` и `AUDIO_SHARED_TOKEN`.
Укажите выделенный каталог, в котором могут писать только доверенные процессы,
и передавайте токен через заголовок Authorization. Пути должны оставаться
внутри этого каталога. Лимит тела POST-запроса составляет 32 МиБ. Одновременно обрабатываются
до двух POST-запросов на процесс, остальные получают HTTP 503. Перед обработкой
поток проверяется по фактическому декодированному объёму. Пределы составляют
30 минут и 64 млн отсчётов суммарно по каналам, превышение возвращает HTTP 413. Выходной WAV
создаётся в существующем каталоге без перезаписи.

Используется при работе в Docker через Shared Volume:

```bash
curl -X POST "http://localhost:8002/api/v1/preprocess/by-path" \
  -H "Authorization: Bearer $AUDIO_SHARED_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "file_path": "/data/calls/input_test_call.mp3",
    "output_wav_path": "/data/processed/call_speech_only.wav",
    "include_audio_base64": false
  }'
```

---

## 7. Тестирование

Запуск модульных и интеграционных тестов:

```bash
# Тестирование модуля Preprocess + VAD
pytest audio_preprocessing/tests/ -v

# Полный регрессионный прогон модулей аудиопайплайна
pytest audio_preprocessing/tests/ stt/tests/ orchestrator/tests/ -v
```
