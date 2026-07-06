"""Standalone, no-login voice API tester page served at /tester.

Lets anyone POST text + voice params to /render and hear the result, and shows
a copyable curl command. Mirrors the game-faithful control layout of the panel.
"""

from __future__ import annotations

TESTER_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TTSmodachi Voice API Tester</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #0f1116;
      --panel: #181a20;
      --panel-2: #20232b;
      --border: #30343e;
      --text: #f3f4f6;
      --muted: #a2a9b4;
      --accent: #3a8cfe;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); min-height: 100vh; }
    main { width: min(920px, calc(100vw - 32px)); margin: 0 auto; padding: 24px 0 40px; }
    h1 { font-size: 22px; margin: 0 0 4px; }
    .sub { color: var(--muted); margin: 0 0 18px; font-size: 14px; }
    section { background: var(--panel); border: 1px solid var(--border); border-radius: 8px; padding: 16px; }
    section + section { margin-top: 16px; }
    h2 { font-size: 14px; margin: 0 0 12px; }
    label { display: block; color: var(--muted); font-size: 13px; margin-bottom: 6px; }
    textarea { width: 100%; min-height: 78px; resize: vertical; border-radius: 6px; border: 1px solid var(--border); background: #0f1116; color: var(--text); padding: 10px; }
    .controls { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 8px; }
    .control { border: 1px solid var(--border); border-radius: 8px; padding: 10px; background: #13161c; }
    .control .row { display: flex; justify-content: space-between; color: var(--muted); font-size: 13px; margin-bottom: 8px; }
    .control output { color: var(--text); }
    .slider-wrap { position: relative; padding-top: 4px; }
    .slider-wrap.centered::before { content: ""; position: absolute; left: 50%; top: 0; transform: translateX(-50%); width: 2px; height: 7px; background: var(--muted); opacity: .55; border-radius: 1px; }
    input[type="range"] { width: 100%; accent-color: var(--accent); }
    .wide { grid-column: 1 / -1; }
    .intona { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 6px; }
    button { border: 1px solid var(--border); background: var(--panel-2); color: var(--text); border-radius: 6px; min-height: 40px; padding: 0 12px; cursor: pointer; }
    button.primary { background: var(--accent); border-color: var(--accent); color: #fff; font-weight: 700; }
    .intona button { display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 1px; line-height: 1.1; }
    .intona button .n { font-size: 10px; color: var(--muted); }
    .intona button.active { background: var(--accent); border-color: var(--accent); color: #fff; }
    .intona button.active .n { color: rgba(255,255,255,.8); }
    .button-row { display: flex; gap: 8px; margin-top: 14px; flex-wrap: wrap; align-items: center; }
    audio { width: 100%; margin-top: 12px; }
    .meta { color: var(--muted); font-size: 12px; margin-top: 8px; min-height: 16px; }
    pre { background: #0f1116; border: 1px solid var(--border); border-radius: 6px; padding: 12px; overflow-x: auto; font-size: 12px; margin: 0; white-space: pre; }
    .curl-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
    @media (max-width: 560px) { .controls { grid-template-columns: 1fr; } }
  </style>
</head>
<body>
  <main>
    <h1>TTSmodachi Voice API Tester</h1>
    <p class="sub">POST text and voice params to <code>/render</code> and hear the Tomodachi voice. No login needed.</p>

    <section>
      <label for="text">Text</label>
      <textarea id="text">Hello! This is the TTSmodachi voice API.</textarea>
      <div class="controls" id="controls"></div>
      <div class="button-row">
        <button class="primary" id="render">Render &amp; Play</button>
        <button id="reset">Reset</button>
        <span class="meta" id="meta"></span>
      </div>
      <audio id="audio" controls></audio>
    </section>

    <section>
      <div class="curl-head"><h2>curl</h2><button id="copyCurl">Copy</button></div>
      <pre id="curl"></pre>
    </section>
  </main>

  <script>
    const sliders = [
      ["pitch", "Pitch", 0, 100, true],
      ["speed", "Speed", 0, 100, true],
      ["quality", "Quality", 0, 100, true],
      ["tone", "Tone", 0, 100, true],
      ["accent", "Accent", 0, 100, true],
      ["volume", "Volume", 25, 300, false]
    ];
    const intonationModes = [[1, "Flat"], [2, "Gentle"], [3, "Lively"], [4, "Questioning"]];
    const DEFAULTS = { engine: "tl3ds", pitch: 50, speed: 50, quality: 50, tone: 50, accent: 50, intonation: 1, lang: "useng", volume: 200 };
    const state = { ...DEFAULTS };
    const $ = (id) => document.getElementById(id);

    function renderControls() {
      const box = $("controls");
      box.innerHTML = "";
      for (const [key, label, min, max, centered] of sliders) {
        const el = document.createElement("div");
        el.className = "control";
        el.innerHTML = `<div class="row"><span>${label}</span><output id="${key}Out">${state[key]}</output></div><div class="slider-wrap ${centered ? "centered" : ""}"><input id="${key}" type="range" min="${min}" max="${max}" value="${state[key]}"></div>`;
        box.appendChild(el);
        $(key).addEventListener("input", (e) => { state[key] = Number(e.target.value); $(`${key}Out`).textContent = state[key]; updateCurl(); });
      }
      const intona = document.createElement("div");
      intona.className = "control wide";
      const btns = intonationModes.map(([v, name]) => `<button data-i="${v}"><span>${name}</span><span class="n">${v}</span></button>`).join("");
      intona.innerHTML = `<div class="row"><span>Intonation</span><output id="intonaOut">${state.intonation}</output></div><div class="intona" id="intona">${btns}</div>`;
      box.appendChild(intona);
      intona.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => { state.intonation = Number(b.dataset.i); $("intonaOut").textContent = state.intonation; highlight(); updateCurl(); }));
      highlight();
    }
    function highlight() {
      document.querySelectorAll("#intona button").forEach((b) => b.classList.toggle("active", Number(b.dataset.i) === state.intonation));
    }
    function payload() {
      const { engine, pitch, speed, quality, tone, accent, intonation, lang, volume } = state;
      return { text: $("text").value, voice: { engine, pitch, speed, quality, tone, accent, intonation, lang, volume }, mode: "text" };
    }
    function updateCurl() {
      const body = JSON.stringify(payload());
      $("curl").textContent = `curl -X POST ${location.origin}/render \\\\\n  -H 'Content-Type: application/json' \\\\\n  -d '${body.replace(/'/g, "'\\\\''")}' \\\\\n  --output speech.wav`;
    }
    async function doRender() {
      const btn = $("render"); btn.disabled = true; $("meta").textContent = "rendering...";
      const t0 = performance.now();
      try {
        const res = await fetch("/render", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload()) });
        if (!res.ok) { let d = ""; try { d = (await res.json()).detail || ""; } catch (e) {} $("meta").textContent = `HTTP ${res.status} ${d}`; return; }
        const blob = await res.blob();
        $("audio").src = URL.createObjectURL(blob);
        $("audio").play().catch(() => {});
        const ms = Math.round(performance.now() - t0);
        $("meta").textContent = `ok - ${(blob.size / 1024).toFixed(1)} KB - ${ms} ms - cache ${res.headers.get("X-Cache") || "?"}`;
      } catch (e) {
        $("meta").textContent = "error: " + (e.message || e);
      } finally { btn.disabled = false; }
    }
    $("render").addEventListener("click", doRender);
    $("reset").addEventListener("click", () => { Object.assign(state, DEFAULTS); renderControls(); updateCurl(); });
    $("text").addEventListener("input", updateCurl);
    $("copyCurl").addEventListener("click", () => navigator.clipboard.writeText($("curl").textContent).then(() => { $("copyCurl").textContent = "Copied"; setTimeout(() => $("copyCurl").textContent = "Copy", 1200); }));

    renderControls();
    updateCurl();
  </script>
</body>
</html>
"""
