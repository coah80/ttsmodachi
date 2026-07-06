const signedOut = document.querySelector("#signedOut");
const dashboard = document.querySelector("#dashboard");
const account = document.querySelector("#account");
const notConfigured = document.querySelector("#notConfigured");
const loginButton = document.querySelector("#loginButton");
const overlayUrl = document.querySelector("#overlayUrl");
const copyOverlay = document.querySelector("#copyOverlay");
const eventSubText = document.querySelector("#eventSubText");
const statusBadge = document.querySelector("#statusBadge");
const testButton = document.querySelector("#testButton");
const testResult = document.querySelector("#testResult");
const settingsForm = document.querySelector("#settingsForm");
const saveResult = document.querySelector("#saveResult");
const refreshButton = document.querySelector("#refreshButton");
const recentEvents = document.querySelector("#recentEvents");
const fields = {
  enabled: document.querySelector("#enabled"),
  minBits: document.querySelector("#minBits"),
  speechDelaySeconds: document.querySelector("#speechDelaySeconds"),
  includeUsername: document.querySelector("#includeUsername"),
  randomVoice: document.querySelector("#randomVoice"),
  voice: document.querySelector("#voice"),
  messageTemplate: document.querySelector("#messageTemplate"),
  noMessageTemplate: document.querySelector("#noMessageTemplate")
};

let current = null;

async function load() {
  const response = await fetch("/api/me");
  current = await response.json();
  render();
}

function render() {
  if (!current.authenticated) {
    signedOut.classList.remove("hidden");
    dashboard.classList.add("hidden");
    account.textContent = "not logged in";
    loginButton.href = current.loginUrl || "/login";
    notConfigured.classList.toggle("hidden", current.configured);
    return;
  }

  signedOut.classList.add("hidden");
  dashboard.classList.remove("hidden");
  account.textContent = `logged in as ${current.streamer.displayName}`;
  overlayUrl.value = current.overlayUrl;
  renderStatus(current.eventSub);
  renderVoices(current.voices, current.settings.voice);
  renderSettings(current.settings);
  renderEvents(current.recentEvents || []);
}

function renderStatus(status) {
  const connected = Boolean(status && status.connected);
  statusBadge.textContent = connected ? "listening" : "offline";
  statusBadge.className = `badge ${connected ? "ok" : "bad"}`;
  eventSubText.textContent = status?.detail || "not connected";
}

function renderVoices(voices, selected) {
  fields.voice.innerHTML = "";
  for (const voice of voices) {
    const option = document.createElement("option");
    option.value = voice;
    option.textContent = voice;
    option.selected = voice === selected;
    fields.voice.append(option);
  }
}

function renderSettings(settings) {
  fields.enabled.checked = settings.enabled;
  fields.minBits.value = settings.minBits;
  fields.speechDelaySeconds.value = ((settings.speechDelayMs || 0) / 1000).toFixed(1);
  fields.includeUsername.checked = settings.includeUsername;
  fields.randomVoice.checked = settings.randomVoice;
  fields.voice.value = settings.voice;
  fields.messageTemplate.value = settings.messageTemplate;
  fields.noMessageTemplate.value = settings.noMessageTemplate;
}

function renderEvents(events) {
  recentEvents.innerHTML = "";
  if (!events.length) {
    recentEvents.innerHTML = `<p class="muted">No bit messages rendered yet.</p>`;
    return;
  }
  for (const event of events) {
    const row = document.createElement("div");
    row.className = "event";
    const date = new Date(event.createdAt * 1000);
    row.innerHTML = `
      <strong>${escapeHtml(event.user)} · ${event.amount}</strong>
      <p>${escapeHtml(event.spokenText)}</p>
      <span class="muted">${date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}</span>
    `;
    recentEvents.append(row);
  }
}

copyOverlay.addEventListener("click", async () => {
  await navigator.clipboard.writeText(overlayUrl.value);
  copyOverlay.textContent = "Copied";
  setTimeout(() => {
    copyOverlay.textContent = "Copy URL";
  }, 1200);
});

testButton.addEventListener("click", async () => {
  testButton.disabled = true;
  testResult.textContent = "Rendering test audio...";
  try {
    const response = await fetch("/api/test", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user: "test viewer", amount: fields.minBits.value, message: "egg gave bits and said hi" })
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    testResult.textContent = "Test sent to the browser source.";
    await load();
  } catch (error) {
    testResult.textContent = `Test failed: ${error.message}`;
  } finally {
    testButton.disabled = false;
  }
});

settingsForm.addEventListener("submit", async event => {
  event.preventDefault();
  saveResult.textContent = "Saving...";
  const payload = {
    enabled: fields.enabled.checked,
    minBits: Number(fields.minBits.value || 1),
    speechDelayMs: Math.round(Number(fields.speechDelaySeconds.value || 0) * 1000),
    includeUsername: fields.includeUsername.checked,
    randomVoice: fields.randomVoice.checked,
    voice: fields.voice.value,
    messageTemplate: fields.messageTemplate.value,
    noMessageTemplate: fields.noMessageTemplate.value
  };
  try {
    const response = await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      throw new Error(await response.text());
    }
    saveResult.textContent = "Saved.";
    await load();
  } catch (error) {
    saveResult.textContent = `Save failed: ${error.message}`;
  }
});

refreshButton.addEventListener("click", load);

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, character => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;"
  })[character]);
}

load().catch(error => {
  signedOut.classList.remove("hidden");
  signedOut.innerHTML = `<div class="notice">Dashboard failed to load: ${escapeHtml(error.message)}</div>`;
});
