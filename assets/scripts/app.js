import { Orb } from "./orb.js";

const $ = id => document.getElementById(id);
const orb = new Orb($("orb"));
const steps = $("steps");
const stepsEmpty = $("stepsEmpty");
let socket = null;
let listening = false;
let responseBuffer = "";
let responseStep = null;
let settings = null;
let catalog = { providers: {}, defaults: {} };
let activeApproval = null;
let interfaceMode = "voice";
let textAttachments = [];
let sessionItems = [];
let showArchived = false;
let sessionSearchQuery = "";
let sidebarCollapsed = localStorage.getItem("webviewda.sidebar.collapsed") === "1";
let textResponseBubble = null;
let textResponseContent = null;
let thinkingBubble = null;
let thinkingTools = null;
let textRequestActive = false;
let dictationTarget = "";
let visualizerHtml = "";
let youtubeApiPromise = null;
let youtubePlayer = null;
let mediaPlaying = false;
let visualizerCount = 0;
let todoState = { items: [], summary: {} };
let memoryState = { items: [], size_chars: 0, max_chars: 12000, path: "" };
let todoFilter = "";
let widgetState = "Готов";
let widgetStep = "Ожидаю команду";
let capturingPtt = false;
let pttBinding = { label: "F8", keyCode: 119, modifiers: 0 };
const subagents = new Map();
const thinkingModes = {
  "off:standard": { label: "Fast", status: "fast" },
  "medium:standard": { label: "Balanced", status: "balanced" },
  "high:standard": { label: "Deep", status: "deep" },
  "high:hermes_duo": { label: "Hermes Duo", status: "Hermes Duo" }
};

const ttsVoices = {
  edge: [
    ["ru-RU-SvetlanaNeural", "Светлана · Neural"],
    ["ru-RU-DmitryNeural", "Дмитрий · Neural"]
  ],
  silero: [
    ["xenia", "Xenia"],
    ["baya", "Baya"],
    ["kseniya", "Kseniya"],
    ["aidar", "Aidar"],
    ["eugene", "Eugene"]
  ]
};

const labels = {
  idle: ["Готов", "Нажмите микрофон или введите запрос"],
  monitoring: ["Ожидаю обращение", "Скажите ключевую фразу или нажмите микрофон"],
  armed: ["Слушаю команду", "Говорите, я отвечу на следующую фразу"],
  ptt: ["Рация активна", "Говорите, пока удерживаете кнопку"],
  follow_up: ["Диалог активен", "Можно продолжить без ключевой фразы"],
  listening: ["Слушаю", "Говорите свободно, пауза завершит фразу"],
  speech_detected: ["Слышу вас", "Фраза распознаётся в реальном времени"],
  transcribing: ["Распознаю", "Завершаю обработку голоса"],
  thinking: ["Думаю", "Выполняю запрос"],
  speaking: ["Отвечаю", "Озвучиваю ответ"],
  interrupted: ["Остановлено", "Готов к новой команде"],
  error: ["Ошибка", "Подробности показаны ниже"]
};

function native(command, payload = {}) {
  window.chrome.webview.postMessage(JSON.stringify({ command, payload }));
}

function backend(command, payload = {}) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    showError("Соединение", "Backend не подключён");
    return;
  }
  socket.send(JSON.stringify({ command, payload }));
}

function compactWidgetStep(text) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  if (!value) return "Ожидаю команду";
  if (value.startsWith("Ответ:")) return responseBuffer ? "Пишу ответ…" : "Ответ готов";
  if (value.startsWith("Запрос:")) return "Запрос принят";
  const clean = value.replace(/^Инструмент:/, "Tool:");
  return clean.length > 92 ? `${clean.slice(0, 89)}…` : clean;
}

function syncWidget() {
  native("widget.update", { state: widgetState, step: compactWidgetStep(widgetStep) });
}

function setState(state, detail = "") {
  const label = labels[state] || labels.idle;
  $("stateTitle").textContent = label[0];
  $("stateDetail").textContent = detail || label[1];
  widgetState = label[0];
  if (detail) {
    widgetStep = detail;
  }
  syncWidget();
  orb.setState(state);
  $("listenButton").classList.toggle("active", ["listening", "speech_detected", "armed", "follow_up", "ptt"].includes(state));
}

function setPartial(text) {
  const element = $("liveTranscript");
  element.textContent = text;
  element.classList.toggle("hidden", !text);
}

function addStep(text, kind = "") {
  stepsEmpty.classList.add("hidden");
  const item = document.createElement("div");
  item.className = `step ${kind}`.trim();
  item.textContent = text;
  steps.appendChild(item);
  widgetStep = String(text || "");
  syncWidget();
  while (steps.querySelectorAll(".step").length > 28) {
    steps.querySelector(".step").remove();
  }
  steps.scrollTop = steps.scrollHeight;
  return item;
}

function updateStreamingResponse(text) {
  if (!responseStep) {
    responseStep = addStep("", "response streaming");
  }
  responseStep.textContent = `Ответ: ${text}`;
  widgetStep = "Пишу ответ…";
  syncWidget();
  steps.scrollTop = steps.scrollHeight;
}

function finishStreamingResponse(text) {
  if (responseStep) {
    responseStep.classList.remove("streaming");
    responseStep.textContent = `Ответ: ${text}`;
    widgetStep = "Ответ готов";
    syncWidget();
    responseStep = null;
  } else if (text) {
    addStep(`Ответ: ${text}`, "response");
  }
}

function showError(title, message) {
  $("errorTitle").textContent = title || "Ошибка";
  $("errorText").textContent = message || "Неизвестная ошибка";
  $("errorToast").classList.remove("hidden");
  addStep(`${title || "Ошибка"}: ${message || "Неизвестная ошибка"}`, "error");
}

function hideError() {
  $("errorToast").classList.add("hidden");
}

function openSetup() {
  $("setupPanel").classList.remove("hidden");
  $("shade").classList.add("visible");
}

function closeSetup() {
  $("setupPanel").classList.add("hidden");
  if (!$("settingsPanel").classList.contains("visible")) {
    $("shade").classList.remove("visible");
  }
}

function applyComponentStatus(component, value) {
  const row = $(`component-${component}`);
  if (!row) {
    return;
  }
  const states = { idle: "Ожидает", loading: "Загружается…", ready: "Готово", error: "Ошибка" };
  row.classList.remove("loading", "ready", "error");
  const state = value && value.state ? value.state : "idle";
  if (state !== "idle") {
    row.classList.add(state);
  }
  row.querySelector("strong").textContent = states[state] || state;
}

function renderModelStatus(payload) {
  const models = payload && payload.models ? payload.models : {};
  ["vad", "stt", "tts"].forEach(component => applyComponentStatus(component, models[component]));
}

function showModelStatus(text, done = false) {
  const element = $("modelStatus");
  element.textContent = text;
  element.classList.remove("hidden");
  element.classList.toggle("ready", done);
  if (done) {
    setTimeout(() => element.classList.add("hidden"), 2800);
  }
}

function setPreparationProgress(completed, total) {
  const value = total > 0 ? Math.round((completed / total) * 100) : 0;
  $("setupProgress").style.width = `${value}%`;
}


function renderSubagents() {
  const rail = $("subagentRail");
  rail.replaceChildren();
  const active = Array.from(subagents.values()).slice(-3);
  rail.classList.toggle("hidden", active.length === 0);
  active.forEach(item => {
    const card = document.createElement("article");
    card.className = `subagent-card ${item.state || "running"}`;
    const title = document.createElement("strong");
    title.textContent = item.title || "Субагент";
    const detail = document.createElement("span");
    detail.textContent = item.detail || (item.state === "running" ? "Работает…" : "Готово");
    card.append(title, detail);
    rail.appendChild(card);
  });
}

function updateSubagent(payload) {
  const current = subagents.get(payload.id) || {};
  subagents.set(payload.id, { ...current, ...payload });
  renderSubagents();
}

