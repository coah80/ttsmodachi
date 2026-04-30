from __future__ import annotations


PANEL_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TTSModachi Voice Panel</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #101114;
      --panel: #181a20;
      --panel-2: #20232b;
      --border: #30343e;
      --text: #f3f4f6;
      --muted: #a2a9b4;
      --accent: #31c48d;
      --accent-2: #4da3ff;
      --warn: #f6ad55;
      --danger: #fb7185;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }
    button, input, select, textarea {
      font: inherit;
    }
    button {
      border: 1px solid var(--border);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 6px;
      min-height: 36px;
      padding: 0 12px;
      cursor: pointer;
    }
    button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #06130e;
      font-weight: 700;
    }
    button:disabled {
      opacity: .55;
      cursor: wait;
    }
    main {
      width: min(1180px, calc(100vw - 32px));
      margin: 0 auto;
      padding: 24px 0 36px;
    }
    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      margin-bottom: 18px;
    }
    .header-side {
      display: flex;
      align-items: center;
      justify-content: flex-end;
      gap: 10px;
      flex-wrap: wrap;
    }
    h1 {
      margin: 0;
      font-size: 24px;
      line-height: 1.1;
      letter-spacing: 0;
    }
    .status {
      min-height: 32px;
      display: inline-flex;
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 999px;
      padding: 0 12px;
      color: var(--muted);
      white-space: nowrap;
    }
    .identity {
      display: flex;
      align-items: center;
      gap: 10px;
      min-height: 44px;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 6px 10px 6px 6px;
      background: var(--panel);
    }
    .identity[hidden] {
      display: none;
    }
    .identity img {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      background: #0f1116;
    }
    .identity span {
      display: block;
      color: var(--muted);
      font-size: 11px;
      line-height: 1.2;
    }
    .identity strong {
      display: block;
      max-width: 220px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      font-size: 14px;
      line-height: 1.2;
    }
    .layout {
      display: grid;
      grid-template-columns: minmax(0, 1fr) 360px;
      gap: 16px;
      align-items: start;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
    }
    section + section { margin-top: 16px; }
    h2 {
      margin: 0 0 14px;
      font-size: 15px;
      line-height: 1.2;
      letter-spacing: 0;
    }
    .message {
      width: 100%;
      min-height: 88px;
      resize: vertical;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: #0f1116;
      color: var(--text);
      padding: 12px;
    }
    .controls {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
      margin-top: 14px;
    }
    .control {
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      background: #13161c;
    }
    .control label {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 13px;
      margin-bottom: 8px;
    }
    .control output {
      color: var(--text);
      min-width: 34px;
      text-align: right;
    }
    input[type="range"] {
      width: 100%;
      accent-color: var(--accent);
    }
    select, input[type="text"] {
      width: 100%;
      min-height: 36px;
      border-radius: 6px;
      border: 1px solid var(--border);
      background: #0f1116;
      color: var(--text);
      padding: 0 10px;
    }
    .button-row {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 14px;
    }
    .audio {
      width: 100%;
      margin-top: 14px;
    }
    .preset-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 8px;
    }
    .preset-grid button {
      justify-content: start;
      text-align: left;
      min-height: 42px;
    }
    .command {
      width: 100%;
      min-height: 92px;
      border: 1px solid var(--border);
      border-radius: 6px;
      background: #0f1116;
      color: var(--text);
      padding: 10px;
      resize: vertical;
    }
    .pack-head {
      display: grid;
      grid-template-columns: 1fr 112px;
      gap: 10px;
      align-items: end;
    }
    .samples {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 14px;
    }
    .sample {
      background: #12151b;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      min-width: 0;
    }
    .sample strong {
      display: block;
      margin-bottom: 6px;
      font-size: 13px;
      line-height: 1.2;
      word-break: break-word;
    }
    .sample audio { width: 100%; height: 34px; }
    .sample .meta {
      color: var(--muted);
      font-size: 12px;
      margin-top: 6px;
      line-height: 1.35;
    }
    .meter {
      height: 8px;
      background: #0e1014;
      border: 1px solid var(--border);
      border-radius: 999px;
      overflow: hidden;
      margin-top: 14px;
    }
    .meter span {
      display: block;
      height: 100%;
      width: 0%;
      background: var(--accent-2);
      transition: width .18s ease;
    }
    @media (max-width: 860px) {
      main { width: min(100vw - 20px, 720px); padding-top: 14px; }
      header { align-items: flex-start; flex-direction: column; }
      .header-side { justify-content: flex-start; }
      .layout, .controls, .samples, .preset-grid { grid-template-columns: 1fr; }
      .pack-head { grid-template-columns: 1fr; }
      .status { white-space: normal; }
    }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>TTSModachi Voice Panel</h1>
      <div class="header-side">
        <div class="identity" id="identity" hidden>
          <img id="identityAvatar" alt="">
          <div>
            <span>Customizing for</span>
            <strong id="identityName"></strong>
          </div>
        </div>
        <div class="status" id="status">ready</div>
      </div>
    </header>

    <div class="layout">
      <div>
        <section>
          <h2>Test Message</h2>
          <textarea class="message" id="message">This is a test message for the discord bot.</textarea>
          <div class="controls" id="controls"></div>
          <div class="button-row">
            <button class="primary" id="play">Play Current</button>
            <button id="save" disabled>Save To Discord</button>
            <button id="reset">Reset</button>
          </div>
          <audio class="audio" id="audio" controls></audio>
        </section>

        <section>
          <div class="pack-head">
            <div>
              <h2>Safe Sample Pack</h2>
              <select id="packMode">
                <option value="builtins">Built-ins only</option>
                <option value="matrix">Curated matrix</option>
                <option value="both">Built-ins + matrix</option>
              </select>
            </div>
            <div>
              <h2>Limit</h2>
              <select id="packLimit">
                <option>12</option>
                <option selected>24</option>
                <option>36</option>
                <option>48</option>
              </select>
            </div>
          </div>
          <div class="button-row">
            <button id="pack">Generate Pack</button>
            <button id="clearPack">Clear</button>
          </div>
          <div class="meter"><span id="progress"></span></div>
          <div class="samples" id="samples"></div>
        </section>
      </div>

      <aside>
        <section>
          <h2>Presets</h2>
          <div class="preset-grid" id="presets"></div>
        </section>
        <section>
          <h2>Discord Voice</h2>
          <textarea class="command" id="command" readonly></textarea>
        </section>
      </aside>
    </div>
  </main>

  <script>
    const state = {
      token: new URLSearchParams(location.search).get("token") || sessionStorage.getItem("ttsmodachiToken") || sessionStorage.getItem("talkmodachiToken") || "",
      builtins: {},
      session: null,
      values: {
        pitch: 50,
        speed: 50,
        quality: 50,
        tone: 50,
        accent: 50,
        intonation: 1,
        lang: "useng",
        volume: 165
      }
    };
    if (state.token) sessionStorage.setItem("ttsmodachiToken", state.token);

    const ranges = [
      ["pitch", "Pitch", 0, 100, 1],
      ["speed", "Speed", 0, 100, 1],
      ["quality", "Quality", 0, 100, 1],
      ["tone", "Tone", 0, 100, 1],
      ["accent", "Accent", 0, 100, 1],
      ["intonation", "Intonation", 1, 4, 1],
      ["volume", "Volume", 25, 300, 1]
    ];

    const $ = (id) => document.getElementById(id);

    function setStatus(text) {
      $("status").textContent = text;
    }

    function headers() {
      return state.token ? {"Content-Type": "application/json", "X-Panel-Token": state.token} : {"Content-Type": "application/json"};
    }

    function voice() {
      return {...state.values};
    }

    function renderControls() {
      const controls = $("controls");
      controls.innerHTML = "";
      for (const [key, label, min, max, step] of ranges) {
        const wrap = document.createElement("div");
        wrap.className = "control";
        wrap.innerHTML = `<label for="${key}"><span>${label}</span><output id="${key}Out">${state.values[key]}</output></label><input id="${key}" type="range" min="${min}" max="${max}" step="${step}" value="${state.values[key]}">`;
        controls.appendChild(wrap);
        $(key).addEventListener("input", (event) => {
          state.values[key] = Number(event.target.value);
          $(`${key}Out`).textContent = state.values[key];
          updateCommand();
        });
      }

      const langWrap = document.createElement("div");
      langWrap.className = "control";
      langWrap.innerHTML = `<label for="lang"><span>Language</span><output id="langOut">${state.values.lang}</output></label><select id="lang"><option value="useng">useng</option><option value="eueng">eueng</option><option value="fr">fr</option><option value="de">de</option><option value="it">it</option><option value="es">es</option><option value="jp">jp</option><option value="kr">kr</option></select>`;
      controls.appendChild(langWrap);
      $("lang").value = state.values.lang;
      $("lang").addEventListener("change", (event) => {
        state.values.lang = event.target.value;
        $("langOut").textContent = state.values.lang;
        updateCommand();
      });
    }

    function updateControlValues() {
      for (const [key] of ranges) {
        $(key).value = state.values[key];
        $(`${key}Out`).textContent = state.values[key];
      }
      $("lang").value = state.values.lang;
      $("langOut").textContent = state.values.lang;
      updateCommand();
    }

    function updateCommand() {
      const v = voice();
      const status = state.session
        ? `Ready to save for Discord user ${state.session.userId}.`
        : "Open this panel from /voice in Discord to save directly.";
      $("command").value = `${status}\n\npitch:${v.pitch} speed:${v.speed} quality:${v.quality} tone:${v.tone} accent:${v.accent} intonation:${v.intonation} lang:${v.lang} volume:${v.volume}`;
    }

    function applyVoice(params) {
      state.values = {...state.values, ...params};
      updateControlValues();
    }

    function renderIdentity() {
      if (!state.session) {
        $("identity").hidden = true;
        return;
      }
      $("identityName").textContent = state.session.displayName || `Discord user ${state.session.userId}`;
      if (state.session.avatarUrl) {
        $("identityAvatar").src = state.session.avatarUrl;
        $("identityAvatar").hidden = false;
      } else {
        $("identityAvatar").hidden = true;
      }
      $("identity").hidden = false;
    }

    async function renderVoice(params, label) {
      const started = performance.now();
      const response = await fetch("/render", {
        method: "POST",
        headers: headers(),
        body: JSON.stringify({text: $("message").value.trim() || "This is a test message for the discord bot.", voice: params, mode: "text"})
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const blob = await response.blob();
      return {
        label,
        url: URL.createObjectURL(blob),
        cache: response.headers.get("x-cache") || "",
        elapsed: Math.round(performance.now() - started)
      };
    }

    async function playCurrent() {
      $("play").disabled = true;
      setStatus("rendering");
      try {
        const result = await renderVoice(voice(), "current");
        $("audio").src = result.url;
        await $("audio").play().catch(() => {});
        setStatus(`${result.cache || "rendered"} in ${result.elapsed}ms`);
      } catch (error) {
        setStatus("failed");
        alert(String(error.message || error));
      } finally {
        $("play").disabled = false;
      }
    }

    async function saveCurrent() {
      if (!state.session) {
        setStatus("open from /voice");
        alert("Use /voice in Discord, then open the private link it gives you.");
        return;
      }
      $("save").disabled = true;
      setStatus("saving");
      try {
        const response = await fetch("/api/voice/save", {
          method: "POST",
          headers: headers(),
          body: JSON.stringify({voice: voice()})
        });
        if (!response.ok) {
          throw new Error(await response.text());
        }
        const result = await response.json();
        setStatus(`saved ${result.voiceId}`);
      } catch (error) {
        setStatus("save failed");
        alert(String(error.message || error));
      } finally {
        $("save").disabled = false;
      }
    }

    function renderPresets() {
      const presets = $("presets");
      presets.innerHTML = "";
      for (const [name, params] of Object.entries(state.builtins)) {
        const button = document.createElement("button");
        button.textContent = name;
        button.addEventListener("click", () => applyVoice(params));
        presets.appendChild(button);
      }
    }

    function matrixVoices() {
      const samples = [];
      const pitches = [25, 50, 75];
      const speeds = [35, 50, 70];
      const tones = [25, 50, 75];
      for (const pitch of pitches) {
        for (const speed of speeds) {
          for (const tone of tones) {
            samples.push({
              label: `p${pitch} s${speed} t${tone}`,
              voice: {...voice(), pitch, speed, tone}
            });
          }
        }
      }
      return samples;
    }

    function packVoices() {
      const mode = $("packMode").value;
      const items = [];
      if (mode === "builtins" || mode === "both") {
        for (const [label, params] of Object.entries(state.builtins)) {
          items.push({label, voice: {...params, volume: state.values.volume}});
        }
      }
      if (mode === "matrix" || mode === "both") {
        items.push(...matrixVoices());
      }
      return items.slice(0, Number($("packLimit").value));
    }

    function addSample(result, params) {
      const el = document.createElement("div");
      el.className = "sample";
      el.innerHTML = `<strong>${result.label}</strong><audio controls src="${result.url}"></audio><div class="meta">p${params.pitch} s${params.speed} q${params.quality} t${params.tone} a${params.accent} i${params.intonation} v${params.volume} ${result.cache} ${result.elapsed}ms</div>`;
      $("samples").appendChild(el);
    }

    async function generatePack() {
      const items = packVoices();
      $("pack").disabled = true;
      $("progress").style.width = "0%";
      setStatus(`0/${items.length}`);
      try {
        for (let index = 0; index < items.length; index += 1) {
          const item = items[index];
          const result = await renderVoice(item.voice, item.label);
          addSample(result, item.voice);
          const pct = Math.round(((index + 1) / items.length) * 100);
          $("progress").style.width = `${pct}%`;
          setStatus(`${index + 1}/${items.length}`);
        }
      } catch (error) {
        setStatus("failed");
        alert(String(error.message || error));
      } finally {
        $("pack").disabled = false;
      }
    }

    async function loadConfig() {
      renderControls();
      updateCommand();
      const response = await fetch("/api/config", {headers: state.token ? {"X-Panel-Token": state.token} : {}});
      if (!response.ok) {
        setStatus("token required");
        return;
      }
      const config = await response.json();
      state.builtins = config.builtins;
      renderPresets();
      let finalStatus = "ready";
      if (state.token) {
        const sessionResponse = await fetch("/api/session", {headers: {"X-Panel-Token": state.token}});
        if (sessionResponse.ok) {
          state.session = await sessionResponse.json();
          applyVoice(state.session.voice);
          renderIdentity();
          finalStatus = "linked";
        } else {
          finalStatus = "invalid panel link";
        }
      }
      $("save").disabled = !state.session;
      setStatus(finalStatus);
    }

    $("play").addEventListener("click", playCurrent);
    $("save").addEventListener("click", saveCurrent);
    $("pack").addEventListener("click", generatePack);
    $("clearPack").addEventListener("click", () => {
      $("samples").innerHTML = "";
      $("progress").style.width = "0%";
      setStatus("ready");
    });
    $("reset").addEventListener("click", () => {
      applyVoice({pitch: 50, speed: 50, quality: 50, tone: 50, accent: 50, intonation: 1, lang: "useng", volume: 165});
      setStatus("ready");
    });

    loadConfig();
  </script>
</body>
</html>
"""
