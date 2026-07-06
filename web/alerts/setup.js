const statusText = document.querySelector("#statusText");
const refreshButton = document.querySelector("#refreshButton");
const copyAlertHtmlButton = document.querySelector("#copyAlertHtmlButton");
const copyAlertJsButton = document.querySelector("#copyAlertJsButton");
const downloadAlertBoxButton = document.querySelector("#downloadAlertBoxButton");
const copyWidgetButton = document.querySelector("#copyWidgetButton");
const downloadWidgetButton = document.querySelector("#downloadWidgetButton");
const alertBoxHtml = document.querySelector("#alertBoxHtml");
const alertBoxJs = document.querySelector("#alertBoxJs");
const widgetCode = document.querySelector("#widgetCode");
const testForm = document.querySelector("#testForm");
const rendererUrl = document.querySelector("#rendererUrl");
const endpointUrl = document.querySelector("#endpointUrl");
const renderedCount = document.querySelector("#renderedCount");
const lastEvent = document.querySelector("#lastEvent");

let currentAlertBoxHtml = "";
let currentAlertBoxJs = "";
let currentWidgetCode = "";
let currentToken = "";

async function loadSetup() {
  statusText.classList.remove("error");
  statusText.textContent = "Loading...";
  const [statusResponse, alertBoxResponse, widgetResponse] = await Promise.all([
    fetch("/api/alerts/status"),
    fetch("/api/alerts/alertbox-code"),
    fetch("/api/alerts/widget-code")
  ]);
  const status = await statusResponse.json();
  const alertBox = await alertBoxResponse.json();
  const widget = await widgetResponse.json();
  currentAlertBoxHtml = alertBox.html;
  currentAlertBoxJs = alertBox.js;
  currentWidgetCode = widget.code;
  currentToken = widgetToken(currentAlertBoxJs || currentWidgetCode);
  alertBoxHtml.value = currentAlertBoxHtml;
  alertBoxJs.value = currentAlertBoxJs;
  widgetCode.value = currentWidgetCode;
  rendererUrl.textContent = status.rendererUrl;
  endpointUrl.textContent = status.endpointUrl;
  renderedCount.textContent = String(status.stats.rendered);
  lastEvent.textContent = status.lastEvent ? `${status.lastEvent.user} - ${status.lastEvent.amount} bits` : "-";
  statusText.textContent = status.lastError || `Ready - install ${status.installId}`;
  if (status.lastError) {
    statusText.classList.add("error");
  }
}

copyAlertHtmlButton.addEventListener("click", () => copyText(currentAlertBoxHtml || alertBoxHtml.value, copyAlertHtmlButton, "Copy HTML"));
copyAlertJsButton.addEventListener("click", () => copyText(currentAlertBoxJs || alertBoxJs.value, copyAlertJsButton, "Copy JS"));
copyWidgetButton.addEventListener("click", () => copyText(currentWidgetCode || widgetCode.value, copyWidgetButton, "Copy widget JS"));

downloadAlertBoxButton.addEventListener("click", () => {
  downloadText("ttsmodachi-alertbox-html.txt", currentAlertBoxHtml || alertBoxHtml.value, "text/html");
  downloadText("ttsmodachi-alertbox-js.txt", currentAlertBoxJs || alertBoxJs.value, "text/javascript");
});

downloadWidgetButton.addEventListener("click", () => {
  downloadText("ttsmodachi-streamelements-widget.js", currentWidgetCode || widgetCode.value, "text/javascript");
});

refreshButton.addEventListener("click", () => {
  loadSetup().catch(showError);
});

testForm.addEventListener("submit", async event => {
  event.preventDefault();
  const response = await fetch("/api/alerts/test", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      user: document.querySelector("#testUser").value,
      amount: Number(document.querySelector("#testAmount").value || 100),
      message: document.querySelector("#testMessage").value,
      token: currentToken
    })
  });
  const result = await response.json();
  if (result.audioUrl) {
    await playAudio(result.audioUrl);
  }
  await loadSetup();
});

async function copyText(text, button, label) {
  await navigator.clipboard.writeText(text);
  button.textContent = "Copied";
  setTimeout(() => {
    button.textContent = label;
  }, 1200);
}

function downloadText(filename, text, type) {
  const blob = new Blob([text], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function playAudio(url) {
  return new Promise(resolve => {
    const audio = new Audio(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`);
    audio.onended = resolve;
    audio.onerror = resolve;
    audio.play().catch(resolve);
  });
}

function showError(error) {
  statusText.textContent = error.message;
  statusText.classList.add("error");
}

function widgetToken(code) {
  const match = code.match(/const TTSMODACHI_TOKEN = "([^"]*)"/);
  return match ? match[1] : "";
}

loadSetup().catch(showError);
