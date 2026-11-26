# Правила модуля «Предобработка аудио»

Следуй общим правилам из [корневого AGENTS.md](../AGENTS.md). Перед изменениями прочитай [контекст модуля](CONTEXT.md) и [его архитектуру](ARCHITECTURE.md).

Сохраняй интерфейсы `BaseConverter`, `BaseDenoiser` и `BaseVAD`. Настраивай адаптеры через `AudioPipelineConfig` и переменные `AUDIO_PREP_*`. При изменении HTTP-контракта синхронизируй `api.py`, `openapi.yaml` и примеры в README.

Проверка из корня репозитория

```bash
python -m pytest audio_preprocessing/tests/
```
