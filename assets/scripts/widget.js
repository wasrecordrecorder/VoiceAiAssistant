const $ = id => document.getElementById(id);
let socket = null;

const labels = {
  idle: "Готов",
  monitoring: "В фоне",
  armed: "Слушаю",
  ptt: "Рация",
  listening: "Слушаю",
  speech_detected: "Слышу",
  transcribing: "Пишу",
  thinking: "Думаю",
  speaking: "Говорю",
  follow_up: "Жду",
  interrupted: "Пауза",
  error: "Ошибка"
};

const kinds = {
  idle: "idle",
  monitoring: "idle",
  armed: "listen",
  ptt: "listen",
  listening: "listen",
  speech_detected: "listen",
  transcribing: "work",
  thinking: "work",
  speaking: "speak",
  follow_up: "listen",
  interrupted: "idle",
  error: "error"
};

function native(command, payload = {}) {
  window.chrome.webview.postMessage(JSON.stringify({ command, payload }));
}

function compact(text, fallback) {
  const value = String(text || "").replace(/\s+/g, " ").trim();
  return value ? (value.length > 62 ? `${value.slice(0, 59)}…` : value) : fallback;
}

function setState(state, detail = "") {
  const kind = kinds[state] || "idle";
  const widget = $("dragRegion");
  widget.className = `widget ${kind}`;
  $("widgetState").textContent = labels[state] || state || "Готов";
  if (detail) {
    $("widgetStep").textContent = compact(detail, "Ожидаю команду");
  }
}

function setStep(value) {
  $("widgetStep").textContent = compact(value, "Ожидаю команду");
}

function connect(info) {
  if (!info.online) {
    setState("error", info.error || "Backend недоступен");
    return;
  }
  socket = new WebSocket(`${info.url}?token=${encodeURIComponent(info.token)}`);
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    const payload = message.payload || {};
    if (message.event === "assistant.state") setState(payload.state);
    else if (message.event.startsWith("assistant.")) setState(message.event.substring(10), payload.message || "");
    else if (message.event === "step.add") setStep(payload.text);
    else if (message.event === "agent.tool_started") setStep(`Tool: ${payload.name || ""}`);
    else if (message.event === "response.delta") setState("thinking", "Пишу ответ…");
    else if (message.event === "response.final") setState("idle", "Ответ готов");
  });
  socket.addEventListener("close", () => setState("error", "Связь потеряна"));
}

window.chrome.webview.addEventListener("message", event => {
  if (event.data.event === "app.info") connect(event.data.payload.backend);
});

$("openButton").addEventListener("click", () => native("window.restoreMain"));
$("dragRegion").addEventListener("pointerdown", event => {
  if (!event.target.closest("button")) native("window.drag");
});
native("app.ready");
