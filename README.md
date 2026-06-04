# WebViewDA Voice v0.12.0 0.6.0

Нативная оболочка голосового ассистента для Windows: C++20 и WebView2 отвечают за окно, трей и UI, Python backend выполняет speech pipeline, API providers и локальный голосовой агент с инструментами проекта и Windows.

## Реализовано

- квадратное frameless-окно в monochrome dark стиле;
- WebGL orb со состояниями `idle`, `listening`, `transcribing`, `thinking`, `speaking`, `error`;
- скрытие в tray, открытие из tray и горячая клавиша `Ctrl + Shift + Space`;
- отдельный Python backend с WebSocket transport и одноразовым session token;
- OpenRouter, OpenCode Zen, OpenCode Go и Custom Endpoint;
- protocol routing для Zen/Go через `Responses`, `Messages`, `Chat Completions` и Google route;
- `faster-whisper` либо Vosk STT, Silero/WebRTC VAD, Silero TTS;
- live partial transcription во время произнесения фразы;
- streaming-ответы и потоковая озвучка завершённых предложений;
- echo-guard и optional barge-in;
- выбор аудиоустройств и профили нагрузки;
- SQLite-история разговоров;
- API keys через системное защищённое хранилище Python `keyring`;
- настоящий agent tool-loop для чтения, изменения файлов и запуска команд.

## Agent tool-loop

Agent mode включает инструменты Windows, а при заданной `Рабочей папке` также добавляет специализированные инструменты проекта.

```text
Prompt
  → Provider tool call
  → Approval / path policy
  → Windows action or workspace action
  → Tool result back to model
  → Next tool call or final answer
```

### Системные инструменты Windows

| Tool | Назначение | Политика по умолчанию |
| --- | --- | --- |
| `get_known_folders` | Пути профиля, Downloads, Desktop, Documents | Разрешён |
| `recycle_bin_status` | Проверка корзины | Разрешён |
| `empty_recycle_bin` | Очистка корзины | Всегда подтверждение |
| `list_processes` | Активные процессы | Разрешён |
| `path_info`, `list_directory`, `read_text_file` | Просмотр файлов на ПК | Внешние пути требуют подтверждения |
| `write_text_file`, `create_directory`, `copy_path`, `move_path` | Изменения пользовательских файлов | Подтверждение |
| `move_to_recycle_bin` | Удаление в корзину | Подтверждение |
| `delete_path_permanently` | Безвозвратное удаление | Всегда подтверждение |
| `open_path`, `launch_application` | Открытие файла/программы | Подтверждение |
| `run_cmd`, `run_powershell` | Выполнение команд Windows | Подтверждение |

### Инструменты проекта

| Tool | Назначение | Политика по умолчанию |
| --- | --- | --- |
| `list_files` | Просмотр файлов workspace | Разрешён |
| `read_file` | Чтение UTF-8 файла с диапазоном строк | Разрешён |
| `search_text` | Поиск текста или regex | Разрешён |
| `write_file` | Создание или полная запись файла | Подтверждение |
| `replace_in_file` | Точечная замена фрагмента | Подтверждение |
| `run_command` | Запуск executable с argv и timeout | Подтверждение |

### Ограничения безопасности

- инструменты проекта не могут выйти из workspace, symlink escape блокируется;
- изменение и удаление системными инструментами ограничено профилем пользователя и workspace;
- системные папки и корни дисков нельзя удалить или изменить;
- `run_cmd` и `run_powershell` требуют подтверждения, пока пользователь явно не разрешит команды без запросов;
- безвозвратное удаление и очистка корзины подтверждаются всегда;
- таймаут команды ограничен и вывод возвращается модели только после завершения.

## OpenCode Zen и Go

Приложение подключается напрямую к API Zen / Go, не запускает `opencode serve` и не зависит от OpenCode CLI.

### Zen

| Тип модели | Endpoint |
| --- | --- |
| GPT 5.x | `https://opencode.ai/zen/v1/responses` |
| Claude и Qwen | `https://opencode.ai/zen/v1/messages` |
| Gemini | `https://opencode.ai/zen/v1/models/<model>` |
| OpenAI-compatible модели | `https://opencode.ai/zen/v1/chat/completions` |

### Go

| Модели | Endpoint |
| --- | --- |
| GLM, Kimi, DeepSeek, MiMo | `https://opencode.ai/zen/go/v1/chat/completions` |
| MiniMax и Qwen | `https://opencode.ai/zen/go/v1/messages` |

Каталог в `backend/assistant_backend/core/catalog.py` зафиксирован по документации OpenCode, обновлённой `2026-05-26`.

## Speech pipeline

```text
Microphone → VAD → Partial STT updates → Final STT → Provider/Agent → Sentence buffer → TTS → Speakers
```

### Live partial transcription

Во время активной речи `VoiceCapture` периодически передаёт накопленный аудиофрагмент STT. Backend публикует `transcript.partial`, а UI показывает текущий текст под шаром. После паузы отправляется `transcript.final`, и только он запускает запрос к модели.

Настройки:

- `Показывать распознавание во время речи`;
- `Интервал partial, мс`, диапазон `450–3000`.

## Архитектура backend

```text
assistant_backend/
├── agent/
│   ├── loop.py
│   ├── policy.py
│   ├── tools.py
│   └── types.py
├── audio/
│   ├── capture.py
│   ├── devices.py
│   ├── stt.py
│   ├── tts.py
│   └── vad.py
├── core/
│   ├── catalog.py
│   ├── events.py
│   ├── history.py
│   └── settings.py
├── providers/
│   ├── chat_completions.py
│   ├── messages.py
│   ├── responses.py
│   ├── google.py
│   └── factory.py
├── runtime.py
└── server.py
```

## Сборка и запуск

Требования:

- Windows 10/11;
- Visual Studio 2022 с `Desktop development with C++`;
- CMake 3.26+;
- Python 3.11+;
- Microsoft Edge WebView2 Evergreen Runtime.

```powershell
.\scripts\setup.ps1 -Configuration Debug
.\scripts\run.ps1 -Configuration Debug
```

Проверка backend:

```powershell
.\scripts\test-backend.ps1
```

## Осталось для production

- packaged Python runtime и installer с управлением весами моделей;
- полноценное acoustic echo cancellation вместо режима mute-processing;
- удалённая синхронизация Zen/Go model catalog;
- diff-preview перед массовыми правками и журнал разрешений агента;
- тестирование API tool calling с реальными ключами Zen/Go/OpenRouter.


## v0.12.0

- Горизонтальная компоновка 1160 × 730.
- Push-to-talk режим с глобальной клавишей.
- Компактный always-on-top status widget при скрытии в трей.
- `play_music` и существующие media controls для управления воспроизведением.
- Локальное время добавляется к каждому обращению модели.
- `inspect_screen` для vision-моделей с подтверждением снимка экрана.
