# Оркестратор обработки звонков (`orchestrator/`)

Пакет `orchestrator/` реализует сквозной конвейер обработки телефонных звонков на основе слабо связанных изолированных компонентов («Чёрные ящики»).

---

## 1. Архитектурная концепция («Чёрные ящики»)

В соответствии с требованиями техлида:
1. **Полная изоляция модулей:**
   - Модули `audio_preprocessing` (конвертация, шумоподавление, VAD) и `stt` (транскрибация) являются независимыми «чёрными ящиками».
   - Внутри `stt/` нет никаких упоминаний `audio_preprocessing` или `vad`.
   - Внутри `audio_preprocessing/` и `vad/` нет никаких упоминаний `stt`.
2. **Транскрибатор не знает о предобработке:**
   - Интерфейс `BaseTranscriber` принимает стандартный аудиопоток (1D float32 массив или путь к файлу).
   - Если предобработка включена, оркестратор передает в транскрибатор только склеенные участки речи (`speech_only_audio`).
   - Если предобработка выключена, оркестратор передает исходное сырое аудио.
   - Сам `stt` не знает и не должен знать, было ли аудио предварительно очищено или сегментировано.
3. **Восстановление таймкодов на стороне оркестратора:**
   - Пересчет временных меток (`remap_transcription_result`) вынесен из модуля предобработки в оркестратор, так как именно оркестратор связывает хронометраж исходного звонка, границы пауз VAD и сегменты транскрипции.
4. **Симметрия In-Memory и REST API:**
   - Благодаря адаптерам `RestPreprocessorClient` и `RestTranscriberClient`, класс `CallProcessingPipeline` работает идентично как при прямом вызове Python-классов в памяти, так и поверх распределенных HTTP REST API микросервисов.

---

## 2. Диаграмма потока данных (Data Flow)

```mermaid
flowchart TD
    A["Входящий звонок (ID / File Path)"] --> B["LocalMockAudioLoader"]
    B -->|Сырое аудио 1D float32| C{"Предобработка включена?"}
    
    C -->|Да| D["Preprocessor / VAD (Silero)"]
    D -->|speech_only_audio + speech_segments| E["STT Transcriber (Whisper)"]
    E -->|Сжатые сегменты речи| F["Remapper (восстановление таймкодов)"]
    F --> G["Итоговый TranscriptionResult на шкале звонка"]

    C -->|Нет| H["STT Transcriber (Whisper) напрямую"]
    H -->|Сегменты на сыром аудио| G
```

---

## 3. Структура модуля

```text
orchestrator/
├── __init__.py           # Публичные экспорты модуля
├── interfaces.py         # Базовый интерфейс BaseAudioLoader и протоколы сервисов
├── loaders.py            # LocalMockAudioLoader (эмуляция CRM / локального хранилища)
├── rest_clients.py       # HTTP REST-клиенты RestPreprocessorClient и RestTranscriberClient
├── pipeline.py           # CallProcessingPipeline + утилита remap_transcription_result
├── demo.py               # Консольная демонстрация двух режимов для заказчика/техлида
├── README.md             # Документация модуля
└── tests/
    ├── __init__.py
    └── test_orchestrator.py # Тесты изоляции, in-memory конвейера и REST API
```

---

## 4. Примеры использования

### 4.1. Режим In-Memory (быстрый локальный запуск)

```python
from audio_preprocessing import get_audio_pipeline
from orchestrator import CallProcessingPipeline, LocalMockAudioLoader
from stt import TranscriberConfig, get_transcriber

# 1. Инициализация компонентов
loader = LocalMockAudioLoader(base_dir="./calls")
preprocessor = get_audio_pipeline()
transcriber = get_transcriber(config=TranscriberConfig())

# 2. Создание и запуск конвейера
pipeline = CallProcessingPipeline(
    audio_loader=loader,
    preprocessor=preprocessor,
    transcriber=transcriber,
    remap_timestamps=True,
)

result = pipeline.run("call_12345.mp3")
print("Текст:", result.text)
print("Длительность звонка:", result.duration)
```

### 4.2. Режим микросервисов (через HTTP REST API)

```python
from orchestrator import (
    CallProcessingPipeline,
    LocalMockAudioLoader,
    RestPreprocessorClient,
    RestTranscriberClient,
)

# Клиенты к распределенным FastAPI микросервисам
preprocessor = RestPreprocessorClient(base_url="http://localhost:8002")
transcriber = RestTranscriberClient(base_url="http://localhost:8001")
loader = LocalMockAudioLoader(base_dir="./calls")

pipeline = CallProcessingPipeline(
    audio_loader=loader,
    preprocessor=preprocessor,
    transcriber=transcriber,
    remap_timestamps=True,
)

result = pipeline.run("call_12345.mp3")
```

---

## 5. Запуск демонстрации и тестов

Запуск интерактивного демо:
```bash
python -m orchestrator.demo
```

Запуск полного набора тестов:
```bash
pytest audio_preprocessing/tests/ stt/tests/ orchestrator/tests/ -v
```
