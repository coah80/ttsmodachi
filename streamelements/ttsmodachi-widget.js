const TTSMODACHI_ENDPOINT = "%%TTSMODACHI_ENDPOINT%%";
const TTSMODACHI_TOKEN = "%%TTSMODACHI_TOKEN%%";
const TTSMODACHI_INSTALL_ID = "%%TTSMODACHI_INSTALL_ID%%";
const TTSMODACHI_ALLOWED_LISTENERS = new Set(["cheer-latest", "cheerPurchase-latest", "cheer", "cheerPurchase", "tip-latest", "tip"]);
const TTSMODACHI_MIN_AMOUNT = 1;
const TTSMODACHI_PLAY_DELAY_MS = 1500;

const ttsmodachiQueue = [];
let ttsmodachiPlaying = false;
let ttsmodachiSequence = 0;
let ttsmodachiChannel = { username: "", provider: "", id: "" };

window.addEventListener("onWidgetLoad", event => {
  const detail = event.detail || {};
  const channel = detail.channel || {};
  ttsmodachiChannel = {
    username: ttsmodachiText(channel.username || channel.name || channel.login),
    provider: ttsmodachiText(channel.provider || channel.platform),
    id: ttsmodachiText(channel.id || channel._id || channel.channelId)
  };
});

window.addEventListener("onEventReceived", event => {
  const detail = event.detail || {};
  const listener = detail.listener || "";
  const alert = detail.event || {};
  const amount = Number(alert.amount || alert.bits || 0);
  if (!TTSMODACHI_ALLOWED_LISTENERS.has(listener) || amount < TTSMODACHI_MIN_AMOUNT) {
    return;
  }
  const eventId = ttsmodachiEventId(listener, alert);
  const payload = {
    installId: TTSMODACHI_INSTALL_ID,
    channel: ttsmodachiChannel,
    listener,
    event: { ...alert, _ttsmodachiEventId: eventId },
    recents: detail.recents || null,
    token: TTSMODACHI_TOKEN
  };
  ttsmodachiQueue.push(ttsmodachiRender(payload));
  ttsmodachiDrainQueue();
});

async function ttsmodachiDrainQueue() {
  if (ttsmodachiPlaying) {
    return;
  }
  ttsmodachiPlaying = true;
  while (ttsmodachiQueue.length) {
    const result = await ttsmodachiQueue.shift();
    if (result && result.audioUrl) {
      if (TTSMODACHI_PLAY_DELAY_MS > 0) {
        await ttsmodachiWait(TTSMODACHI_PLAY_DELAY_MS);
      }
      await ttsmodachiPlay(result.audioUrl);
    }
  }
  ttsmodachiPlaying = false;
}

async function ttsmodachiRender(payload) {
  try {
    const response = await fetch(TTSMODACHI_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!response.ok) {
      return null;
    }
    const result = await response.json();
    return result.rendered === false ? null : result;
  } catch (error) {
    await ttsmodachiWait(750);
    return null;
  }
}

function ttsmodachiPlay(url) {
  return new Promise(resolve => {
    const audio = new Audio(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`);
    audio.volume = 1;
    audio.onended = resolve;
    audio.onerror = resolve;
    audio.play().catch(resolve);
  });
}

function ttsmodachiWait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function ttsmodachiEventId(listener, alert) {
  const existing = alert.activityId || alert._id || alert.id || alert.transactionId;
  if (existing) {
    return String(existing);
  }
  ttsmodachiSequence += 1;
  return `${TTSMODACHI_INSTALL_ID || "default"}:${listener}:${Date.now()}:${ttsmodachiSequence}`;
}

function ttsmodachiText(value) {
  return value === undefined || value === null ? "" : String(value);
}
