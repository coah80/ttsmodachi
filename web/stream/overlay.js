const key = location.pathname.split("/").filter(Boolean).pop();
const debug = new URLSearchParams(location.search).get("debug") === "1";
const state = document.querySelector("#state");
const last = document.querySelector("#last");
const unlock = document.querySelector("#unlock");
const queue = [];
let playing = false;
let unlocked = false;

if (debug) {
  document.body.classList.add("debug-on");
}

unlock.addEventListener("click", async () => {
  unlocked = true;
  document.body.classList.remove("needs-unlock");
  await drain();
});

const source = new EventSource(`/api/overlay/${key}/events`);

source.addEventListener("ready", event => {
  const payload = JSON.parse(event.data);
  state.textContent = `ready for ${payload.streamer || "stream"}`;
});

source.addEventListener("speech", event => {
  const payload = JSON.parse(event.data);
  queue.push(payload);
  drain();
});

source.onerror = () => {
  state.textContent = "reconnecting";
};

async function drain() {
  if (playing) {
    return;
  }
  playing = true;
  while (queue.length) {
    const event = queue.shift();
    state.textContent = "playing";
    last.textContent = `${event.user} · ${event.amount}`;
    const delayMs = Math.max(0, Number(event.speechDelayMs || 0));
    if (delayMs > 0) {
      state.textContent = "waiting";
      await wait(delayMs);
    }
    state.textContent = "playing";
    const ok = await play(event.audioUrl);
    if (!ok && !unlocked) {
      queue.unshift(event);
      document.body.classList.add("needs-unlock");
      break;
    }
  }
  if (!queue.length) {
    state.textContent = "ready";
  }
  playing = false;
}

function play(url) {
  return new Promise(resolve => {
    const audio = new Audio(`${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`);
    audio.volume = 1;
    let finished = false;
    const finish = value => {
      if (!finished) {
        finished = true;
        resolve(value);
      }
    };
    audio.onended = () => finish(true);
    audio.onerror = () => finish(true);
    audio.play().catch(() => finish(false));
  });
}

function wait(ms) {
  return new Promise(resolve => {
    setTimeout(resolve, ms);
  });
}
