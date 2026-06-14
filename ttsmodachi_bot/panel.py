from __future__ import annotations


LANDING_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>TTSmodachi - Discord TTS bot</title>
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
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    html { scroll-behavior: smooth; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }
    a { color: inherit; }
    .topbar {
      align-items: center;
      background: rgba(16, 17, 20, .94);
      border-bottom: 1px solid var(--border);
      display: flex;
      gap: 16px;
      justify-content: space-between;
      min-height: 64px;
      padding: 0 max(16px, calc((100vw - 1060px) / 2));
      position: sticky;
      top: 0;
      z-index: 5;
    }
    .brand {
      align-items: center;
      display: inline-flex;
      height: 44px;
      text-decoration: none;
    }
    .brand-mark {
      display: block;
      height: 44px;
      object-fit: contain;
      width: 44px;
    }
    .nav {
      align-items: center;
      display: flex;
      gap: 8px;
    }
    .nav a,
    .button {
      align-items: center;
      border: 1px solid var(--border);
      border-radius: 6px;
      display: inline-flex;
      font-weight: 700;
      justify-content: center;
      min-height: 36px;
      padding: 0 12px;
      text-decoration: none;
      white-space: nowrap;
    }
    .nav a:not(.button) {
      color: var(--muted);
      font-weight: 600;
    }
    .button.primary {
      background: var(--accent);
      border-color: var(--accent);
      color: #06130e;
    }
    .button.secondary {
      background: var(--panel-2);
      color: var(--text);
    }
    .hero {
      border-bottom: 1px solid var(--border);
      min-height: clamp(420px, 64svh, 560px);
      overflow: hidden;
      position: relative;
    }
    #voiceScene {
      height: 100%;
      inset: 0;
      opacity: .36;
      position: absolute;
      width: 100%;
    }
    .hero-inner {
      margin: 0 auto;
      max-width: 1060px;
      min-height: inherit;
      padding: 70px 16px 46px;
      position: relative;
      z-index: 1;
    }
    .hero-copy {
      max-width: 660px;
    }
    h1 {
      font-size: clamp(46px, 8vw, 88px);
      letter-spacing: 0;
      line-height: .92;
      margin: 0 0 14px;
    }
    .tagline {
      color: var(--text);
      font-size: clamp(22px, 3.4vw, 34px);
      font-weight: 800;
      line-height: 1.05;
      margin: 0 0 16px;
    }
    .lede {
      color: var(--muted);
      font-size: clamp(16px, 1.7vw, 19px);
      line-height: 1.5;
      margin: 0;
      max-width: 560px;
    }
    .hero-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      margin-top: 24px;
    }
    .hero-actions .button {
      min-height: 40px;
    }
    .analytics {
      padding: 42px 16px 56px;
    }
    .analytics-inner {
      margin: 0 auto;
      max-width: 1060px;
    }
    .analytics h2 {
      font-size: clamp(24px, 3vw, 34px);
      letter-spacing: 0;
      line-height: 1.1;
      margin: 0 0 8px;
    }
    .analytics p {
      color: var(--muted);
      line-height: 1.5;
      margin: 0 0 18px;
      max-width: 620px;
    }
    .stats {
      display: grid;
      gap: 12px;
      grid-template-columns: repeat(4, minmax(0, 1fr));
    }
    .stat {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      min-height: 104px;
      overflow: hidden;
      padding: 14px;
    }
    .stat strong {
      display: block;
      font-size: clamp(28px, 3.6vw, 40px);
      line-height: 1;
      margin-bottom: 9px;
      min-height: 42px;
    }
    .stat strong.slide .number-value {
      animation: numberSlide .42s ease-in-out both;
    }
    .number-value {
      display: inline-block;
    }
    .stat span {
      color: var(--muted);
      line-height: 1.4;
    }
    .footer {
      align-items: center;
      border-top: 1px solid var(--border);
      color: var(--muted);
      display: flex;
      gap: 12px;
      justify-content: flex-end;
      padding: 22px max(16px, calc((100vw - 1060px) / 2));
    }
    .footer-links {
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
    }
    .footer a { font-weight: 700; text-decoration: none; }
    @keyframes numberSlide {
      from { opacity: .15; transform: translateY(16px); }
      to { opacity: 1; transform: translateY(0); }
    }
    @media (prefers-reduced-motion: reduce) {
      html { scroll-behavior: auto; }
      .stat strong.slide .number-value { animation: none; }
    }
    @media (max-width: 860px) {
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
    @media (max-width: 620px) {
      .topbar { align-items: flex-start; flex-direction: column; gap: 10px; padding-bottom: 12px; padding-top: 12px; position: static; }
      .nav { flex-wrap: wrap; }
      .hero { min-height: 470px; }
      .hero-inner { padding-top: 42px; }
      .stats { grid-template-columns: 1fr; }
      .footer { align-items: flex-start; flex-direction: column; }
    }
  </style>
</head>
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TTSmodachi home"><img class="brand-mark" src="/static/ttsmodachi-logo.webp?v=2" alt="" width="44" height="44"></a>
    <nav class="nav" aria-label="Main navigation">
      <a class="button secondary" id="navSupport" href="#">Support</a>
      <a class="button primary" id="navInvite" href="#">Invite bot</a>
    </nav>
  </header>

  <main>
    <section class="hero">
      <canvas id="voiceScene" aria-hidden="true"></canvas>
      <div class="hero-inner">
        <div class="hero-copy">
          <h1>TTSmodachi</h1>
          <p class="tagline">TTS bot, but Tomodachi.</p>
          <p class="lede">Invite it, run /join, and Discord messages get read in voice chat with customizable weird little voices. Use /voice to tune yours.</p>
          <div class="hero-actions">
            <a class="button primary" id="heroInvite" href="#">Invite to Discord</a>
            <a class="button secondary" id="heroSupport" href="#">Support Discord</a>
          </div>
        </div>
      </div>
    </section>

    <section class="analytics" id="analytics">
      <div class="analytics-inner">
        <h2>Live analytics</h2>
        <p>Counts refresh automatically.</p>
        <div class="stats">
          <div class="stat"><strong id="statServers"><span class="number-value">-</span></strong><span>servers</span></div>
          <div class="stat"><strong id="statVoices"><span class="number-value">-</span></strong><span>linked users</span></div>
          <div class="stat"><strong id="statRenders"><span class="number-value">-</span></strong><span>render requests</span></div>
          <div class="stat"><strong id="statWorkers"><span class="number-value">-</span></strong><span>render workers</span></div>
        </div>
      </div>
    </section>
  </main>

  <footer class="footer">
    <div class="footer-links">
      <a id="footerInvite" href="#">Invite</a>
      <a id="footerSupport" href="#">Support</a>
      <a href="/tos">Terms</a>
      <a href="/privacy-policy">Privacy</a>
    </div>
  </footer>

  <script>
    const ids = (id) => document.getElementById(id);
    const formatNumber = (value) => Number(value || 0).toLocaleString();

    function setLink(id, href) {
      const element = ids(id);
      if (!element || !href) return;
      element.href = href;
    }

    function setNumber(id, value) {
      const element = ids(id);
      if (!element) return;
      const next = Number(value || 0);
      const previous = Number(element.dataset.value || 0);
      const number = document.createElement("span");
      number.className = "number-value";
      number.textContent = formatNumber(next);
      element.replaceChildren(number);
      element.dataset.value = String(next);
      element.classList.remove("slide");
      if (next > previous) {
        void element.offsetWidth;
        element.classList.add("slide");
      }
    }

    async function loadSummary() {
      try {
        const response = await fetch("/api/bot/summary", {cache: "no-store"});
        if (!response.ok) throw new Error(await response.text());
        const summary = await response.json();
        const bot = summary.bot || {};
        const analytics = summary.analytics || {};
        const renderer = summary.renderer || {};
        const pool = renderer.pool || {};
        const workers = Array.isArray(pool.workers) ? pool.workers.length : 0;
        for (const id of ["navInvite", "heroInvite", "footerInvite"]) setLink(id, bot.inviteUrl);
        for (const id of ["navSupport", "heroSupport", "footerSupport"]) setLink(id, bot.supportUrl);
        setNumber("statServers", analytics.serverCount);
        setNumber("statVoices", analytics.linkedAccountCount);
        setNumber("statRenders", analytics.renderRequestCount);
        setNumber("statWorkers", workers);
      } catch (error) {
      }
    }

    function drawScene(time = 0) {
      const canvas = ids("voiceScene");
      if (!canvas) return;
      const dpr = Math.max(1, window.devicePixelRatio || 1);
      const width = canvas.clientWidth;
      const height = canvas.clientHeight;
      if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
        canvas.width = Math.floor(width * dpr);
        canvas.height = Math.floor(height * dpr);
      }
      const ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.strokeStyle = "#31c48d";
      ctx.lineWidth = 3;
      for (let row = 0; row < 8; row += 1) {
        const base = height * .25 + row * 38;
        ctx.globalAlpha = .18 + row * .035;
        ctx.beginPath();
        for (let x = -20; x <= width + 20; x += 8) {
          const y = base + Math.sin((x + time / 24 + row * 34) * .018) * (18 + row * 2);
          if (x === -20) ctx.moveTo(x, y);
          else ctx.lineTo(x, y);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = 1;
      requestAnimationFrame(drawScene);
    }

    loadSummary();
    setInterval(loadSummary, 10000);
    requestAnimationFrame(drawScene);
  </script>
</body>
</html>
"""


LEGAL_PAGE_STYLE = """
  <style>
    :root {
      color-scheme: dark;
      --bg: #101114;
      --panel: #181a20;
      --border: #30343e;
      --text: #f3f4f6;
      --muted: #a2a9b4;
      --accent: #31c48d;
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      background: var(--bg);
      color: var(--text);
      margin: 0;
      min-height: 100vh;
    }
    a { color: inherit; }
    .topbar {
      align-items: center;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      min-height: 64px;
      padding: 0 max(16px, calc((100vw - 860px) / 2));
    }
    .brand {
      align-items: center;
      display: inline-flex;
      height: 44px;
      text-decoration: none;
    }
    .brand-mark {
      display: block;
      height: 44px;
      object-fit: contain;
      width: 44px;
    }
    .nav {
      display: flex;
      gap: 14px;
    }
    .nav a,
    .footer a {
      color: var(--muted);
      font-weight: 700;
      text-decoration: none;
    }
    main {
      margin: 0 auto;
      max-width: 860px;
      padding: 44px 16px 64px;
    }
    .doc {
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: clamp(20px, 4vw, 34px);
    }
    h1 {
      font-size: clamp(34px, 5vw, 56px);
      letter-spacing: 0;
      line-height: 1;
      margin: 0 0 10px;
    }
    .updated {
      color: var(--muted);
      margin: 0 0 28px;
    }
    h2 {
      font-size: 20px;
      letter-spacing: 0;
      margin: 28px 0 10px;
    }
    p,
    li {
      color: var(--muted);
      font-size: 16px;
      line-height: 1.62;
    }
    p { margin: 0 0 14px; }
    ul { margin: 0 0 16px; padding-left: 22px; }
    strong { color: var(--text); }
    .footer {
      border-top: 1px solid var(--border);
      color: var(--muted);
      display: flex;
      gap: 14px;
      justify-content: space-between;
      padding: 22px max(16px, calc((100vw - 860px) / 2));
    }
    .footer-links {
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
    }
    @media (max-width: 620px) {
      .topbar,
      .footer {
        align-items: flex-start;
        flex-direction: column;
        gap: 12px;
        padding-bottom: 14px;
        padding-top: 14px;
      }
      .nav { flex-wrap: wrap; }
    }
  </style>
"""


def legal_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title} - TTSmodachi</title>
{LEGAL_PAGE_STYLE}</head>
<body>
  <header class="topbar">
    <a class="brand" href="/" aria-label="TTSmodachi home"><img class="brand-mark" src="/static/ttsmodachi-logo.webp?v=2" alt="" width="44" height="44"></a>
    <nav class="nav" aria-label="Legal navigation">
      <a href="/tos">Terms</a>
      <a href="/privacy-policy">Privacy</a>
      <a href="/">Support</a>
    </nav>
  </header>
  <main>
    <article class="doc">
      <h1>{title}</h1>
      <p class="updated">Last updated: June 14, 2026</p>
{body}
    </article>
  </main>
  <footer class="footer">
    <span>TTSmodachi</span>
    <div class="footer-links">
      <a href="/">Home</a>
      <a href="/tos">Terms</a>
      <a href="/privacy-policy">Privacy</a>
      <a href="/">Support</a>
    </div>
  </footer>
</body>
</html>
"""


TOS_HTML = legal_page(
    "Terms of Service",
    """      <p>These terms apply to your use of TTSmodachi, a Discord text-to-speech bot and voice settings dashboard.</p>
      <h2>Using the bot</h2>
      <p>By inviting or using TTSmodachi, you agree to use it only in servers where you have permission to use it. You are responsible for how you configure the bot and for the messages you choose to have read aloud.</p>
      <ul>
        <li>Follow Discord's Terms of Service, Community Guidelines, Developer Terms, and Developer Policy.</li>
        <li>Do not use the bot for harassment, spam, impersonation, illegal content, or content that violates someone else's rights.</li>
        <li>Do not try to overload, break, reverse engineer, or abuse the bot, dashboard, renderer, or supporting services.</li>
        <li>Do not use the bot to speak private or sensitive information in a voice channel where it should not be heard.</li>
      </ul>
      <h2>Voice channels and messages</h2>
      <p>TTSmodachi can join voice channels and read configured Discord messages aloud. Server admins and permitted users control where it joins and which settings are enabled. Voice output may be delayed, inaccurate, unavailable, or different from the original text after cleanup and filtering.</p>
      <h2>Account linking</h2>
      <p>The /voice command links your Discord account to the voice dashboard so your custom voice can be saved. You can use /unlink to disconnect that dashboard link.</p>
      <h2>Service changes</h2>
      <p>TTSmodachi is provided as-is. We may change commands, limits, availability, features, or these terms at any time to keep the bot stable, safe, or compliant with platform rules.</p>
      <h2>Removal</h2>
      <p>You can remove the bot from a server through Discord, use /leave to disconnect it from voice, or contact support if you need help with account or server data.</p>
      <h2>Warranty and liability</h2>
      <p>The bot is provided without warranties. To the maximum extent allowed by law, TTSmodachi and its operators are not liable for indirect, incidental, special, consequential, or punitive damages related to use of the bot.</p>
      <h2>Contact</h2>
      <p>Questions, abuse reports, or data requests should go to whoever is running your copy of the bot.</p>""",
)


PRIVACY_POLICY_HTML = legal_page(
    "Privacy Policy",
    """      <p>This policy explains what TTSmodachi processes when you use the Discord bot or the voice dashboard.</p>
      <h2>Data we process</h2>
      <ul>
        <li>Discord IDs for users, servers, channels, roles, and the bot account, so settings and voice connections work in the right place.</li>
        <li>Server settings, including setup channel, role requirements, prefix, message length, emoji behavior, name announcement, and default voice.</li>
        <li>User voice settings, saved voice presets, selected default voice, custom TTS names, and text replacement rules.</li>
        <li>When you use /voice, your Discord user ID, display name, avatar URL, and link time for the dashboard session.</li>
        <li>Aggregate analytics such as server count, linked account count, render count, worker count, and queue/runtime health.</li>
      </ul>
      <h2>Message content</h2>
      <p>When the bot is active in a configured channel, message text and attachment filenames may be read, cleaned, and sent to the renderer so audio can be generated. TTSmodachi does not intentionally store raw Discord message text as database records. Generated audio may be cached as WAV files to improve speed and reduce duplicate rendering; that cache is pruned by size.</p>
      <h2>How we use data</h2>
      <p>We use this data to operate the bot, join and leave voice channels, generate speech, save your voice settings, run the dashboard, display public aggregate analytics, debug failures, prevent abuse, and keep the service stable.</p>
      <h2>Sharing</h2>
      <p>We do not sell personal data. Data may be processed by Discord, the server hosting provider, and services needed to run the bot and dashboard. Information may also be shared if required to comply with law, platform rules, or abuse investigations.</p>
      <h2>Retention and deletion</h2>
      <p>Server and user settings are kept until they are changed, deleted, unlinked, or the bot is removed and the data is cleaned up. Use /unlink to remove your dashboard account link and dashboard voice preset. Use /voices delete to delete saved custom voices. Server admins can change or remove server settings. Contact support for other deletion requests.</p>
      <h2>Security</h2>
      <p>We use reasonable technical measures to protect stored settings and dashboard links, but no online service can guarantee perfect security.</p>
      <h2>Children</h2>
      <p>TTSmodachi is intended for Discord users who are allowed to use Discord. It is not directed to children under 13.</p>
      <h2>Changes</h2>
      <p>We may update this policy when the bot changes or when legal, platform, or operational requirements change. The updated date at the top of this page shows the latest version.</p>
      <h2>Contact</h2>
      <p>Privacy questions or data requests should go to whoever is running your copy of the bot.</p>""",
)

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
      languages: ["useng"],
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
    const LINK_REQUIRED_MESSAGE = "Use /voice to link your account first!";

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
      const languages = state.languages.length ? state.languages : ["useng"];
      if (!languages.includes(state.values.lang)) state.values.lang = languages[0];
      const options = languages.map((lang) => `<option value="${lang}">${lang}</option>`).join("");
      langWrap.innerHTML = `<label for="lang"><span>Language</span><output id="langOut">${state.values.lang}</output></label><select id="lang">${options}</select>`;
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
        : LINK_REQUIRED_MESSAGE;
      $("command").value = `${status}\n\npitch:${v.pitch} speed:${v.speed} quality:${v.quality} tone:${v.tone} accent:${v.accent} intonation:${v.intonation} lang:${v.lang} volume:${v.volume}`;
    }

    function requireLinkedSession() {
      if (state.session) return true;
      setUnlinkedStatus();
      return false;
    }

    function setUnlinkedStatus() {
      setStatus(LINK_REQUIRED_MESSAGE);
      updateCommand();
    }

    function setReadyStatus() {
      setStatus(state.session ? "ready" : LINK_REQUIRED_MESSAGE);
    }

    function applyVoice(params) {
      state.values = {...state.values, ...params};
      if (!state.languages.includes(state.values.lang)) {
        state.values.lang = state.languages[0] || "useng";
      }
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
      if (!requireLinkedSession()) {
        alert(LINK_REQUIRED_MESSAGE);
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
        $("save").disabled = true;
        setStatus(LINK_REQUIRED_MESSAGE);
        updateCommand();
        return;
      }
      const config = await response.json();
      state.builtins = config.builtins;
      state.languages = Array.isArray(config.languages) && config.languages.length ? config.languages : ["useng"];
      if (!state.languages.includes(state.values.lang)) state.values.lang = state.languages[0];
      renderControls();
      renderPresets();
      let finalStatus = state.session ? "ready" : LINK_REQUIRED_MESSAGE;
      if (state.token) {
        const sessionResponse = await fetch("/api/session", {headers: {"X-Panel-Token": state.token}});
        if (sessionResponse.ok) {
          state.session = await sessionResponse.json();
          applyVoice(state.session.voice);
          renderIdentity();
          finalStatus = "linked";
        } else {
          state.session = null;
          sessionStorage.removeItem("ttsmodachiToken");
          sessionStorage.removeItem("talkmodachiToken");
          finalStatus = LINK_REQUIRED_MESSAGE;
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
      setReadyStatus();
    });
    $("reset").addEventListener("click", () => {
      applyVoice({pitch: 50, speed: 50, quality: 50, tone: 50, accent: 50, intonation: 1, lang: "useng", volume: 165});
      setReadyStatus();
    });

    loadConfig();
  </script>
</body>
</html>
"""