function toggleOrganizer(visible, tab = "") {
  $("organizerPanel").classList.toggle("visible", visible);
  $("organizerPanel").setAttribute("aria-hidden", String(!visible));
  $("shade").classList.toggle("visible", visible || $("settingsPanel").classList.contains("visible") || !$("setupPanel").classList.contains("hidden"));
  if (tab) {
    selectOrganizerTab(tab);
  }
}

function selectOrganizerTab(tab) {
  const memory = tab === "memory";
  $("todoTab").classList.toggle("active", !memory);
  $("memoryTab").classList.toggle("active", memory);
  $("todoSection").classList.toggle("hidden", memory);
  $("memorySection").classList.toggle("hidden", !memory);
}

function renderTodos(payload) {
  todoState = payload || { items: [], summary: {} };
  const summary = todoState.summary || {};
  const openCount = Number(summary.todo || 0) + Number(summary.later || 0);
  $("todoSummary").textContent = `${summary.todo || 0} в работе · ${summary.important || 0} важных · ${summary.done || 0} готово`;
  $("todoBadge").textContent = openCount > 99 ? "99+" : String(openCount);
  $("todoBadge").classList.toggle("hidden", openCount === 0);
  const list = $("todoList");
  list.replaceChildren();
  const items = (todoState.items || []).filter(item => !todoFilter || item.status === todoFilter);
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Здесь пока ничего нет";
    list.appendChild(empty);
    return;
  }
  items.forEach(item => {
    const card = document.createElement("article");
    card.className = `todo-card ${item.priority === "important" ? "important" : ""} ${item.status === "done" ? "done" : ""}`.trim();
    const title = document.createElement("div");
    title.className = "card-title";
    title.textContent = item.title;
    const meta = document.createElement("div");
    meta.className = "card-meta";
    meta.textContent = `${item.kind === "note" ? "заметка" : "задача"} · ${item.priority === "important" ? "важно" : item.status === "later" ? "потом" : item.status === "done" ? "сделано" : "надо"}`;
    card.append(title, meta);
    if (item.body) {
      const body = document.createElement("p");
      body.className = "card-body";
      body.textContent = item.body;
      card.appendChild(body);
    }
    const actions = document.createElement("div");
    actions.className = "card-actions";
    const action = (label, payload, danger = false) => {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.classList.toggle("danger", danger);
      button.addEventListener("click", () => backend(payload.command, payload.value));
      actions.appendChild(button);
    };
    if (item.status !== "done") {
      action("Готово", { command: "todo.update", value: { id: item.id, status: "done" } });
    } else {
      action("Вернуть", { command: "todo.update", value: { id: item.id, status: "todo" } });
    }
    action(item.priority === "important" ? "Снять важность" : "Важно", { command: "todo.update", value: { id: item.id, priority: item.priority === "important" ? "normal" : "important" } });
    if (item.status !== "later") {
      action("Потом", { command: "todo.update", value: { id: item.id, status: "later" } });
    }
    action("Удалить", { command: "todo.delete", value: { id: item.id } }, true);
    card.appendChild(actions);
    list.appendChild(card);
  });
}

function renderMemory(payload) {
  memoryState = payload || { items: [], size_chars: 0, max_chars: 12000, path: "" };
  const percent = Math.min(100, Math.round((Number(memoryState.size_chars || 0) / Math.max(1, Number(memoryState.max_chars || 1))) * 100));
  $("memoryMeter").style.width = `${percent}%`;
  $("memoryPath").textContent = `${memoryState.size_chars || 0} / ${memoryState.max_chars || 0} символов · ${memoryState.path || "memory.md"}`;
  const list = $("memoryList");
  list.replaceChildren();
  if (!(memoryState.items || []).length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Долговременная память пуста";
    list.appendChild(empty);
    return;
  }
  memoryState.items.forEach(item => {
    const card = document.createElement("article");
    card.className = "memory-card";
    const meta = document.createElement("div");
    meta.className = "card-meta";
    meta.textContent = `${item.category} · важность ${item.importance}`;
    const body = document.createElement("p");
    body.className = "card-body";
    body.textContent = item.text;
    const actions = document.createElement("div");
    actions.className = "card-actions";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Забыть";
    remove.addEventListener("click", () => backend("memory.delete", { id: item.id }));
    actions.appendChild(remove);
    card.append(meta, body, actions);
    list.appendChild(card);
  });
}

function escapeHtml(value) {
  return String(value || "").replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;");
}

function loadYouTubeApi() {
  if (window.YT && window.YT.Player) {
    return Promise.resolve();
  }
  if (youtubeApiPromise) {
    return youtubeApiPromise;
  }
  youtubeApiPromise = new Promise(resolve => {
    const previous = window.onYouTubeIframeAPIReady;
    window.onYouTubeIframeAPIReady = () => {
      if (typeof previous === "function") {
        previous();
      }
      resolve();
    };
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    script.async = true;
    document.head.appendChild(script);
  });
  return youtubeApiPromise;
}

async function playInternalMusic(payload) {
  const videoId = String(payload.video_id || "");
  if (!videoId) {
    showError("Плеер", "Не удалось определить YouTube video id.");
    return;
  }
  $("mediaDock").classList.remove("hidden");
  $("mediaDock").setAttribute("aria-hidden", "false");
  $("mediaTitle").textContent = payload.title || "Музыка";
  await loadYouTubeApi();
  if (youtubePlayer) {
    youtubePlayer.loadVideoById(videoId);
    youtubePlayer.playVideo();
    return;
  }
  youtubePlayer = new YT.Player("youtubePlayer", {
    videoId,
    playerVars: { autoplay: 1, controls: 1, playsinline: 1, rel: 0 },
    events: {
      onReady: event => event.target.playVideo(),
      onStateChange: event => {
        mediaPlaying = event.data === YT.PlayerState.PLAYING;
        $("mediaToggle").textContent = mediaPlaying ? "Ⅱ" : "▶";
      }
    }
  });
}

function controlInternalMusic(action) {
  if (!youtubePlayer) {
    return;
  }
  if (action === "play") youtubePlayer.playVideo();
  if (action === "pause") youtubePlayer.pauseVideo();
  if (action === "stop") {
    youtubePlayer.stopVideo();
    $("mediaDock").classList.add("hidden");
    $("mediaDock").setAttribute("aria-hidden", "true");
  }
  if (action === "mute") {
    if (youtubePlayer.isMuted()) youtubePlayer.unMute(); else youtubePlayer.mute();
  }
  if (action === "volume_up") youtubePlayer.setVolume(Math.min(100, youtubePlayer.getVolume() + 10));
  if (action === "volume_down") youtubePlayer.setVolume(Math.max(0, youtubePlayer.getVolume() - 10));
  if (action === "expand") $("mediaDock").classList.add("expanded");
  if (action === "collapse") $("mediaDock").classList.remove("expanded");
}

function toggleVisualizer(visible) {
  $("visualizerPanel").classList.toggle("hidden", !visible);
  $("visualizerPanel").setAttribute("aria-hidden", String(!visible));
}

function wrapVisualizerContent(html, mode = "replace") {
  const safe = String(html || "").trim();
  if (!safe) {
    return '<div class="visualizer-empty"></div>';;
  }
  if (mode === "append") {
    visualizerCount += 1;
    return `<section class="visualizer-block" data-viz-block="${visualizerCount}">${safe}</section>`;
  }
  visualizerCount = 1;
  return `<div class="visualizer-canvas"><section class="visualizer-block" data-viz-block="1">${safe}</section></div>`;
}

function updateVisualizer(payload) {
  const action = payload.action || "show";
  const surface = $("visualizerSurface");
  if (action === "hide") {
    visualizerHtml = "";
    visualizerCount = 0;
    surface.innerHTML = "";
    toggleVisualizer(false);
    return;
  }
  if (payload.title) {
    $("visualizerTitle").textContent = payload.title;
  }
  const fragment = String(payload.html || "");
  if (action === "show" || action === "replace") {
    visualizerHtml = fragment;
    surface.innerHTML = wrapVisualizerContent(fragment, "replace");
  } else if (action === "append") {
    if (!surface.querySelector('.visualizer-canvas')) {
      surface.innerHTML = '<div class="visualizer-canvas"></div>';
      visualizerCount = 0;
    }
    surface.querySelector('.visualizer-canvas').insertAdjacentHTML('beforeend', wrapVisualizerContent(fragment, "append"));
    visualizerHtml += fragment;
  }
  if (!surface.innerHTML.trim()) {
    surface.innerHTML = '<div class="visualizer-empty"></div>';;
  }
  toggleVisualizer(true);
  surface.scrollTop = surface.scrollHeight;
}

