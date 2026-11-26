# SaaS-voice-analysis

Для установки используйте Python 3.11 или новее. Версии библиотек с
исправлениями безопасности заданы в общем [файле ограничений](constraints.txt).

```bash
python -m pip install -r requirements.txt
python -m pytest -q
```

В интеграционных тестах используется [синтетическая запись](testdata/synthetic_call.wav)
без персональных данных. Русский голос сгенерирован eSpeak NG из учебной фразы. При первом запуске Whisper
загружает модели `tiny` и `large-v3-turbo`. При наличии весов в кэше тесты
можно выполнить с `HF_HUB_OFFLINE=1`.
