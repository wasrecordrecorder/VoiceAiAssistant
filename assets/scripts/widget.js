const $ = id => document.getElementById(id);
let socket = null;
const labels = {
  idle: "Готов",
  monitoring: "В фоне",
  armed: "Слушаю",
  ptt: "Рация активна",
  listening: "Слушаю",
  speech_detected: "Слышу вас",
  transcribing: "Распознаю",
  thinking: "Думаю",
  speaking: "Говорю",
  follow_up: "Жду продолжение",
  error: "Ошибка"
};

function native(command, payload = {}) {
  window.chrome.webview.postMessage(JSON.stringify({ command, payload }));
}

function setState(state, detail = "") {
  $("widgetState").textContent = labels[state] || state || "Готов";
  if (detail) $("widgetStep").textContent = detail;
  $("indicator").classList.toggle("active", ["armed", "ptt", "listening", "speech_detected", "transcribing", "thinking", "speaking", "follow_up"].includes(state));
  $("indicator").classList.toggle("error", state === "error");
}

function connect(info) {
  if (!info.online) {
    setState("error", "Backend недоступен");
    return;
  }
  socket = new WebSocket(`${info.url}?token=${encodeURIComponent(info.token)}`);
  socket.addEventListener("message", event => {
    const message = JSON.parse(event.data);
    const { payload } = message;
    if (message.event === "assistant.state") setState(payload.state);
    else if (message.event.startsWith("assistant.")) setState(message.event.substring(10), payload.message || "");
    else if (message.event === "step.add") $("widgetStep").textContent = payload.text || "";
    else if (message.event === "agent.tool_started") $("widgetStep").textContent = `Инструмент: ${payload.name}`;
    else if (message.event === "response.final") $("widgetStep").textContent = "Ответ готов";
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