function setInterfaceMode(mode, persist = false) {
  interfaceMode = mode === "text" ? "text" : "voice";
  document.querySelector(".app").classList.toggle("text-mode", interfaceMode === "text");
  $("textWorkspace").classList.toggle("hidden", interfaceMode !== "text");
  $("voiceModeButton").classList.toggle("active", interfaceMode === "voice");
  $("textModeButton").classList.toggle("active", interfaceMode === "text");
  if (persist) {
    backend("settings.save", { ui_mode: interfaceMode });
  }
}

function formatChatTime(value) {
  if (!value) {
    return "";
  }
  try {
    return new Date(value).toLocaleString("ru-RU", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
  } catch (_) {
    return "";
  }
}

function setSidebarCollapsed(collapsed) {
  sidebarCollapsed = Boolean(collapsed);
  $("textWorkspace").classList.toggle("sidebar-collapsed", sidebarCollapsed);
  $("chatSidebar").classList.toggle("collapsed", sidebarCollapsed);
  localStorage.setItem("webviewda.sidebar.collapsed", sidebarCollapsed ? "1" : "0");
}

function startSessionRename(item, session) {
  const input = document.createElement("input");
  input.className = "session-rename";
  input.value = session.title || "Новый диалог";
  item.querySelector(".session-main").replaceWith(input);
  input.focus();
  input.select();
  const commit = () => {
    const value = input.value.trim();
    if (value && value !== session.title) {
      backend("conversation.rename", { id: session.id, title: value });
    } else {
      renderSessionList(sessionItems, sessionItems.find(value => value.active)?.id || "");
    }
  };
  input.addEventListener("keydown", event => {
    if (event.key === "Enter") { event.preventDefault(); commit(); }
    if (event.key === "Escape") { renderSessionList(sessionItems, sessionItems.find(value => value.active)?.id || ""); }
  });
  input.addEventListener("blur", commit, { once: true });
}

function renderSessionList(items, activeId) {
  sessionItems = items || [];
  const list = $("sessionList");
  list.replaceChildren();
  const archivedCount = sessionItems.filter(session => session.archived).length;
  $("archiveCount").textContent = String(archivedCount);
  $("showArchivedSessions").classList.toggle("active", showArchived);
  $("showArchivedSessions").querySelector("span").textContent = showArchived ? "Архив" : "Активные";
  const query = sessionSearchQuery.trim().toLowerCase();
  const visibleItems = sessionItems
    .filter(session => Boolean(session.archived) === showArchived)
    .filter(session => !query || String(session.title || "").toLowerCase().includes(query) || String(session.preview || session.last_message || "").toLowerCase().includes(query));
  visibleItems.forEach(session => {
    const row = document.createElement("article");
    row.className = `session-item ${session.id === activeId || session.active ? "active" : ""}`.trim();
    const main = document.createElement("button");
    main.type = "button";
    main.className = "session-main";
    const title = document.createElement("strong");
    title.textContent = session.title || "Новый диалог";
    const preview = document.createElement("span");
    preview.className = "session-preview";
    preview.textContent = session.preview || session.last_message || "Пустой диалог";
    const date = document.createElement("small");
    date.textContent = formatChatTime(session.updated_at);
    main.append(title, preview, date);
    main.addEventListener("click", () => backend("conversation.select", { id: session.id }));
    const actions = document.createElement("div");
    actions.className = "session-actions";
    const rename = document.createElement("button");
    rename.type = "button";
    rename.title = "Переименовать";
    rename.innerHTML = '<svg class="outline-icon" viewBox="0 0 24 24"><path d="m4 20 4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10L4 20Z"/></svg>';
    rename.addEventListener("click", event => { event.stopPropagation(); startSessionRename(row, session); });
    const archive = document.createElement("button");
    archive.type = "button";
    archive.title = session.archived ? "Вернуть из архива" : "В архив";
    archive.innerHTML = session.archived ? '<svg class="outline-icon" viewBox="0 0 24 24"><path d="M5 8h14v12H5zM4 4h16v4H4z"/><path d="M12 16v-6M9 13l3-3 3 3"/></svg>' : '<svg class="outline-icon" viewBox="0 0 24 24"><path d="M5 8h14v12H5zM4 4h16v4H4z"/><path d="M9 13h6"/></svg>';
    archive.addEventListener("click", event => { event.stopPropagation(); backend("conversation.archive", { id: session.id, archived: !session.archived }); });
    const remove = document.createElement("button");
    remove.type = "button";
    remove.title = "Удалить";
    remove.className = "danger";
    remove.innerHTML = '<svg class="outline-icon" viewBox="0 0 24 24"><path d="M5 7h14M9 7V4h6v3M8 7v13h8V7"/></svg>';
    remove.addEventListener("click", event => {
      event.stopPropagation();
      const name = session.title || "Новый диалог";
      if (confirm(`Удалить чат «${name}»?`)) {
        backend("conversation.delete", { id: session.id });
      }
    });
    actions.append(rename, archive, remove);
    row.append(main, actions);
    list.appendChild(row);
  });
  if (!list.childElementCount) {
    const empty = document.createElement("p");
    empty.className = "session-empty";
    empty.textContent = query ? "Ничего не найдено" : (showArchived ? "Архив пуст" : "Нет чатов");
    list.appendChild(empty);
  }
}

function scrollChatToBottom() {
  const target = $("chatMessages");
  target.scrollTop = target.scrollHeight;
}

function createAttachmentBadge(item) {
  const badge = document.createElement("div");
  badge.className = `message-attachment ${item.kind || "file"}`;
  const preview = document.createElement("div");
  preview.className = "message-attachment-preview";
  if ((item.kind === "image" || String(item.type || "").startsWith("image/")) && item.data_url) {
    const image = document.createElement("img");
    image.src = item.data_url;
    image.alt = item.name || "image";
    preview.appendChild(image);
  } else {
    preview.textContent = attachmentExtension(item.name || "file");
  }
  const meta = document.createElement("div");
  meta.className = "message-attachment-meta";
  const name = document.createElement("strong");
  name.textContent = item.name || "file";
  const size = document.createElement("span");
  size.textContent = formatFileSize(Number(item.size) || 0);
  meta.append(name, size);
  badge.append(preview, meta);
  return badge;
}

function appendChatMessage(role, content, createdAt = "", attachments = []) {
  const item = document.createElement("article");
  item.className = `chat-message ${role === "user" ? "user" : "assistant"}`;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  const body = document.createElement("div");
  body.className = "message-content";
  body.textContent = content || (attachments.length ? "Вложения" : "");
  bubble.appendChild(body);
  if (attachments.length) {
    const list = document.createElement("div");
    list.className = "message-attachments";
    attachments.forEach(attachment => list.appendChild(createAttachmentBadge(attachment)));
    bubble.appendChild(list);
  }
  const time = document.createElement("time");
  time.textContent = formatChatTime(createdAt);
  item.append(bubble, time);
  $("chatEmpty").classList.add("hidden");
  $("chatMessages").appendChild(item);
  scrollChatToBottom();
  return body;
}

function renderChat(payload) {
  renderSessionList(payload.items || [], payload.active_id);
  const active = (payload.items || []).find(item => item.id === payload.active_id || item.active);
  $("activeChatTitle").textContent = active ? active.title : "Новый диалог";
  if (textRequestActive && interfaceMode === "text" && (thinkingBubble || textResponseContent)) {
    return;
  }
  const target = $("chatMessages");
  target.replaceChildren();
  const messages = payload.messages || [];
  $("chatEmpty").classList.toggle("hidden", messages.length > 0);
  if (!messages.length) {
    target.appendChild($("chatEmpty"));
  } else {
    messages.forEach(message => appendChatMessage(message.role, message.content, message.created_at));
  }
  textResponseBubble = null;
  textResponseContent = null;
  thinkingBubble = null;
  thinkingTools = null;
}

function showThinkingBubble(detail = "") {
  if (interfaceMode !== "text") return;
  if (thinkingBubble) {
    const label = thinkingBubble.querySelector(".thinking-label");
    if (label && detail) label.textContent = detail;
    scrollChatToBottom();
    return;
  }
  $("chatEmpty").classList.add("hidden");
  const item = document.createElement("article");
  item.className = "chat-message assistant thinking-message";
  const bubble = document.createElement("div");
  bubble.className = "bubble thinking-bubble";
  const row = document.createElement("div");
  row.className = "thinking-row";
  const dots = document.createElement("span");
  dots.className = "thinking-dots";
  dots.innerHTML = "<i></i><i></i><i></i>";
  const label = document.createElement("span");
  label.className = "thinking-label";
  label.textContent = detail || "Думаю над ответом";
  row.append(dots, label);
  thinkingTools = document.createElement("div");
  thinkingTools.className = "tool-call-list hidden";
  bubble.append(row, thinkingTools);
  item.appendChild(bubble);
  $("chatMessages").appendChild(item);
  thinkingBubble = item;
  scrollChatToBottom();
}

function clearThinkingBubble() {
  if (thinkingBubble) {
    thinkingBubble.remove();
  }
  thinkingBubble = null;
  thinkingTools = null;
}

function recordToolCall(name, state = "running", result = "") {
  if (interfaceMode !== "text") return;
  showThinkingBubble("Выполняю инструменты");
  thinkingTools.classList.remove("hidden");
  const item = document.createElement("div");
  item.className = `tool-call ${state}`;
  const dot = document.createElement("span");
  dot.className = "tool-call-dot";
  const title = document.createElement("strong");
  title.textContent = name || "tool";
  const status = document.createElement("span");
  status.textContent = state === "done" ? "готово" : state === "error" ? "ошибка" : "работает";
  item.append(dot, title, status);
  if (result) {
    const small = document.createElement("small");
    small.textContent = result;
    item.appendChild(small);
  }
  thinkingTools.appendChild(item);
  scrollChatToBottom();
}

function streamChatDelta(delta) {
  if (interfaceMode !== "text") {
    return;
  }
  clearThinkingBubble();
  if (!textResponseContent) {
    textResponseContent = appendChatMessage("assistant", "");
    textResponseBubble = textResponseContent;
    textResponseContent.closest(".bubble").classList.add("streaming");
  }
  textResponseContent.textContent += delta;
  scrollChatToBottom();
}

function finishChatResponse(text = "") {
  clearThinkingBubble();
  if (interfaceMode === "text" && !textResponseContent && text) {
    textResponseContent = appendChatMessage("assistant", text);
  } else if (textResponseContent && text && !textResponseContent.textContent.trim()) {
    textResponseContent.textContent = text;
  }
  if (textResponseContent) {
    const bubble = textResponseContent.closest(".bubble");
    if (bubble) bubble.classList.remove("streaming");
  }
  textResponseContent = null;
  textResponseBubble = null;
  textRequestActive = false;
}

function renderEditCard(payload) {
  const card = document.createElement("div");
  card.className = "edit-pill";
  card.innerHTML = `<svg class="outline-icon" viewBox="0 0 24 24"><path d="m4 20 4.5-1 10-10a2.1 2.1 0 0 0-3-3l-10 10L4 20Z"/><path d="m13.5 7.5 3 3"/></svg><span>editing file</span><span class="path"></span><span class="diff-minus">-${Number(payload.removed) || 0}</span><span class="diff-plus">+${Number(payload.added) || 0}</span>`;
  card.querySelector(".path").textContent = payload.path || "file";
  $("chatEmpty").classList.add("hidden");
  $("chatMessages").appendChild(card);
  $("chatMessages").scrollTop = $("chatMessages").scrollHeight;
}

function attachmentExtension(name) {
  const value = String(name || "");
  const index = value.lastIndexOf(".");
  return index > 0 ? value.slice(index + 1).toUpperCase().slice(0, 6) : "FILE";
}

function formatFileSize(size) {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(2)} MB`;
}

function attachmentClass(file) {
  const ext = `.${attachmentExtension(file.name).toLowerCase()}`;
  if ([".java", ".cpp", ".hpp", ".h", ".py", ".js", ".ts", ".json", ".cmake", ".xml", ".css", ".html"].includes(ext)) return "code";
  if (file.type.startsWith("image/")) return "image";
  if ([".log", ".txt", ".md", ".crash"].includes(ext)) return "log";
  return "file";
}

async function encodeAttachment(file) {
  const item = { name: file.name, type: file.type || "application/octet-stream", size: file.size, kind: attachmentClass(file) };
  if (file.type.startsWith("image/")) {
    if (file.size > 6 * 1024 * 1024) throw new Error(`${file.name}: изображение больше шести мегабайт`);
    item.data_url = await new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = () => reject(new Error(`Не удалось прочитать ${file.name}`));
      reader.readAsDataURL(file);
    });
    return item;
  }
  if (file.size > 2 * 1024 * 1024) throw new Error(`${file.name}: текстовый файл больше двух мегабайт`);
  item.content = await file.text();
  return item;
}

function createComposerAttachment(item, index) {
  const chip = document.createElement("div");
  chip.className = `attachment-chip ${item.kind}`;
  const preview = document.createElement("div");
  preview.className = "attachment-preview";
  if (item.kind === "image" && item.data_url) {
    const image = document.createElement("img");
    image.src = item.data_url;
    image.alt = item.name;
    preview.appendChild(image);
  } else {
    preview.textContent = attachmentExtension(item.name);
  }
  const meta = document.createElement("div");
  meta.className = "attachment-meta";
  const name = document.createElement("span");
  name.className = "attachment-name";
  name.textContent = item.name;
  const size = document.createElement("span");
  size.className = "attachment-size";
  size.textContent = formatFileSize(item.size);
  meta.append(name, size);
  const remove = document.createElement("button");
  remove.className = "attachment-remove";
  remove.type = "button";
  remove.textContent = "×";
  remove.addEventListener("click", () => {
    textAttachments.splice(index, 1);
    renderAttachments();
  });
  chip.append(preview, meta, remove);
  return chip;
}

function renderAttachments() {
  const strip = $("attachmentStrip");
  strip.replaceChildren();
  strip.classList.toggle("hidden", textAttachments.length === 0);
  textAttachments.forEach((item, index) => strip.appendChild(createComposerAttachment(item, index)));
  updateComposerStatus();
}

async function attachFiles(files) {
  for (const file of Array.from(files).slice(0, 8 - textAttachments.length)) {
    try {
      textAttachments.push(await encodeAttachment(file));
    } catch (error) {
      showError("Вложение", error.message);
    }
  }
  renderAttachments();
}

function autosizeTextPrompt() {
  const field = $("textPrompt");
  field.style.height = "auto";
  field.style.height = `${Math.min(170, Math.max(48, field.scrollHeight))}px`;
}

function updateThinkingControl() {
  const select = $("textThinkingMode");
  const current = thinkingModes[select.value] || thinkingModes["medium:standard"];
  $("thinkingLabel").textContent = current.label;
  document.querySelectorAll("#thinkingMenu button").forEach(button => button.classList.toggle("active", button.dataset.value === select.value));
}

function setThinkingControl(value, persist = true) {
  $("textThinkingMode").value = value;
  updateThinkingControl();
  applyThinkingMode(value, persist);
  updateComposerStatus();
}

function updateComposerStatus() {
  const parts = [];
  parts.push($("textWebSearch").checked ? "web" : "local");
  if (textAttachments.length) {
    parts.push(`${textAttachments.length} влож.`);
  }
  const current = thinkingModes[$("textThinkingMode").value] || thinkingModes["medium:standard"];
  parts.push(current.status);
  $("composerStatusLabel").textContent = parts.join(" · ");
  updateThinkingControl();
}

function sendTextPrompt() {
  const value = $("textPrompt").value.trim();
  if (!value && !textAttachments.length) {
    return;
  }
  const outgoingAttachments = textAttachments.map(item => ({ ...item }));
  responseBuffer = "";
  textResponseBubble = null;
  textResponseContent = null;
  textRequestActive = true;
  appendChatMessage("user", value || "Вложения", "", outgoingAttachments);
  showThinkingBubble("Думаю над ответом");
  backend("assistant.send", { text: value, attachments: outgoingAttachments, web_search: $("textWebSearch").checked });
  $("textPrompt").value = "";
  textAttachments = [];
  renderAttachments();
  autosizeTextPrompt();
  updateComposerStatus();
}

function applyThinkingMode(value, persist = true) {
  const [reasoning, strategy] = String(value || "medium:standard").split(":");
  if (persist) {
    backend("settings.save", { reasoning_effort: reasoning, agent_strategy: strategy });
  }
}

function connectBackend(info) {
  if (!info.online) {
    setState("error", info.error || "Backend не запущен");
    showError("Backend", info.error || "Backend не запущен");
    return;
  }
  let attempts = 0;
  const open = () => {
    attempts += 1;
    socket = new WebSocket(`${info.url}?token=${encodeURIComponent(info.token)}`);
    socket.addEventListener("message", event => receive(JSON.parse(event.data)));
    socket.addEventListener("close", () => {
      if (attempts < 20) {
        setTimeout(open, 250);
      } else {
        setState("error", "Python backend недоступен");
        showError("Backend", "Python backend недоступен");
      }
    }, { once: true });
  };
  open();
}

function receive(message) {
  const { event, payload } = message;
  if (event === "backend.ready") {
    setState("idle", `Backend ${payload.version} подключён`);
    backend("models.status");
    return;
  }
  if (event === "settings.current" || event === "settings.changed") {
    settings = payload;
    fillSettings();
    setInterfaceMode(settings.ui_mode || "voice");
    const currentStrategy = settings.agent_strategy === "hermes_duo" ? "high:hermes_duo" : `${settings.reasoning_effort || "medium"}:standard`;
    $("textThinkingMode").value = currentStrategy;
    updateThinkingControl();
    return;
  }
  if (event === "providers.catalog") {
    catalog = payload;
    renderModelField();
    return;
  }
  if (event === "todo.current") {
    renderTodos(payload);
    return;
  }
  if (event === "memory.current") {
    renderMemory(payload);
    return;
  }
  if (event === "visualization.update") {
    updateVisualizer(payload);
    return;
  }
  if (event === "media.play") {
    playInternalMusic(payload);
    return;
  }
  if (event === "media.control") {
    controlInternalMusic(payload.action);
    return;
  }
  if (event === "audio.devices") {
    renderDevices(payload);
    if (payload.error) {
      showError("Аудиоустройства", payload.error);
    }
    return;
  }
  if (event === "assistant.state") {
    listening = payload.listening;
    setState(payload.state);
    $("chatStatus").textContent = (labels[payload.state] || labels.idle)[0];
    return;
  }
  if (event === "audio.level") {
    orb.setLevel(payload.value);
    return;
  }
  if (event === "models.status") {
    renderModelStatus(payload);
    return;
  }
  if (event === "preparation.started") {
    $("setupError").classList.add("hidden");
    $("setupError").textContent = "";
    setPreparationProgress(0, payload.total);
    openSetup();
    return;
  }
  if (event === "preparation.progress") {
    setPreparationProgress(payload.completed, payload.total);
    return;
  }
  if (event === "preparation.finished") {
    setPreparationProgress(payload.completed, payload.total);
    showModelStatus("Голос подготовлен", true);
    return;
  }
  if (event === "preparation.failed") {
    $("setupError").textContent = payload.message;
    $("setupError").classList.remove("hidden");
    showError("Подготовка голоса", payload.message);
    return;
  }
  if (event === "model.loading") {
    showModelStatus(payload.detail || `Загружаю ${payload.model}…`);
    return;
  }
  if (event === "model.ready") {
    showModelStatus(`${payload.model} готов`, true);
    return;
  }
  if (event === "model.error") {
    openSetup();
    $("setupError").textContent = payload.message;
    $("setupError").classList.remove("hidden");
    return;
  }
  if (event === "voice.test.started") {
    setState("speaking", "Проверяю устройство вывода и голос");
    return;
  }
  if (event === "voice.test.finished") {
    showModelStatus("Озвучка работает", true);
    return;
  }
  if (event === "voice.error") {
    showError("Озвучка", payload.message);
    openSetup();
    $("setupError").textContent = payload.message;
    $("setupError").classList.remove("hidden");
    return;
  }
  if (event === "audio.output.fallback") {
    addStep(payload.message, "tool");
    return;
  }
  if (event === "transcript.partial") {
    setPartial(payload.text || "");
    return;
  }
  if (event === "transcript.final") {
    setPartial("");
    responseBuffer = "";
    responseStep = null;
    addStep(`Вы: ${payload.text}`, "input");
    return;
  }
  if (event === "dictation.partial") {
    $("textPrompt").value = payload.text || "";
    autosizeTextPrompt();
    return;
  }
  if (event === "dictation.final") {
    const spoken = String(payload.text || "").trim();
    if (spoken) {
      $("textPrompt").value = `${$("textPrompt").value.trim()} ${spoken}`.trim();
      autosizeTextPrompt();
    }
    $("dictateButton").classList.remove("active");
    return;
  }
  if (event === "file.edit") {
    renderEditCard(payload);
    return;
  }
  if (event === "preferences.updated") {
    if (interfaceMode === "text") {
      const names = (payload.items || []).map(item => item.key).join(", ");
      addStep(`Стиль запомнен: ${names}`, "complete");
    }
    return;
  }
  if (event === "step.add") {
    addStep(payload.text, payload.kind);
    return;
  }
  if (event === "subagent.started") {
    updateSubagent(payload);
    addStep(`Субагент: ${payload.title}`, "tool");
    return;
  }
  if (event === "subagent.progress") {
    updateSubagent({ ...payload, state: "running" });
    return;
  }
  if (event === "subagent.finished") {
    updateSubagent(payload);
    addStep(`Субагент ${payload.title}: ${payload.state === "done" ? "завершил работу" : "ошибка"}`, payload.state === "done" ? "complete" : "error");
    return;
  }
  if (event === "agent.iteration") {
    setState("thinking", `Шаг агента ${payload.current} из ${payload.maximum}`);
    return;
  }
  if (event === "agent.tool_started") {
    addStep(`Инструмент: ${payload.name}`, "tool");
    recordToolCall(payload.name, "running");
    return;
  }
  if (event === "agent.tool_finished") {
    addStep(`${payload.name}: выполнено`, "complete");
    recordToolCall(payload.name, "done");
    return;
  }
  if (event === "agent.approval_required") {
    showApproval(payload);
    return;
  }
  if (event === "agent.approval_resolved") {
    hideApproval();
    return;
  }
  if (event === "response.delta") {
    responseBuffer += payload.text;
    updateStreamingResponse(responseBuffer);
    streamChatDelta(payload.text);
    return;
  }
  if (event === "response.final") {
    finishStreamingResponse(payload.text || responseBuffer);
    finishChatResponse(payload.text || responseBuffer);
    widgetStep = "Ответ готов";
    syncWidget();
    return;
  }
  if (event === "conversation.current") {
    steps.querySelectorAll(".step").forEach(item => item.remove());
    responseStep = null;
    const messages = payload.messages || [];
    messages.slice(-8).forEach(item => addStep(`${item.role === "user" ? "Вы" : "Ответ"}: ${item.content}`, item.role === "assistant" ? "response" : "input"));
    if (!messages.length) {
      stepsEmpty.classList.remove("hidden");
    }
    renderChat(payload);
    return;
  }
  if (event === "conversation.sessions") {
    renderSessionList(payload.items || [], payload.active_id);
    return;
  }
  if (event === "assistant.error") {
    clearThinkingBubble();
    if (interfaceMode === "text" && textRequestActive) {
      appendChatMessage("assistant", `Ошибка: ${payload.message || "неизвестная ошибка"}`);
      textRequestActive = false;
    }
    setState("error", payload.message);
    showError(payload.scope === "tts" ? "Озвучка" : "Ошибка", payload.message);
    return;
  }
  if (event === "assistant.thinking") {
    showThinkingBubble("Думаю над ответом");
  }
  if (event.startsWith("assistant.")) {
    const state = event.substring("assistant.".length);
    listening = ["listening", "speech_detected", "armed", "follow_up"].includes(state);
    setState(state, payload.message || "");
    $("chatStatus").textContent = (labels[state] || labels.idle)[0];
  }
}

function showApproval(payload) {
  activeApproval = payload.id;
  setState("thinking", "Ожидаю подтверждение действия");
  $("approvalSummary").textContent = payload.summary;
  $("approvalDetails").textContent = JSON.stringify(payload.details, null, 2);
  $("approvalPanel").classList.remove("hidden");
}

function hideApproval() {
  activeApproval = null;
  $("approvalPanel").classList.add("hidden");
}

function renderModelField() {
  const provider = $("provider").value;
  const isCatalog = provider === "opencode_zen" || provider === "opencode_go" || provider === "freemodel_gpt";
  document.querySelector(".catalog-model-row").classList.toggle("hidden", !isCatalog);
  document.querySelector(".text-model-row").classList.toggle("hidden", isCatalog);
  document.querySelectorAll(".custom-row").forEach(item => item.classList.toggle("hidden", provider !== "custom"));
  document.querySelectorAll(".ollama-row").forEach(item => item.classList.toggle("hidden", provider !== "ollama"));
  if (isCatalog) {
    const select = $("catalogModel");
    const current = settings && settings.provider === provider ? settings.model : catalog.defaults[provider];
    select.innerHTML = "";
    (catalog.providers[provider] || []).forEach(model => {
      const option = document.createElement("option");
      option.value = model.id;
      option.textContent = `${model.label} · ${model.protocol}${model.free ? " · free" : ""}`;
      option.selected = model.id === current;
      select.appendChild(option);
    });
    $("providerHint").textContent = provider === "freemodel_gpt" ? "FreeModel GPT: OpenAI-compatible Chat Completions через api.freemodel.dev." : provider === "opencode_go" ? "Go: подписка, маршрутизация API зависит от модели." : "Zen: pay-as-you-go; free-модели могут иметь особые условия данных.";
  } else if (provider === "ollama") {
    if (settings && settings.provider === "ollama") {
      $("model").value = settings.model || "llama3.2";
    } else if (!$("model").value.trim() || $("model").value.includes("/")) {
      $("model").value = catalog.defaults.ollama || "llama3.2";
    }
    $("providerHint").textContent = "Ollama работает через локальный REST API. Убедитесь, что Ollama запущен, а модель скачана командой ollama pull <model>.";
  } else {
    $("providerHint").textContent = provider === "openrouter" ? "OpenRouter использует streaming Chat Completions и tools." : "Endpoint должен поддерживать выбранный streaming protocol и tools для agent mode.";
  }
  const names = { freemodel_gpt: "freemodel", opencode_zen: "zen", opencode_go: "go", openrouter: "openrouter", ollama: "ollama", custom: "custom" };
  $("providerPill").textContent = names[provider] || provider;
  if (provider === "ollama") {
    $("apiKey").placeholder = "Ollama не требует API key";
  } else if (settings) {
    $("apiKey").placeholder = settings.has_api_key ? "Ключ сохранён · введите новый для замены" : "Сохранится в защищённом хранилище Windows";
  }
}

function renderDevices(value) {
  const fill = (id, items, selected) => {
    const select = $(id);
    const target = settings ? settings[selected] : "";
    select.innerHTML = '<option value="">Системное устройство</option>';
    (items || []).forEach(device => {
      const option = document.createElement("option");
      option.value = device.id;
      option.textContent = device.name;
      option.selected = device.id === target;
      select.appendChild(option);
    });
  };
  fill("inputDevice", value.inputs, "input_device");
  fill("outputDevice", value.outputs, "output_device");
}

function renderTtsVoices() {
  const engine = $("ttsEngine").value || "edge";
  const current = settings && settings.tts_engine === engine ? settings.tts_voice : ttsVoices[engine][0][0];
  const select = $("ttsVoice");
  select.innerHTML = "";
  ttsVoices[engine].forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    option.selected = value === current;
    select.appendChild(option);
  });
}

function keyName(event) {
  const names = {
    Space: "Space",
    Enter: "Enter",
    Escape: "Escape",
    Tab: "Tab",
    Backspace: "Backspace",
    Delete: "Delete",
    Insert: "Insert",
    Home: "Home",
    End: "End",
    PageUp: "Page Up",
    PageDown: "Page Down",
    ArrowUp: "Arrow Up",
    ArrowDown: "Arrow Down",
    ArrowLeft: "Arrow Left",
    ArrowRight: "Arrow Right",
    CapsLock: "Caps Lock",
    ScrollLock: "Scroll Lock"
  };
  if (names[event.code]) {
    return names[event.code];
  }
  if (/^Key[A-Z]$/.test(event.code)) {
    return event.code.substring(3);
  }
  if (/^Digit[0-9]$/.test(event.code)) {
    return event.code.substring(5);
  }
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(event.code)) {
    return event.code;
  }
  return event.key.length === 1 ? event.key.toUpperCase() : event.key;
}

function captureBinding(event) {
  if (["ControlLeft", "ControlRight", "AltLeft", "AltRight", "ShiftLeft", "ShiftRight", "MetaLeft", "MetaRight"].includes(event.code)) {
    return null;
  }
  let modifiers = 0;
  const parts = [];
  if (event.ctrlKey) {
    modifiers |= 1;
    parts.push("Ctrl");
  }
  if (event.altKey) {
    modifiers |= 2;
    parts.push("Alt");
  }
  if (event.shiftKey) {
    modifiers |= 4;
    parts.push("Shift");
  }
  if (event.metaKey) {
    modifiers |= 8;
    parts.push("Win");
  }
  parts.push(keyName(event));
  return { label: parts.join(" + "), keyCode: event.keyCode || event.which, modifiers };
}

function updateBinding(binding) {
  pttBinding = binding;
  $("pttKey").value = binding.label;
}

function showSpeechFields() {
  const vosk = $("sttEngine").value === "vosk";
  document.querySelectorAll(".vosk-row").forEach(item => item.classList.toggle("hidden", !vosk));
  document.querySelectorAll(".whisper-row").forEach(item => item.classList.toggle("hidden", vosk));
  document.querySelectorAll(".wake-row").forEach(item => item.classList.toggle("hidden", $("activationMode").value !== "wake"));
  document.querySelectorAll(".ptt-row").forEach(item => item.classList.toggle("hidden", $("activationMode").value !== "ptt"));
  if ($("echoGuard").checked) {
    $("bargeIn").checked = false;
    $("bargeIn").disabled = true;
  } else {
    $("bargeIn").disabled = false;
  }
}

function fillSettings() {
  if (!settings) {
    return;
  }
  $("provider").value = settings.provider;
  $("model").value = settings.model;
  $("customBaseUrl").value = settings.custom_base_url;
  $("ollamaBaseUrl").value = settings.ollama_base_url || "http://localhost:11434";
  $("customProtocol").value = settings.custom_protocol;
  $("voiceProfile").value = settings.voice_profile;
  $("sttEngine").value = settings.stt_engine;
  $("sttModel").value = settings.stt_model;
  $("voskPath").value = settings.vosk_model_path;
  $("vadEngine").value = settings.vad_engine;
  $("activationMode").value = settings.activation_mode || "wake";
  $("wakePhrases").value = settings.wake_phrases || "ассистент, вебви";
  updateBinding({
    label: settings.ptt_key || "F8",
    keyCode: Number(settings.ptt_vk) || 119,
    modifiers: Number(settings.ptt_modifiers) || 0
  });
  $("followUpSeconds").value = settings.follow_up_seconds || 60;
  $("noiseSuppression").checked = settings.noise_suppression !== false;
  $("noiseStrength").value = settings.noise_strength ?? 0.56;
  $("utteranceSilenceMs").value = settings.utterance_silence_ms || 1450;
  $("utteranceMaxSeconds").value = settings.utterance_max_seconds || 120;
  $("partialTranscription").checked = settings.partial_transcription;
  $("partialInterval").value = settings.partial_interval_ms;
  $("ttsEnabled").checked = settings.tts_enabled;
  $("ttsEngine").value = settings.tts_engine || "edge";
  renderTtsVoices();
  $("ttsVoice").value = settings.tts_voice;
  $("ttsSpeed").value = settings.tts_speed;
  $("ttsPrefetchMs").value = settings.tts_prefetch_ms ?? 170;
  $("ttsBatchChars").value = settings.tts_batch_chars ?? 240;
  $("autoListen").checked = settings.auto_listen;
  $("echoGuard").checked = settings.echo_guard;
  $("bargeIn").checked = settings.barge_in;
  $("agentEnabled").checked = settings.agent_enabled;
  $("workspacePath").value = settings.workspace_path;
  $("agentAllowEdits").checked = settings.agent_allow_edits;
  $("agentAllowCommands").checked = settings.agent_allow_commands;
  $("agentMaxSteps").value = settings.agent_max_steps;
  $("agentCommandTimeout").value = settings.agent_command_timeout;
  $("subagentMaxParallel").value = settings.subagent_max_parallel || 3;
  $("memoryEnabled").checked = settings.memory_enabled !== false;
  $("memoryMaxChars").value = settings.memory_max_chars || 12000;
  $("screenVisionEnabled").checked = settings.screen_vision_enabled !== false;
  $("screenCaptureWithoutConfirmation").checked = settings.screen_capture_without_confirmation === true;
  $("trayWidgetEnabled").checked = settings.tray_widget_enabled !== false;
  $("widgetOrientation").value = settings.widget_orientation || "horizontal";
  $("reasoningEffort").value = settings.reasoning_effort || "medium";
  $("reasoningVisible").checked = settings.reasoning_visible === true;
  $("textWebSearch").checked = settings.web_search_enabled !== false;
  const composerStrategy = settings.agent_strategy === "hermes_duo" ? "high:hermes_duo" : `${settings.reasoning_effort || "medium"}:standard`;
  $("textThinkingMode").value = composerStrategy;
  updateThinkingControl();
  native("ptt.configure", { enabled: settings.activation_mode === "ptt", keyCode: pttBinding.keyCode, modifiers: pttBinding.modifiers });
  native("widget.configure", { enabled: settings.tray_widget_enabled !== false, orientation: settings.widget_orientation || "horizontal" });
  $("apiKey").placeholder = settings.has_api_key ? "Ключ сохранён · введите новый для замены" : "Сохранится в защищённом хранилище Windows";
  renderModelField();
  showSpeechFields();
  updateComposerStatus();
}

function settingsPayload() {
  const provider = $("provider").value;
  const catalogProvider = provider === "opencode_zen" || provider === "opencode_go" || provider === "freemodel_gpt";
  return {
    provider,
    model: catalogProvider ? $("catalogModel").value : $("model").value.trim(),
    api_key: $("apiKey").value.trim(),
    custom_base_url: $("customBaseUrl").value.trim(),
    ollama_base_url: $("ollamaBaseUrl").value.trim(),
    custom_protocol: $("customProtocol").value,
    voice_profile: $("voiceProfile").value,
    stt_engine: $("sttEngine").value,
    stt_model: $("sttModel").value,
    vosk_model_path: $("voskPath").value.trim(),
    vad_engine: $("vadEngine").value,
    activation_mode: $("activationMode").value,
    wake_phrases: $("wakePhrases").value.trim(),
    ptt_key: pttBinding.label,
    ptt_vk: pttBinding.keyCode,
    ptt_modifiers: pttBinding.modifiers,
    follow_up_seconds: Number($("followUpSeconds").value) || 60,
    noise_suppression: $("noiseSuppression").checked,
    noise_strength: Number($("noiseStrength").value) || 0.56,
    utterance_silence_ms: Number($("utteranceSilenceMs").value) || 1450,
    utterance_max_seconds: Number($("utteranceMaxSeconds").value) || 120,
    partial_transcription: $("partialTranscription").checked,
    partial_interval_ms: Number($("partialInterval").value) || 950,
    tts_enabled: $("ttsEnabled").checked,
    tts_engine: $("ttsEngine").value,
    tts_voice: $("ttsVoice").value,
    tts_speed: Number($("ttsSpeed").value) || 1,
    tts_prefetch_ms: Number($("ttsPrefetchMs").value) || 170,
    tts_batch_chars: Number($("ttsBatchChars").value) || 240,
    auto_listen: $("autoListen").checked,
    echo_guard: $("echoGuard").checked,
    barge_in: $("bargeIn").checked,
    input_device: $("inputDevice").value,
    output_device: $("outputDevice").value,
    agent_enabled: $("agentEnabled").checked,
    workspace_path: $("workspacePath").value.trim(),
    agent_allow_edits: $("agentAllowEdits").checked,
    agent_allow_commands: $("agentAllowCommands").checked,
    agent_max_steps: Number($("agentMaxSteps").value) || 12,
    agent_command_timeout: Number($("agentCommandTimeout").value) || 45,
    subagent_max_parallel: Math.max(1, Math.min(3, Number($("subagentMaxParallel").value) || 3)),
    memory_enabled: $("memoryEnabled").checked,
    memory_max_chars: Number($("memoryMaxChars").value) || 12000,
    screen_vision_enabled: $("screenVisionEnabled").checked,
    screen_capture_without_confirmation: $("screenCaptureWithoutConfirmation").checked,
    tray_widget_enabled: $("trayWidgetEnabled").checked,
    widget_orientation: $("widgetOrientation").value,
    reasoning_effort: $("reasoningEffort").value,
    reasoning_visible: $("reasoningVisible").checked,
    web_search_enabled: $("textWebSearch").checked,
    ui_mode: interfaceMode,
    agent_strategy: $("textThinkingMode").value.endsWith("hermes_duo") ? "hermes_duo" : "standard"
  };
}

function toggleSettings(visible) {
  $("settingsPanel").classList.toggle("visible", visible);
  $("shade").classList.toggle("visible", visible || $("organizerPanel").classList.contains("visible") || !$("setupPanel").classList.contains("hidden"));
  $("settingsPanel").setAttribute("aria-hidden", String(!visible));
}

window.chrome.webview.addEventListener("message", event => {
  if (event.data.event === "app.info") {
    connectBackend(event.data.payload.backend);
  }
  if (event.data.event === "native.error") {
    setState("error", event.data.payload.message);
    showError("Приложение", event.data.payload.message);
  }
  if (event.data.event === "ptt.down") {
    backend("assistant.pttDown");
  }
  if (event.data.event === "ptt.up") {
    backend("assistant.pttUp");
  }
});

$("dragRegion").addEventListener("pointerdown", event => {
  if (!event.target.closest("button")) {
    native("window.drag");
  }
});
$("minimizeButton").addEventListener("click", () => native("window.minimize"));
$("closeButton").addEventListener("click", () => native("window.close"));
$("settingsOpen").addEventListener("click", () => {
  toggleOrganizer(false);
  toggleSettings(true);
});
$("settingsClose").addEventListener("click", () => toggleSettings(false));
$("organizerOpen").addEventListener("click", () => {
  toggleSettings(false);
  toggleOrganizer(true);
  backend("todo.list");
  backend("memory.get");
});
$("organizerClose").addEventListener("click", () => toggleOrganizer(false));
$("todoTab").addEventListener("click", () => selectOrganizerTab("todo"));
$("memoryTab").addEventListener("click", () => selectOrganizerTab("memory"));
$("shade").addEventListener("click", () => {
  toggleSettings(false);
  toggleOrganizer(false);
  closeSetup();
});
document.querySelectorAll(".filter").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".filter").forEach(value => value.classList.remove("active"));
  button.classList.add("active");
  todoFilter = button.dataset.filter || "";
  renderTodos(todoState);
}));
$("todoForm").addEventListener("submit", event => {
  event.preventDefault();
  backend("todo.create", {
    kind: $("todoKind").value,
    priority: $("todoPriority").value,
    title: $("todoTitle").value.trim(),
    body: $("todoBody").value.trim()
  });
  $("todoTitle").value = "";
  $("todoBody").value = "";
});
$("memoryForm").addEventListener("submit", event => {
  event.preventDefault();
  backend("memory.add", {
    category: $("memoryCategory").value,
    importance: Number($("memoryImportance").value),
    text: $("memoryText").value.trim()
  });
  $("memoryText").value = "";
});
$("pttRecord").addEventListener("click", () => {
  capturingPtt = true;
  native("ptt.configure", { enabled: false, keyCode: pttBinding.keyCode, modifiers: pttBinding.modifiers });
  $("pttRecord").classList.add("recording");
  $("pttRecord").textContent = "Нажмите…";
});

window.addEventListener("keydown", event => {
  if (!capturingPtt) {
    return;
  }
  event.preventDefault();
  event.stopPropagation();
  if (event.code === "Escape") {
    capturingPtt = false;
    $("pttRecord").classList.remove("recording");
    $("pttRecord").textContent = "Назначить";
    native("ptt.configure", { enabled: settings && settings.activation_mode === "ptt", keyCode: pttBinding.keyCode, modifiers: pttBinding.modifiers });
    return;
  }
  const binding = captureBinding(event);
  if (!binding) {
    return;
  }
  updateBinding(binding);
  capturingPtt = false;
  $("pttRecord").classList.remove("recording");
  $("pttRecord").textContent = "Назначить";
});

$("voiceModeButton").addEventListener("click", () => setInterfaceMode("voice", true));
$("textModeButton").addEventListener("click", () => setInterfaceMode("text", true));
$("textNewSession").addEventListener("click", () => backend("conversation.new"));
$("sidebarToggle").addEventListener("click", () => setSidebarCollapsed(!sidebarCollapsed));
$("showArchivedSessions").addEventListener("click", () => {
  showArchived = !showArchived;
  renderSessionList(sessionItems, sessionItems.find(item => item.active)?.id || "");
});
$("sessionSearch").addEventListener("input", event => {
  sessionSearchQuery = event.target.value || "";
  renderSessionList(sessionItems, sessionItems.find(item => item.active)?.id || "");
});
$("attachButton").addEventListener("click", event => {
  event.stopPropagation();
  $("attachMenu").classList.toggle("hidden");
});
$("attachFileButton").addEventListener("click", () => {
  $("attachMenu").classList.add("hidden");
  $("attachmentFileInput").click();
});
$("attachImageButton").addEventListener("click", () => {
  $("attachMenu").classList.add("hidden");
  $("attachmentImageInput").click();
});
$("attachmentFileInput").addEventListener("change", async event => {
  await attachFiles(event.target.files);
  event.target.value = "";
});
$("attachmentImageInput").addEventListener("change", async event => {
  await attachFiles(event.target.files);
  event.target.value = "";
});
$("textWebSearch").addEventListener("change", () => {
  if (settings) settings.web_search_enabled = $("textWebSearch").checked;
  updateComposerStatus();
});
document.addEventListener("click", event => {
  if (!event.target.closest("#attachMenu") && !event.target.closest("#attachButton")) {
    $("attachMenu").classList.add("hidden");
  }
  if (!event.target.closest("#thinkingControl")) {
    $("thinkingMenu").classList.add("hidden");
  }
});
setSidebarCollapsed(sidebarCollapsed);
$("chatDropZone").addEventListener("dragenter", event => {
  event.preventDefault();
  $("dropOverlay").classList.remove("hidden");
});
$("chatDropZone").addEventListener("dragover", event => {
  event.preventDefault();
  $("dropOverlay").classList.remove("hidden");
});
$("chatDropZone").addEventListener("dragleave", event => {
  if (!$("chatDropZone").contains(event.relatedTarget)) {
    $("dropOverlay").classList.add("hidden");
  }
});
$("chatDropZone").addEventListener("drop", async event => {
  event.preventDefault();
  $("dropOverlay").classList.add("hidden");
  await attachFiles(event.dataTransfer.files);
});
$("textPrompt").addEventListener("input", () => { autosizeTextPrompt(); updateComposerStatus(); });
$("textPrompt").addEventListener("keydown", event => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendTextPrompt();
  }
});
$("textPromptForm").addEventListener("submit", event => {
  event.preventDefault();
  sendTextPrompt();
});
$("dictateButton").addEventListener("click", () => {
  $("dictateButton").classList.add("active");
  backend("assistant.dictate");
});
$("thinkingTrigger").addEventListener("click", event => {
  event.stopPropagation();
  $("thinkingMenu").classList.toggle("hidden");
});
document.querySelectorAll("#thinkingMenu button").forEach(button => button.addEventListener("click", event => {
  event.stopPropagation();
  $("thinkingMenu").classList.add("hidden");
  setThinkingControl(button.dataset.value || "medium:standard");
}));
$("provider").addEventListener("change", renderModelField);
$("sttEngine").addEventListener("change", showSpeechFields);
$("activationMode").addEventListener("change", showSpeechFields);
$("echoGuard").addEventListener("change", showSpeechFields);
$("ttsEngine").addEventListener("change", renderTtsVoices);
$("voiceProfile").addEventListener("change", () => backend("settings.save", { apply_profile: $("voiceProfile").value }));
$("clearSteps").addEventListener("click", () => backend("conversation.clear"));
$("newSession").addEventListener("click", () => backend("conversation.new"));
$("listenButton").addEventListener("click", () => {
  listening = !listening;
  backend(listening ? "assistant.listen" : "assistant.stopListening");
});
$("stopButton").addEventListener("click", () => backend("assistant.interrupt"));
$("promptForm").addEventListener("submit", event => {
  event.preventDefault();
  const text = $("prompt").value.trim();
  if (!text) {
    return;
  }
  responseBuffer = "";
  responseStep = null;
  backend("assistant.send", { text });
  $("prompt").value = "";
});
$("saveSettings").addEventListener("click", () => {
  backend("settings.save", settingsPayload());
  $("apiKey").value = "";
  toggleSettings(false);
});
$("preloadModels").addEventListener("click", () => {
  openSetup();
  backend("models.preload");
});
$("prepareVoice").addEventListener("click", () => {
  openSetup();
  backend("models.preload");
});
$("setupRetry").addEventListener("click", () => backend("models.preload"));
$("testVoice").addEventListener("click", () => {
  openSetup();
  backend("tts.test", { text: "Привет. Озвучка ассистента работает." });
});
$("testVoiceInline").addEventListener("click", () => {
  openSetup();
  backend("tts.test", { text: "Привет. Озвучка ассистента работает." });
});
$("setupTestVoice").addEventListener("click", () => backend("tts.test", { text: "Привет. Озвучка ассистента работает." }));
$("setupClose").addEventListener("click", closeSetup);
$("errorClose").addEventListener("click", hideError);
$("visualizerClose").addEventListener("click", () => toggleVisualizer(false));
$("mediaToggle").addEventListener("click", () => controlInternalMusic(mediaPlaying ? "pause" : "play"));
$("mediaStop").addEventListener("click", () => controlInternalMusic("stop"));
$("mediaExpand").addEventListener("click", () => {
  const expanded = $("mediaDock").classList.toggle("expanded");
  $("mediaExpand").textContent = expanded ? "◱" : "□";
});
$("approvalReject").addEventListener("click", () => {
  if (activeApproval) {
    backend("agent.reject", { id: activeApproval });
  }
});
$("approvalAccept").addEventListener("click", () => {
  if (activeApproval) {
    backend("agent.approve", { id: activeApproval });
  }
});

setState("idle", "Запускаю backend");
native("app.ready");

updateComposerStatus();
autosizeTextPrompt();
