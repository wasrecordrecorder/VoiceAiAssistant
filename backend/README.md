# WebViewDA Python Backend 0.4.0

Backend предоставляет WebSocket runtime, локальную обработку речи, streaming providers и workspace-scoped agent tool-loop.

## Запуск вручную

```powershell
.\bootstrap.ps1
.\.venv\Scripts\python.exe -m assistant_backend --host 127.0.0.1 --port 48761 --token local-dev --data-dir .\data
```

## WebSocket commands

| Command | Назначение |
| --- | --- |
| `assistant.listen` | Запустить микрофон и VAD |
| `assistant.stopListening` | Остановить микрофон |
| `assistant.send` | Отправить запрос |
| `assistant.interrupt` | Прервать агент, запрос или TTS |
| `agent.approve` | Разрешить ожидающее изменение или команду |
| `agent.reject` | Отклонить ожидающее изменение или команду |
| `settings.get` | Получить настройки |
| `settings.save` | Сохранить настройки и API key |
| `providers.catalog` | Получить Zen/Go model catalog |
| `audio.devices` | Получить список устройств |
| `models.preload` | Предварительно загрузить speech-модели |
| `tts.test` | Проверить голос |
| `conversation.new` | Создать диалог |
| `conversation.clear` | Очистить активный диалог |

## Новые события

| Event | Назначение |
| --- | --- |
| `transcript.partial` | Текущий распознанный текст во время речи |
| `transcript.final` | Завершённая фраза для запроса модели |
| `agent.iteration` | Номер шага tool-loop |
| `agent.tool_started` | Инструмент вызван моделью |
| `agent.tool_finished` | Результат инструмента отправлен модели |
| `agent.approval_required` | UI должен запросить разрешение |
| `agent.approval_resolved` | Решение принято |

## Agent settings

| Setting | Значение |
| --- | --- |
| `agent_enabled` | Включить tools |
| `workspace_path` | Единственная доступная агенту директория |
| `agent_allow_edits` | Записывать файлы без подтверждения |
| `agent_allow_commands` | Запускать команды без подтверждения |
| `agent_max_steps` | Максимум итераций модели и tools, до 256 |
| `agent_command_timeout` | Максимальная длительность команды |
| `partial_transcription` | Включить live STT |
| `partial_interval_ms` | Интервал partial decode |

## Secrets

API key не записывается в `settings.json`. При доступном `keyring` ключ хранится в системном credential storage под service name `WebViewDA` и именем выбранного provider.
