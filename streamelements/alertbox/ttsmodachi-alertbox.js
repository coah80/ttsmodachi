const TTSMODACHI_ENDPOINT = "%%TTSMODACHI_ENDPOINT%%";
const TTSMODACHI_TOKEN = "%%TTSMODACHI_TOKEN%%";
const TTSMODACHI_INSTALL_ID = "%%TTSMODACHI_INSTALL_ID%%";
const TTSMODACHI_CHANNEL = "%%TTSMODACHI_CHANNEL%%";
const TTSMODACHI_LISTENER = "%%TTSMODACHI_LISTENER%%";
const TTSMODACHI_PLAY_DELAY_MS = 1500;

ttsmodachiRunAlertBoxTts();

async function ttsmodachiRunAlertBoxTts() {
  const alert = ttsmodachiReadAlertData();
  if (!alert.user && !alert.message) {
    ttsmodachiResumeQueue();
    return;
  }
  const result = await ttsmodachiRender({
    installId: TTSMODACHI_INSTALL_ID,
    channel: {
      username: TTSMODACHI_CHANNEL,
      provider: "twitch"
    },
    listener: TTSMODACHI_LISTENER,
    event: {
      _ttsmodachiEventId: ttsmodachiEventId(alert),
      name: alert.user,
      amount: alert.amount,
      message: alert.message,
      currency: alert.currency || "bits"
    },
    token: TTSMODACHI_TOKEN
  });
  if (result && result.audioUrl) {
    await ttsmodachiWait(TTSMODACHI_PLAY_DELAY_MS);
    await ttsmodachiPlay(result.audioUrl);
  }
  ttsmodachiResumeQueue();
}

function ttsmodachiReadAlertData() {
  const root = document.querySelector("[data-ttsmodachi-alert]");
  const text = name => {
    const node = root ? root.querySelector(`[data-ttsmodachi-${name}]`) : null;
    return node ? node.textContent.trim() : "";
  };
  return {
    user: text("name"),
    amount: ttsmodachiAmount(text("amount")),
    message: text("message"),
    currency: text("currency"),
    duration: ttsmodachiAmount(text("duration"))
  };
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
    return null;
  }
}

function ttsmodachiPlay(url) {
  return new Promise(resolve => {
    const audio = new Audio(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`);
    audio.volume = 1;
    audio.playsInline = true;
    audio.onended = resolve;
    audio.onerror = resolve;
    audio.play().catch(resolve);
  });
}

function ttsmodachiResumeQueue() {
  if (window.SE_API && typeof window.SE_API.resumeQueue === "function") {
    window.SE_API.resumeQueue();
  }
}

function ttsmodachiWait(ms) {
  return new Promise(resolve => setTimeout(resolve, ms));
}

function ttsmodachiAmount(value) {
  const number = Number(String(value || "").replace(/[^\d.]/g, ""));
  return Number.isFinite(number) ? number : 0;
}

function ttsmodachiEventId(alert) {
  const randomPart = window.crypto && typeof window.crypto.randomUUID === "function"
    ? window.crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `${TTSMODACHI_INSTALL_ID || "default"}:${TTSMODACHI_LISTENER}:${alert.user}:${alert.amount}:${randomPart}`;
}
