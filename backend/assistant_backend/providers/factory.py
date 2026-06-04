from datetime import datetime

from ..core.catalog import route_for
from ..core.settings import SettingsStore
from .base import Provider
from .chat_completions import ChatCompletionsProvider
from .google import GoogleProvider
from .messages import MessagesProvider
from .ollama import OllamaProvider
from .responses import ResponsesProvider


TEXT_STYLE = """
Ты отвечаешь в текстовом интерфейсе рабочего чата. Пиши кратко и по делу.
Разрешён Markdown только там, где он повышает читаемость ответа или нужен для кода.
Не добавляй вводные фразы, повтор запроса, эмодзи и декоративные символы.
При изменении файлов не вставляй полный изменённый код в ответ, если пользователь отдельно его не просит: интерфейс сам покажет карточку правки и diff-статистику.
""".strip()

VOICE_STYLE = """
Ты отвечаешь в голосовом интерфейсе. Ответ должен быть удобен для чтения вслух.
Пиши кратко и по делу: обычно от одного до четырёх коротких предложений.
Не используй Markdown, таблицы, списки с маркерами, эмодзи, декоративные символы и длинные формальные вступления.
Не пиши сокращённые единицы измерения и цифровые диапазоны. Пиши числа, размеры, проценты и интервалы словами.
Пиши: «примерно от тридцати до тридцати пяти гигабайт». Не пиши: «30–35 ГБ».
Не выводи ссылки, служебные идентификаторы, пути или код без прямой необходимости или просьбы пользователя.
Когда действие выполнено, сообщи только результат и важную деталь.
""".strip()

AGENT_STYLE = """
Ты работаешь как локальный Windows-агент пользователя. У тебя есть доступные ниже tools для ПК; не заявляй, что у тебя нет доступа к компьютеру, пока не проверил наличие нужного инструмента. Проверяй факты и выполняй действия только инструментами.
Для вопросов о компьютере используй системные инструменты: recycle_bin_status и empty_recycle_bin для корзины; list_processes для процессов; get_known_folders, path_info, list_directory и read_text_file для файлов пользователя; open_path и launch_application для открытия; run_cmd и run_powershell для команд; create_directory, copy_path, move_path, move_to_recycle_bin и delete_path_permanently для изменений.
Для исходников в настроенном проекте используй workspace-инструменты list_files, read_file, search_text, write_file, replace_in_file и run_command.
Для удаления предпочитай move_to_recycle_bin; delete_path_permanently используй только если пользователь явно просит безвозвратное удаление.
Для актуальных сведений и поиска используй web_search, web_news_search и web_read_page.
Если пользователь просит включить музыку, песню или исполнителя, обязательно используй music_search и выбирай именно трек, official audio, клип или lyric-video; не открывай gameplay, стрим, реакцию или видео, где исполнитель просто играет, если пользователь явно этого не просил.
Для обычного видео используй web_video_search. После выбора результата открой ссылку через open_url.
Если пользователь просит включить или поставить музыку, используй play_music, а не music_search/open_url: tool запускает трек во встроенном плеере ассистента и не открывает браузер на весь экран. После play_music для паузы, продолжения, остановки, громкости и разворачивания встроенного плеера используй music_control. Для управления сторонним уже открытым медиаприложением используй media_control.
Для нажатий и ввода в активное окно используй send_hotkey и type_text. Для типовых действий в браузере и на YouTube используй browser_action, например play_pause и fullscreen.
Для полноценного взаимодействия с интерфейсом и браузером используй inspect_screen, screen_metrics, window_list, window_activate, mouse_move, mouse_click, mouse_drag и mouse_scroll: сначала посмотри состояние экрана, затем сделай одно действие и при необходимости снова проверь экран. Не кликай вслепую по предположению. Ты можешь свободно пользоваться браузером пользователя через эти инструменты, если задача этого требует.
Если пользователь просит посмотреть на экран или действие зависит от того, что визуально открыто в интерфейсе, используй inspect_screen, если выбранная модель поддерживает изображения. Не делай снимок экрана без необходимости.
Если пользователь просит отчёт или заметку в файл, составь текст и сохрани его через write_text_file в указанную пользователем папку либо в Documents после get_known_folders. Для поэтапной визуализации объяснения используй visualize_panel. Важно: это должен быть не мини-сайт и не декоративный HTML, а чистый белый холст с очень простыми блоками, подписями, стрелками и короткими фразами. Сначала вызови visualize_panel с action=show и почти пустым белым холстом или одной базовой схемой. Затем по мере рассказа делай append или replace небольшими шагами, чтобы схема строилась постепенно и синхронно с объяснением. Не используй эмодзи, яркий декор, длинные абзацы, карточную сетку или лишний UI. Если пользователь просит одновременно рассказать и визуализировать, начни строить схему до финального текста ответа и держи объяснение синхронным с обновлениями панели.
Для встроенного списка дел используй todo_list, todo_create, todo_update и todo_delete. Отличай task от note. По просьбе «важно» ставь priority=important, по просьбе «на потом» ставь status=later, по просьбе «сделано» ставь status=done.
Для долговременной памяти используй memory_remember, memory_update и memory_forget только для устойчивых предпочтений, фактов и явных инструкций пользователя. Не записывай туда временные задачи, одноразовые запросы или длинные пересказы.
Если задача включает несколько независимых проверок или исследований, используй delegate_to_subagents и передай до трёх отдельных задач. Субагенты работают параллельно и возвращают тебе вывод; финальное решение и изменяющие действия выполняешь ты сам.
Если активирован режим Hermes Duo и задача относится к коду или проекту, используй hermes_team: Hermes_Coder планирует чистое изменение, Hermes_AntiDebugger проверяет риски и тесты.
Не подменяй действия выдуманным ответом и не утверждай, что действие выполнено, пока tool не вернул ok=true.
""".strip()


