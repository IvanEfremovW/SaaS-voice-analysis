# Модуль транскрибации речи (Speech-to-Text, STT)

Модуль `stt/` реализует компонент автоматического перевода аудиозаписей телефонных звонков в структурированный текст с разбивкой по репликам и таймкодам. Является связующим звеном между модулями предобработки/детекции голоса (`audio_preprocessing/`, `vad/`) и модулем аналитической оценки звонков языковой моделью (`LLM Qwen`).

---

## 1. Архитектура и принципы проектирования

- **Паттерн Strategy / Adapter:** Модуль изолирован за абстрактным интерфейсом `BaseTranscriber`. Текущая реализация `FasterWhisperTranscriber` использует высокоэффективный инференс-движок `CTranslate2`. Архитектура позволяет подключить внешние API (например, Sber SaluteSpeech, GigaChat API) или другие локальные модели без модификации вызывающего кода.
- **Строгая типизация (Pydantic v2):** Все контракты данных (`TranscriptionResult`, `TranscriptionSegment`, `TranscriberConfig`) валидируются моделями Pydantic v2 с поддержкой сериализации в JSON (`model_dump()`, `model_dump_json()`).
- **Graceful Hardware Fallback:** Проверка доступности GPU осуществляется нативно через `ctranslate2.get_cuda_device_count() > 0` без тяжеловесной зависимости от PyTorch. При отсутствии CUDA или запуске на CPU происходит автоматическое переключение на `cpu` с квантованием `int8`.
- **Универсальный вход:** Поддерживается передача как строковых путей (`str`) и объектов `pathlib.Path`, так и массивов `numpy.ndarray` (float32, 16 kHz Mono).

---

## 2. Структура модуля

```text
stt/
├── __init__.py                 # Публичный экспорт: get_transcriber, модели DTO, BaseTranscriber
├── interfaces.py               # Абстрактный интерфейс BaseTranscriber и Pydantic-схемы
├── transcriber.py              # Реализация FasterWhisperTranscriber (CTranslate2)
├── config.py                   # Pydantic-конфигурация модели TranscriberConfig
├── generate_samples.py         # Скрипт генерации артефакта качества на реальных данных
├── transcription_samples.json  # Артефакт качества транскрибации (DoD №2)
├── requirements.txt            # Изолированные зависимости модуля
├── README.md                   # Документация API и примеры использования
└── tests/
    ├── __init__.py
    └── test_transcriber.py     # Интеграционные тесты DoD на 3 реальных аудиофайлах
```

---

## 3. Спецификация API и схемы данных

### 3.1. `TranscriberConfig`
Параметры инициализации и инференса модели:

| Поле | Тип | По умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `model_size` | `str` | `"base"` | Размер модели Whisper (`tiny`, `base`, `small`, `medium`, `large-v3`) |
| `device` | `"cuda" \| "cpu" \| "auto"` | `"cuda"` | Вычислительное устройство (с автопереключением на CPU) |
| `device_index`| `int` | `0` | Индекс целевой видеокарты |
| `compute_type`| `str` | `"float16"` | Тип квантования (`float16`, `int8`, `float32`, `int8_float16`) |
| `language` | `Optional[str]` | `"ru"` | Двухбуквенный языковой код ISO или `None` для автодетекции |
| `beam_size` | `int` | `5` | Размер лучевого поиска (beam search) |
| `vad_filter` | `bool` | `False` | Внутренний VAD Whisper (`False`, т.к. используется модуль `vad/`) |
| `condition_on_previous_text` | `bool` | `False` | Защита от зацикливания и галлюцинаций на паузах |
| `initial_prompt` | `Optional[str]` | `None` | Начальный контекст/глоссарий для повышения точности терминов |

---

### 3.2. Схемы DTO (Выходные данные)

#### `TranscriptionSegment`
Речевой фрагмент с таймкодами и оценкой уверенности:
```python
class TranscriptionSegment(BaseModel):
    id: int               # Порядковый номер сегмента (0, 1, 2...)
    start: float          # Время начала сегмента в секундах (округлено до 3 знаков)
    end: float            # Время окончания сегмента в секундах (округлено до 3 знаков)
    text: str             # Очищенный текст сегмента
    avg_logprob: float    # Средняя лог-вероятность токенов (уверенность)
    no_speech_prob: float # Вероятность отсутствия речи
```

#### `TranscriptionResult`
Итоговый объект распознанной записи:
```python
class TranscriptionResult(BaseModel):
    text: str                             # Полный собранный текст звонка
    language: str                         # Распознанный язык (например, 'ru')
    language_probability: float           # Уверенность модели в языке (0.0 - 1.0)
    duration: float                       # Длительность аудиозаписи в секундах
    segments: list[TranscriptionSegment]  # Список всех сегментов
```

---

## 4. Примеры использования

### Вариант А: Транскрибация по пути к файлу (`str` или `Path`)

```python
from pathlib import Path
from stt import get_transcriber, TranscriberConfig

# 1. Создаем транскрибатор через фабрику
config = TranscriberConfig(model_size="base", device="cuda")
transcriber = get_transcriber(engine="faster-whisper", config=config)

# 2. Вызываем транскрибацию по пути к аудио
audio_path = Path("samples/test_call_youtube.mp3")
result = transcriber.transcribe(audio_path)

print(f"Язык: {result.language} (вероятность: {result.language_probability})")
print(f"Длительность: {result.duration:.2f} сек.")
print(f"Полный текст: {result.text}\n")

# Итерация по сегментам
for seg in result.segments:
    print(f"[{seg.start:.2f}s -> {seg.end:.2f}s] {seg.text}")
```

---

### Вариант Б: Передача `np.ndarray` напрямую из модуля `vad/`

Интеграция со склеенным голосовым потоком после детекции голосовой активности:

```python
import soundfile as sf
from vad import SileroVADAdapter
from stt import get_transcriber, TranscriberConfig

# 1. Загрузка исходного аудио и фильтрация пауз через VAD
raw_audio, sr = sf.read("samples/input_test_call.mp3", dtype="float32")
vad = SileroVADAdapter()
speech_only_audio, speech_segments = vad.process(raw_audio, sr=sr)

# 2. Транскрибация чистого речевого потока (1D float32 np.ndarray)
transcriber = get_transcriber(config=TranscriberConfig(model_size="base"))
result = transcriber.transcribe(speech_only_audio)

print(f"Распознано слов: {len(result.text.split())}")
print(f"Текст после VAD: {result.text}")
```

---

## 5. Запуск тестов и валидация качества

```bash
# Запуск автоматических тестов DoD на 3 реальных аудиофайлах:
pytest stt/tests/test_transcriber.py -v

# Генерация артефакта качества на модели 'base' (stt/transcription_samples.json):
python -m stt.generate_samples
```