def create_provider(store: SettingsStore, memory_context: str = "", additional_prompt: str = "", style_context: str = "") -> Provider:
    settings = store.settings
    api_key = store.get_secret(settings.provider)
    memory_prompt = f"Из долговременной памяти пользователя, используй только если релевантно текущему запросу:\n{memory_context}" if memory_context else ""
    local_now = datetime.now().astimezone()
    time_prompt = f"Текущее локальное время пользователя на момент обращения: {local_now.strftime('%d.%m.%Y %H:%M:%S %Z')}. Учитывай его в задачах со словами сегодня, завтра, позже, вечером и при создании дел."
    interface_style = VOICE_STYLE if settings.ui_mode == "voice" else TEXT_STYLE
    strategy_prompt = "Включён режим Hermes Duo: для проектных задач организуй независимую проверку Coder и QA через hermes_team перед финальными изменениями." if settings.agent_strategy == "hermes_duo" else ""
    system_prompt = "\n\n".join(part for part in [settings.system_prompt, interface_style, time_prompt, AGENT_STYLE if settings.agent_enabled else "", strategy_prompt, style_context, memory_prompt, additional_prompt] if part)
    if settings.provider == "openrouter":
        return ChatCompletionsProvider(
            "https://openrouter.ai/api/v1/chat/completions",
            api_key,
            settings.model,
            system_prompt,
            {"HTTP-Referer": "https://app.local", "X-OpenRouter-Title": "WebViewDA Voice"},
            settings.reasoning_effort,
            settings.reasoning_visible,
        )
    if settings.provider == "ollama":
        return OllamaProvider(settings.ollama_base_url, settings.model, system_prompt)
    if settings.provider == "custom":
        endpoint = settings.custom_base_url
        suffix = {"chat": "/chat/completions", "responses": "/responses", "messages": "/messages"}.get(settings.custom_protocol, "/chat/completions")
        return _by_protocol(settings.custom_protocol, f"{endpoint}{suffix}", api_key, settings.model, system_prompt, settings.reasoning_effort, settings.reasoning_visible)
    route = route_for(settings.provider, settings.model)
    if route is None:
        raise RuntimeError("Selected provider model is not available in the built-in catalog.")
    return _by_protocol(route.protocol, route.endpoint, api_key, route.id, system_prompt, settings.reasoning_effort, settings.reasoning_visible)


def _by_protocol(protocol: str, endpoint: str, api_key: str, model: str, system_prompt: str, reasoning_effort: str = "medium", reasoning_visible: bool = False) -> Provider:
    if protocol == "responses":
        return ResponsesProvider(endpoint, api_key, model, system_prompt)
    if protocol == "messages":
        return MessagesProvider(endpoint, api_key, model, system_prompt)
    if protocol == "google":
        return GoogleProvider(endpoint, api_key, model, system_prompt)
    return ChatCompletionsProvider(endpoint, api_key, model, system_prompt, None, reasoning_effort, reasoning_visible)
