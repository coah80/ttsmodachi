# LTD staging

TTSModachi keeps the existing 3DS/Citra engine as `tl3ds`. Tomodachi Life: Living the Dream work is isolated as the experimental `ltd-switch` engine. The current bridge can render arbitrary text through the LTD VoiceText path in a headless Ryubing process and return voice-only WAV bytes from a direct PCM tap.

## Local inputs

- Base NSP: `Tomodachi Life Living the Dream.nsp`
- SHA-256: `497f09bc3cfe386b08f98971cd2f263b1dfa0decbbb005a4b641705f520a1021`
- Title ID: `010051f0207b2000`
- Version: `0`
- Main build ID: `56BF85BD535413464CB75BB6C2683B6711E0BC0B000000000000000000000000`
- Local-only work dirs: `ltd-work/`, `ryubing-work/`

Do not commit NSP/NCA/key material. The repo ignores Switch package formats, key files, and LTD work directories.

## Staging contract

- Engine id: `ltd-switch`
- Current production default: `tl3ds`
- First target: base NSP only
- Required before enabling in Discord: build id check, versioned address table, voice parameter mapping, queue/cache integration, and staging benchmark against current 3DS warm/cache/idle numbers.

## Boot smoke

- Ryubing source: `93f23cd`
- Local build: `dotnet build -c Release -o build`
- Boot command: headless Ryubing with isolated `ltd-work/ryubing-data`
- Firmware installed locally into isolated Ryubing data dir from `Firmware 21.1.0.zip`
- Result: NSP loads as `Tomodachi Life: Living the Dream v1.0.0`, Vulkan initializes, audio renderer starts, and the title can be advanced through first-run software keyboard/profile flows in headless mode.
- Current status: arbitrary short text can be dispatched through the LTD voice request object and captured as voice-only 32 kHz mono WAV through the cold or warm worker. The worker now defaults to LightningJIT `HostMappedUnsafe`, not software-page-table tracing.

## Ryubing instrumentation

The reproducible local Ryubing diff is stored in `docs/ryubing-ttsmodachi.patch`. Apply it from a Ryubing checkout root.

Implemented hooks:

- Headless software keyboard auto-accept via `RYUJINX_HEADLESS_SWKBD_AUTO_ACCEPT` and `RYUJINX_HEADLESS_SWKBD_TEXTS`.
- Headless controller input via static/live scripts: `RYUJINX_TTSMODACHI_INPUT_SCRIPT`, `RYUJINX_TTSMODACHI_INPUT_FILE`, and `RYUJINX_TTSMODACHI_AUTO_A`.
- Headless touch input via static/live scripts: `RYUJINX_TTSMODACHI_TOUCH_SCRIPT` and `RYUJINX_TTSMODACHI_TOUCH_FILE`.
- Optional PCM audio trace/dump in Ryubing DSP data-source commands via `RYUJINX_TTSMODACHI_AUDIO_TRACE` and `RYUJINX_TTSMODACHI_AUDIO_DUMP_DIR`. The trace records pre/post wave-buffer index, consumed count, DSP address, and guest CPU address for each active wave buffer. Appliance mode disables this by default because the direct PCM tap is enough for production renders.
- ARMeilleure guest-address tracing via `RYUJINX_TTSMODACHI_GUEST_TRACE`, `RYUJINX_TTSMODACHI_GUEST_TRACE_BASE`, `RYUJINX_TTSMODACHI_GUEST_TRACE_ADDRS`, and optional `RYUJINX_TTSMODACHI_GUEST_TRACE_RANGE`.
- `RYUJINX_TTSMODACHI_DISABLE_HYPERVISOR=true` override for trace runs. On Apple Silicon, trace mode also needs `--memory-manager-mode SoftwarePageTable`; otherwise Ryubing uses Hypervisor or LightningJit and ARMeilleure hooks will not fire.
- Optional `RYUJINX_TTSMODACHI_MANAGED_DISPATCH=true` / `--trace-exec` path for targeted execution-hit tracing. Keep this off for broad `--trace-main` runs unless the event cap is high enough.
- Optional ARMeilleure guest write watch via `RYUJINX_TTSMODACHI_MEMORY_WRITE_TRACE` and `RYUJINX_TTSMODACHI_MEMORY_WRITE_RANGES`. The trace logs destination address, source PC, LR/x30, and x0/x1/x2 so `memcpy` writes can be traced back to their caller and source buffer.
- Basic-block register tracing via `RYUJINX_TTSMODACHI_BLOCK_TRACE` and `RYUJINX_TTSMODACHI_BLOCK_TRACE_ADDRS`.
- LTD text injection via `RYUJINX_TTSMODACHI_TEXT_INJECT` at `RYUJINX_TTSMODACHI_TEXT_INJECT_ADDR=0x444660`. The hook writes the UTF-8 bytes into the game's current text buffer and updates `x3` to the injected byte length.
- LTD appliance dispatch via `RYUJINX_TTSMODACHI_APPLIANCE=true`. This writes the request text into the live VoiceText request object, dispatches the request wrapper at `main+0x4445CC`, and captures raw voice PCM at `main+0x465714` without relying on menu navigation or DSP output capture.
- Experimental bootstrap context capture/replay via `RYUJINX_TTSMODACHI_APPLIANCE_BOOTSTRAP_CAPTURE_ADDRS`, `RYUJINX_TTSMODACHI_APPLIANCE_BOOTSTRAP_TRIGGER_ADDRS`, `RYUJINX_TTSMODACHI_APPLIANCE_BOOTSTRAP_ADDR`, and `RYUJINX_TTSMODACHI_APPLIANCE_BOOTSTRAP_FRAME_FILE`. This is for no-title RE only; it is off by default.
- Early appliance dispatch plus context restore is enabled by default via `TTSMODACHI_LTD_APPLIANCE_DISPATCH_ON_CAPTURE=true` and `TTSMODACHI_LTD_APPLIANCE_CONTEXT_RESTORE=true`. The hook dispatches from the early `main+0x600EFC` VoiceText capture point, restores the interrupted guest context, and still lets the later audio/PCM path run normally.
- Appliance park mode via `RYUJINX_TTSMODACHI_APPLIANCE_PARK=true`. Once the VoiceText object is initialized, the guest parks at the hook poll site until a text file changes; after dispatch it lets only the PCM-producing path run, then parks again. This keeps the full title from continuing normal menu/gameplay flow between requests.
- Scripted controller/touch boot input is disabled by default for appliance mode. Set `TTSMODACHI_LTD_BOOT_INPUT=true` only for first-run setup/debug data dirs that still need UI advancement.
- Dummy audio backend via `RYUJINX_TTSMODACHI_DUMMY_AUDIO=true`. Headless Ryubing uses `DummyHardwareDeviceDriver` in appliance mode instead of initializing SDL audio.
- Host audio sink mute via `RYUJINX_TTSMODACHI_MUTE_DEVICE_SINK=true`. This skips final mixed-audio output to the host device while preserving the direct VoiceText PCM tap.
- LightningJIT injection support for the same text/block hooks, allowing `--memory-manager-mode HostMappedUnsafe` with Hypervisor disabled. ARMeilleure/software-page-table is now only needed for broad tracing.
- Final sink capture via `RYUJINX_TTSMODACHI_OUTPUT_CAPTURE_DIR` exists for debugging mixed output, but `LtdSwitchWorker` defaults to appliance direct PCM capture, dummy audio, disabled DSP dumps, and muted host sink so game music/UI audio is not returned.

Probe command:

```sh
./tools/ltd_ryubing_probe.py \
  --game "$TTSMODACHI_LTD_GAME_PATH" \
  --out-dir ltd-work/probe-armeilleure-maintrace \
  --seconds 120 \
  --jit \
  --trace-main
```

Targeted execution trace command:

```sh
./tools/ltd_ryubing_probe.py \
  --game "$TTSMODACHI_LTD_GAME_PATH" \
  --out-dir ltd-work/probe-armeilleure-exectrace \
  --seconds 120 \
  --jit \
  --trace-exec \
  --guest-addrs "0x5fffe8,0x600330,0x600bec,0x600d78,0x43f704,0x465380,0x1500ae0,0x1415db0"
```

Trace correlation:

```sh
./tools/ltd_trace_correlate.py ltd-work/probe-armeilleure-maintrace
```

Memory-write trace summary:

```sh
./tools/ltd_memory_trace_summary.py ltd-work/probe-writewatch-regs/memory-writes.csv
```

Static caller scan:

```sh
./tools/ltd_static_callers.py 0x465598 0x43f704 0x4445cc 0x443cec 0x5fffe8 \
  --text ltd-work/analysis/main.text.bin \
  --branches
```

String xref scan:

```sh
./tools/ltd_string_xrefs.py \
  "END of LOADTTS" \
  "VoiceText/tts_single_db(D32-GLORIA).vtdb2" \
  "VoiceTextSynthesizer" \
  "VoiceTextMgr" \
  "VoiceText/userdict_eng.csv"
```

Block-trace indirect caller summary:

```sh
./tools/ltd_block_trace_callers.py \
  ltd-work/consumer-entry-trace-work/warm-eab0c54245ae4c8485c4609e11ce0076/block-trace.csv
```

Consumer register trace summary:

```sh
TTSMODACHI_LTD_APPLIANCE_TRACE_CONSUMER_REGISTERS=true ./tools/ltd_warm_render_text.py \
  "consumer register trace proof" \
  --work-dir ltd-work/consumer-reg-trace-work \
  --out-dir ltd-work/consumer-reg-trace-output

./tools/ltd_consumer_registers.py ltd-work/consumer-reg-trace-work/warm-*/appliance.csv
```

Consumer object dump:

```sh
TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_DIR=$PWD/ltd-work/consumer-object-dump \
TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_BYTES=256 \
TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_REGISTERS=0,19,21,22 \
./tools/ltd_warm_render_text.py "consumer object dump proof"

TTSMODACHI_LTD_APPLIANCE_CONSUMER_FRAME_FILE=$PWD/ltd-work/consumer-frame/parent-step.frame \
./tools/ltd_warm_render_text.py "consumer frame capture proof"
```

Request/voice-context dump:

```sh
TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_DIR=$PWD/ltd-work/request-dump/request-dumps \
TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_BYTES=4096 \
./tools/ltd_warm_render_text.py "request dump proof"

./tools/ltd_request_dump_summary.py ltd-work/request-dump/request-dumps
```

Init/context trace:

```sh
TTSMODACHI_LTD_APPLIANCE_CONTEXT_TRACE_ADDRS=0x5f7554,0x5ff764,0x5fffe8,0x600efc \
TTSMODACHI_LTD_APPLIANCE_CONTEXT_TRACE_ONCE=true \
./tools/ltd_warm_render_text.py "parent init context proof"

./tools/ltd_read_string.py \
  0xad2c687 0xad79dc2 0xad8647a 0xad537c3 0xadb96cf 0xad25d4f 0xad25d79
```

Current local trace result:

- 120s ARMeilleure trace run produced `59,656` guest trace rows and 4 PCM voice-like bursts.
- Captured PCM chunks were 48 kHz mono s16le, sourced from 32 kHz `PcmInt16` data-source nodes.
- Burst durations: `0.430s`, `0.625s`, `0.285s`, `0.660s`.
- Tight pre-audio guest candidates include relative addresses around `0x43fee8`, `0x465380`, `0x43f704`, `0x1500ae0`, `0x1415db0`, and `0x107f4d4`. These are not final bridge addresses yet; they are correlation targets for the next static RE pass.
- Timed execution tracing over the voice-preview window produced `233,857` `ExecuteSingle` rows and 4 PCM bursts. The closest repeated addresses were dominated by audio/render loops (`0x3004`, `0x927c`, `0x8262b8`, `0x6cadc`, `0x130b420`, `0x9fc4c4`, `0x4a0b68`), so this did not identify the synthesis bridge directly.
- Audio wave-buffer tracing showed the voice bursts entering Ryubing as 32 kHz PCM ring buffers at guest CPU/DSP ranges:
  - First preview lane: `0x65F76E7000-0x65F76E8000`
  - Later preview lane: `0x65F770F000-0x65F7710000`
- Write-watch on those final audio buffers shows they are filled by SDK `memcpy` at `sdk+0x5B0F28` / absolute `0xDD4FF28`, called mainly from:
  - `main+0x465714` / absolute `0x896B714`
  - `main+0x4659D8` / absolute `0x896B9D8`
- Register tracing on the same writes shows the immediate PCM source buffer in `x1`, commonly around `0x65F795B000` and `0x65F7A5B000+`.
- Write-watch on that source range shows another game-side ring-buffer copy at `main+0x43F7B0` / absolute `0x89457B0`, plus buffer clear/setup at `main+0x78668C` / absolute `0x8C8C68C`.
- Watching the next upstream range `0x65F9F97000-0x65FA300000` hit allocator/zeroing and queue setup quickly, especially `main+0x2055230`/`0x2055360` zero-fill helpers and callers around `main+0x601A34`/`0x601AEC`. That range is too broad for the next pass.
- Text request tracing found the LTD VoiceText request path:
  - `main+0x444660` / absolute `0x894A660`: text prep complete; `x2` is the text pointer and `x3` is the text byte length.
  - `main+0x443CEC` / absolute `0x8949CEC`: VoiceText dispatcher; it moves `x2` to `x1` and `w3` to `w2` before language-specific synthesis.
- Dynamic text injection proof:
  - `RYUJINX_TTSMODACHI_TEXT_INJECT="This is a test message."` produced four non-silent 48 kHz PCM chunks. First `main+0x444660` hit showed `x3=0x17`.
  - Control run `RYUJINX_TTSMODACHI_TEXT_INJECT="Hi."` produced shorter PCM chunks. First `main+0x444660` hit showed `x3=0x3`.
  - Package worker proof rendered `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/ltd-tts-works.wav` from `LtdSwitchWorker.render("LTD TTS works.")`; output is 48 kHz mono WAV, `0.900s`, `86,444` bytes.
- Voice-only LightningJIT worker proof:
  - `the quick brown fox jumps over the lazy dog` rendered to `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/voice-only-lightning-the-quick-brown-fox-jumps-over-the-lazy-dog.wav`; output is 48 kHz mono WAV, `2.455s`, `235,724` bytes, cold elapsed `21.086s`.
  - `custom audio with no music test` rendered to `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/voice-only-lightning-custom-audio-with-no-music-test.wav`; output is 48 kHz mono WAV, `1.845s`, `177,164` bytes, cold elapsed `19.931s`.
  - Both runs produced one `main+0x444660` block trace hit with `x3` matching the injected UTF-8 byte length and no mixed `output-audio.csv`.
- Current patched CLI proof:
  - `tools/ltd_render_text.py "the quick brown fox jumps over the lazy dog" --out ltd-work/ltd-renderer-proof/ltd-patched-quick-brown-fox.wav` produced 48 kHz mono WAV, `2.455s`, `235,724` bytes.
  - `tools/ltd_render_text.py "custom ltd tts output with no game music" --out ltd-work/ltd-renderer-proof/ltd-patched-custom-no-music.wav` produced 48 kHz mono WAV, `2.845s`, `273,164` bytes.
  - Output is selected from voice-only DSP data-source dumps, trimmed/faded, and normalized to peak `26000`, so game music is not returned even though the full title still boots behind the patch.
- Warm patched backend proof:
  - Ryubing now supports `RYUJINX_TTSMODACHI_TEXT_INJECT_FILE`, so the guest text request can be changed while the game process stays open.
  - `tools/ltd_warm_render_text.py "warm ltd message one" "warm ltd message two different words" --out-dir ltd-work/ltd-renderer-proof/warm-smoke2 --timeout 180` produced two voice-only WAVs from one Ryubing process: `1.365s`/`131,084` bytes and `2.470s`/`237,164` bytes.
  - Backend warm mode with `TTSMODACHI_LTD_WARM=1` produced `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/backend-warm/01.wav` and `02.wav` through `LtdSwitchWorker`; outputs were `1.400s`/`134,444` bytes and `2.445s`/`234,764` bytes.
- Direct appliance verdict:
  - Dispatching `main+0x4445CC` from the LightningJIT hook reaches `main+0x444660`, `main+0x443CEC`, and the downstream `main+0x465714` PCM copy path.
  - The Ryubing patch now taps `main+0x465714` directly, so the backend no longer depends on game UI audio or DSP wave-buffer selection for appliance mode.
- Versioned address-table pass:
  - `LtdSwitchWorker` now carries the base NSP address table in code and exposes the active request/capture/PCM addresses in `/health`.
  - The confirmed text dispatcher `main+0x443CEC` is recorded in the table for RE, but it is intentionally excluded from the default block trace because tracing it during startup makes this Ryubing build exit before VoiceText readiness. Use `TTSMODACHI_LTD_APPLIANCE_BLOCK_TRACE_ADDRS` only for targeted debugger runs.
  - Runtime env overrides still exist for RE experiments, but the default base-build path no longer depends on duplicate loose string defaults.
  - Stable address-table proof prewarmed in `14.111s`, rendered `address table stable proof` in `2.769s`, and returned a non-silent 32 kHz mono WAV with SHA-256 prefix `ba7bbc9760098d67`.
- Consumer-kick performance pass:
  - The worker now captures the final audio-ring consumer function at `main+0x465598` and can kick that same function from the appliance poll loop while PCM is pending.
  - With a primer render, `consumer kick entry proof` and `consumer kick second message` rendered in `2.021s` and `2.342s`, returning distinct non-silent 32 kHz mono WAVs with SHA-256 prefixes `0fdf2bf92b09f9a6` and `952b8a01610e8516`.
  - Without a primer render, `consumer ready first/second/third message` prewarmed in `13.666s` and rendered in `2.799s`, `2.651s`, and `2.343s`; same-length `a...`/`z...` requests produced distinct traces and WAV hashes. This is now enabled as a bounded default (`8` kicks at `20ms`) but can be disabled with `TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_MAX=0`.
  - Retesting the normal defaults with no env overrides prewarmed in `13.882s`, then rendered `consumer default proof one` and `consumer default proof two` in `2.813s` and `2.333s`; outputs were distinct non-silent 32 kHz mono WAVs with SHA-256 prefixes `ba7bbc9760098d67` and `0c7fabe506834a08`.
  - The experimental fast profile captures and replays the parent consumer-step function at `main+0x2AD98C` instead of the lower final-copy function. With `TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_MAX=64` and `TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_INTERVAL_MS=0`, a seeded warm worker prewarmed in `13.571s`, then rendered `same length test alpha`, `same length test bravo`, and the pangram in `1.257s`, `0.167s`, and `2.351s`.
  - The same-length fast replay validation produced distinct WAV hashes (`5e855d5632583da6`, `bf22d675b85ce1f0`) and dispatch text hashes (`df3d4e10cf8f2d90`, `03084fef507188ab`), so the sub-200ms second request was not just the prior request returned from the append-only PCM file.
  - Retesting with the new default address table and no consumer env overrides prewarmed in `14.931s`, then rendered `default fast profile one`, `default fast profile two`, and the pangram in `1.261s`, `0.170s`, and `1.103s`. Outputs were distinct non-silent 32 kHz mono WAVs with SHA-256 prefixes `20c99575e7b52b90`, `aee13d0fd01c1fe1`, and `e428494d91cf0d51`.
- Graphics/log tuning pass:
  - `TTSMODACHI_LTD_RESOLUTION_SCALE=0.25` and `0.5` both failed during boot with MoltenVK mip-level validation errors (`32x32` supports max 6 levels and `64x64` supports max 7 levels), so resolution scale stays unset by default.
  - `TTSMODACHI_LTD_BACKEND_THREADING=Off` was stable but not faster: prewarm `14.341s`, renders `2.806s` and `2.344s`, non-silent 32 kHz WAV SHA-256 prefixes `c47cbde3fb1f97d2` and `5586951100da30fc`.
  - `TTSMODACHI_LTD_QUIET_LOGS=true` is the default. It keeps warnings/errors but disables stub/info/guest spam; proof prewarmed in `13.659s`, rendered `quiet logs default proof` in `2.503s`, and produced a non-silent 32 kHz mono WAV, `1.714s`, peak `26000`, SHA-256 prefix `ec3b4422def81a56`. The Ryubing log was `13,422` bytes.
- PCM capture is request-bounded using the current text length, sample rate, and configured min/max seconds so a warm worker can serve multiple texts from one append-only PCM file. There is an opt-in quiet-tail capture mode (`TTSMODACHI_LTD_PCM_WAIT_FOR_QUIET_TAIL=true`) for debugging clipped phrases, but the production default stays on the faster estimate-based capture because the larger capture budget adds latency.
- Upstream PCM tap experiments at `main+0x43F7B0` and `main+0x43F7AC` did not produce appliance PCM in direct-dispatch mode, so the reliable production tap remains the final audio-ring copy at `main+0x465714`.
- The context-restore trampoline now dispatches at the early `main+0x600EFC` capture point by default without corrupting the caller. This proves the request wrapper can be called during init, but it does not make PCM arrive immediately because the queued VoiceText job is consumed later by the game/audio update path.

Current patch verdict:

- LTD TTS works as a headless appliance path: text input reaches the Switch VoiceText synthesis call in a running Ryubing process and voice-only WAV output is captured without returning game music.
- The repo has direct local entrypoints for arbitrary text to WAV: `tools/ltd_render_text.py` for cold renders and `tools/ltd_warm_render_text.py` for one warm process serving multiple texts.
- Fresh LTD worker data dirs can be bootstrapped from a private Ryubing seed via `TTSMODACHI_LTD_SEED_DATA_DIR`. The seed must contain firmware, profiles, and a minimal LTD save/Mii context; no seed contents are committed.
- Voice parameters affect output through a fast post-render pitch/speed/tone transform. Native in-game LTD voice parameter mapping is not done yet.
- Cold boot is still about `16-22s`, but warm mode keeps the process open and can render repeated custom text from the same process without menu navigation. The current warm latency tracks output length because the backend waits for the full PCM request before returning.
- The patch now has the request-side bridge (`main+0x444660`), direct dispatch (`main+0x4445CC`), direct PCM tap (`main+0x465714`), live text-file bridge, appliance park mode, discard-present rendering, backend warm worker, renderer API integration, cache integration, signed panel persistence, output limiting, and idle suspend/resume. The remaining hard gap is replacing the initial full title boot with a true extracted/standalone LTD TTS engine.
- Appliance production defaults are now direct PCM only: `TTSMODACHI_LTD_ENABLE_DSP_TRACE=false` avoids per-buffer DSP trace/dump overhead, `TTSMODACHI_LTD_DUMMY_AUDIO=true` avoids SDL audio backend setup, `TTSMODACHI_LTD_MUTE_DEVICE_SINK=true` skips final mixed output to the host audio device, and `TTSMODACHI_LTD_DISCARD_PRESENT=true` consumes frame callbacks without presenting textures or swapping buffers.
- Appliance production defaults use the final-copy replay (`main+0x465598`, `8` kicks at `20ms`) because burst tests showed the parent consumer-step fast profile can poison Ryubing's audio thread. The parent replay (`main+0x2AD98C`, `64` immediate kicks) remains documented as an opt-in experiment for short latency probes.
- Appliance production defaults now also enable primer prewarm (`TTSMODACHI_LTD_PREWARM_PRIMER=true`) so server startup pays the first synthesis setup cost before Discord traffic starts. With stable final-copy replay, a five-message burst prewarmed in `15.292s`, then rendered `primer alpha one`, `primer bravo two`, `primer charlie three`, `primer delta four`, and the pangram in `0.323s`, `1.106s`, `1.411s`, `2.037s`, and `2.497s`. The outputs were distinct non-silent 32 kHz mono WAVs.
- Appliance mode also defaults `TTSMODACHI_LTD_DISABLE_SHADER_CACHE=true`. The title still creates a graphics device, but skipping shader-cache loading is faster for this server-side voice appliance because rendered visuals are discarded.

Latest local proof:

- ACK/repeat proof after direct PCM handoff fix:
  - The host now writes `RYUJINX_TTSMODACHI_APPLIANCE_PCM_ACK_FILE` after it has copied a request's PCM bytes. Ryubing consumes ACK tokens even when no PCM is pending, so stale prewarm ACKs cannot cancel the next request.
  - `tools/ltd_warm_render_text.py "ack test one" "ack test two"` prewarmed in `17.114s`, then rendered two back-to-back warm requests in `0.944s` and `0.783s`.
  - `tools/ltd_warm_render_text.py "the quick brown fox jumps over the lazy dog" "custom audio should come from this exact sentence" "discord server text to speech proof"` prewarmed in `16.481s`, then rendered in `2.804s`, `3.734s`, and `2.809s`. Outputs were non-silent 32 kHz mono WAVs with SHA-256 prefixes `d48d9ef95637d2c0`, `21b999263124f2f6`, and `a23e679e375b838d`.
- Seed bootstrap proof:
  - A partial save-only copy is not enough; Ryubing exits before reaching the LTD TTS manager without the full firmware/profile environment.
  - `TTSMODACHI_LTD_SEED_DATA_DIR=ltd-work/ryubing-data` with a brand-new `TTSMODACHI_LTD_DATA_DIR` copied the private seed, prewarmed in `17.050s`, and rendered `bootstrap seed text in audio out proof` in `2.359s`.
  - The bootstrap output was 32 kHz mono, `2.714s`, peak `26000`, SHA-256 prefix `19333eadddcee0fe`.
- No-input boot proof:
  - `TTSMODACHI_LTD_BOOT_INPUT=false tools/ltd_warm_render_text.py "no input headless appliance proof"` reached VoiceText without scripted controller/touch input, prewarmed in `17.778s`, and rendered in `2.962s`.
  - This is now the default appliance boot profile; prepared seed data is expected instead of driving setup menus.
  - With the default no-input profile plus `TTSMODACHI_LTD_SEED_DATA_DIR=ltd-work/ryubing-data`, a brand-new worker data dir prewarmed in `17.518s` and rendered `default no input bootstrap proof` in `2.637s`. The output was 32 kHz mono, `2.286s`, peak `26000`, SHA-256 prefix `af3c5e156489eaef`.
- Cold post-rebuild: `tools/ltd_render_text.py "post rebuild ltd cold render"` produced `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/user-request-test-now/post-rebuild-cold.wav`, 32 kHz mono, `2.000s`, peak `26000`, SHA-256 prefix `c03aaffd777946fe`.
- Warm post-rebuild: `tools/ltd_warm_render_text.py "warm ltd message one" "the quick brown fox jumps over the lazy dog"` prewarmed in `18.735s`, then rendered `1.704s` and `3.545s` requests from one process. Outputs were 32 kHz mono WAVs with SHA-256 prefixes `afab0b6594169466` and `3a950606ae337276`.
- Appliance park proof:
  - `tools/ltd_render_text.py "park mode text in audio out proof"` produced `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/park-mode-cold-2.wav`, 32 kHz mono, `2.357s`, peak `26000`, SHA-256 prefix `440b4ccb8d2ba65e`.
  - `tools/ltd_warm_render_text.py "park warm message one" "the quick brown fox jumps over the lazy dog"` prewarmed in `18.090s`, then rendered `1.688s` and `3.510s` requests from one process. Outputs were 32 kHz mono WAVs with SHA-256 prefixes `565ffd6f93f11d2e` and `ad6175a8b27c62b0`.
  - The warm appliance trace shows `park,waiting-for-text` events between dispatches, then new `dispatch,ok` events when the text file changes. Blocking immediately after dispatch was tested and failed because it starved the downstream PCM copy; the working park mode allows execution while `_pcmDumpRemainingBytes > 0`, then parks.
- HTTP renderer proof:
  - Local LTD-only renderer service started with `TTSMODACHI_WORKER_ROMS=LTD`, `TTSMODACHI_LTD_ENABLED=1`, `TTSMODACHI_LTD_WARM=1`, and the local NSP/Ryubing paths.
  - `/render` with `voice.engine="ltd-switch"` returned HTTP 200, `X-Cache: MISS`, and `X-Render-Time-Ms: 9882.35` for `the quick brown fox jumps over the lazy dog`.
  - The returned WAV was 32 kHz mono, `3.071s`, `196,572` PCM bytes, peak `32766`, `0` clipped samples after the output limiter.
  - Repeating the same request returned `X-Cache: HIT` in about `10ms`.
  - A signed panel token saved an `ltd-switch` per-user `panel` voice, and `/api/session` resolved the saved engine back for that user.
  - Final limiter/voice-transform pass: `/render` with `pitch=60`, `speed=55`, `tone=60`, `volume=165` returned HTTP 200, `X-Cache: MISS`, `X-Render-Time-Ms: 10471.15`; the WAV was 32 kHz mono, `2.939s`, peak `32000`, `0` full-scale samples. Repeating it returned `X-Cache: HIT` in about `10ms`.
  - Two different LTD voice profiles for the same text produced different WAV hashes and durations, confirming saved LTD voice parameters now affect output. This is currently a fast post-render transform; in-game LTD voice parameter mapping remains future RE work.
  - Park-mode HTTP proof: local renderer on `127.0.0.1:18082` started with `TTSMODACHI_LTD_APPLIANCE_PARK=true` and `TTSMODACHI_LTD_IDLE_SUSPEND_SECONDS=2`; prewarm completed in `17.65s`, then `/health` showed `warm_paused=true`.
  - An uncached `/render` for `http park renderer proof message` resumed Ryubing once and returned HTTP 200 in `1.677s` wall time. The returned WAV was 32 kHz mono, `2.286s`, peak `32000`, SHA-256 prefix `00e98db7cd344d00`.
  - Repeating the same request returned `x-cache: HIT` in `1.38ms` and did not increment the warm render count. After idle, `/health` again showed `warm_paused=true`, `warm_resume_count=1`, `warm_restart_count=0`, and `ps` reported the Ryubing process as `STAT T`, `0.0% CPU`.
- Idle appliance proof:
  - Local LTD renderer started with `TTSMODACHI_LTD_IDLE_SUSPEND_SECONDS=2`.
  - After prewarm, `/health` showed `warm_paused=true`, `warm_idle_seconds=13.15`, and the Ryubing process was `STAT T` with `0.0% CPU`.
  - An uncached request while paused returned HTTP 200, `X-Cache: MISS`, `X-Render-Time-Ms: 2799.04`; health then showed `warm_resume_count=1`, `warm_restart_count=0`, and the process re-paused.
  - Repeating the same request returned `X-Cache: HIT` in about `10ms` while Ryubing stayed stopped at `0.0% CPU`.
- Host presentation skip experiment:
  - `RYUJINX_TTSMODACHI_NO_PRESENT=true` was added as an opt-in Ryubing debug knob, but it is not enabled by default.
  - With `TTSMODACHI_LTD_NO_PRESENT=true`, LTD prewarm failed to finish and `/render` returned HTTP 500 after timeout, so the reliable appliance profile keeps normal headless presentation and relies on idle suspend for CPU control.
  - A safer `TTSMODACHI_LTD_NO_PRESENT_AFTER_PREWARM=true` variant let prewarm finish and set `warm_no_present=true`, but the next uncached render still timed out with HTTP 500. Presentation remains coupled to guest progress, so both no-present modes stay disabled by default.
  - Retest after parent-step consumer replay: full no-present now reaches ready (`13.554s`) and can render a single short message (`1.260s`), but a three-message burst timed out on the pangram after two successful renders. It remains unsafe as a default.
- Discard-present proof:
  - Full no-present mode was replaced by `RYUJINX_TTSMODACHI_DISCARD_PRESENT`, which still consumes guest frame callbacks but skips texture presentation and buffer swaps.
  - `TTSMODACHI_LTD_DISCARD_PRESENT=true` now defaults on for appliance mode. A warm run prewarmed in `17.434s`, then rendered `the quick brown fox jumps over the lazy dog` in `3.407s` and a second message in `4.516s`; both returned 32 kHz mono WAVs.
  - The dispatch-trace render path no longer depends on the UI text-prep block trace in appliance mode. A reduced block trace run prewarmed in `16.972s`, rendered two messages in `3.422s` and `2.663s`, and confirmed appliance `dispatch,ok` plus direct PCM output.
  - HTTP renderer proof on `127.0.0.1:18086` returned HTTP 200, `X-Cache: MISS`, and `X-Render-Time-Ms: 3014.96` for `http discard present proof message`. The returned WAV was 32 kHz mono, `2.429s`, SHA-256 prefix `3494a4900092841a`.
  - Repeating the same HTTP request returned `X-Cache: HIT`. After idle, `/health` showed `discard_present=true`, `warm_paused=true`, `warm_resume_count=1`, and `warm_restart_count=0`.
- Muted host-sink/direct-PCM proof:
  - Cold render with default appliance profile produced `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/mute-sink-cold.wav`, 32 kHz mono, `1.857s`, peak `26000`, SHA-256 prefix `6487fcc970f02e0d`, cold wall `19.65s`.
  - The cold work dir contained only `appliance.csv`, `appliance.pcm`, `block-trace.csv`, and `ryubing.log`; no DSP `audio.csv` or `audio-dumps` were emitted.
  - Warm render with the same profile prewarmed in `17.876s`, then rendered `mute sink warm one` in `1.690s` and `the quick brown fox jumps over the lazy dog` in `3.654s`. Outputs were 32 kHz mono WAVs with SHA-256 prefixes `13cc07de563b7ad9` and `3a950606ae337276`.
  - HTTP renderer proof on `127.0.0.1:18083` returned HTTP 200, `X-Cache: MISS`, and `X-Render-Time-Ms: 2709.11` for `http muted sink direct pcm proof`. The returned WAV was 32 kHz mono, `2.286s`, peak `32000`, SHA-256 prefix `c98cf7a62c2361a7`.
  - Repeating the same HTTP request returned `X-Cache: HIT` in `0.002s`. After idle, `/health` showed `dsp_trace=false`, `mute_device_sink=true`, `warm_paused=true`, `warm_resume_count=1`, `warm_restart_count=0`, and the Ryubing process was stopped at `0.0% CPU`.
- Final dummy-audio/default proof:
  - Cold render with dummy audio produced `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/dummy-audio-cold.wav`, 32 kHz mono, `2.000s`, peak `26000`, SHA-256 prefix `c03aaffd777946fe`, cold wall `20.66s`.
  - Warm render with dummy audio prewarmed in `18.274s`, then rendered two requests in `1.707s` and `1.699s`. Outputs were 32 kHz mono WAVs with SHA-256 prefixes `afab0b6594169466` and `2151693db27e077e`.
  - Ryubing log confirmed `TTSmodachi dummy audio driver enabled.`
  - HTTP renderer proof on `127.0.0.1:18084` returned HTTP 200, `X-Cache: MISS`, and `X-Render-Time-Ms: 1973.74` for `http dummy audio direct pcm proof`. The returned WAV was 32 kHz mono, `2.357s`, peak `32000`, SHA-256 prefix `046a522adb1962d6`.
  - Repeating the same HTTP request returned `X-Cache: HIT` in `0.0018s`. After idle, `/health` showed `warm_ready=true`, `dsp_trace=false`, `dummy_audio=true`, `mute_device_sink=true`, `warm_paused=true`, `warm_resume_count=1`, `warm_restart_count=0`, and the Ryubing process was stopped at `0.0% CPU` with about `3.8 GiB` RSS.
- Early-dispatch trampoline proof:
  - `TTSMODACHI_LTD_APPLIANCE_DISPATCH_ON_CAPTURE=true` without context restore previously corrupted guest startup. The hook now refuses the unsafe mismatch path unless context restore is enabled.
  - With `TTSMODACHI_LTD_APPLIANCE_DISPATCH_ON_CAPTURE=true` and `TTSMODACHI_LTD_APPLIANCE_CONTEXT_RESTORE=true`, `tools/ltd_render_text.py "early restore dispatch proof"` rendered `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/early-restore-dispatch.wav`, 32 kHz mono, `2.000s`, peak `26000`, SHA-256 prefix `80c6bad69162a91f`. The trace shows dispatch at `main+0x600EFC`, a restore at `main+0x3004`, then PCM only after the later audio path starts.
  - Forcing `TTSMODACHI_LTD_APPLIANCE_CONTEXT_RESUME_ADDR=0x3004` to skip the rest of startup crashed with `InvalidMemoryRegionException` before PCM. That confirms the warm appliance still needs the later title/audio initialization once per process.
- Default early/no-input proof:
  - Early dispatch/context restore and no-input boot are now the default appliance profile.
  - `tools/ltd_warm_render_text.py "early no input dispatch proof" "second early no input proof"` prewarmed in `16.467s`, then rendered in `2.672s` and `2.334s`.
  - The run used no scripted controller/touch boot input and produced two non-silent 32 kHz mono WAVs through the direct PCM tap.
  - Retesting the defaults without explicit early/no-input env overrides prewarmed in `17.284s`, then rendered `default early appliance proof` and `second default early proof` in `2.635s` and `2.485s`. Outputs were 32 kHz mono WAVs with SHA-256 prefixes `f64558c6f11d979d` and `446174ef46491626`.
  - Retesting a fresh worker data dir with `TTSMODACHI_LTD_SEED_DATA_DIR=ltd-work/ryubing-data` prewarmed in `17.927s`, rendered `default early seeded proof` in `2.195s`, and produced a 32 kHz mono WAV with SHA-256 prefix `df226100596b960a`.
- PCM completion proof:
  - A quiet-tail capture experiment rendered correctly but made the pangram slower (`5.178s` render, `4.300s` WAV), so it remains opt-in instead of production default.
  - Restored fast default capture prewarmed in `18.624s`, then rendered `pcm fast default proof` in `2.024s` and `the quick brown fox jumps over the lazy dog` in `3.579s`.
  - The outputs were non-silent 32 kHz mono WAVs, `1.571s`/`3.071s`, with SHA-256 prefixes `c259eed29a5ee980` and `8d02d3beb41a7756`.
- Text trace proof:
  - `appliance.csv` now records `text_sha256` and `text_preview` at each dispatch, read back from the live VoiceText request object.
  - Same-length phrases `aaaaaaaaaaaaaaaaaaaaaa` and `zzzzzzzzzzzzzzzzzzzzzz` dispatched with distinct text hashes `ec7c494df6d2a7ea` and `58bee62c5730617e`, and produced distinct non-silent WAV hashes `c259eed29a5ee980` and `80c2d20892105830`.
  - Local renderer service proof on `127.0.0.1:18088` returned HTTP 200 for `http trace custom text proof` with `X-Cache: MISS`, `X-Render-Time-Ms: 1384.5`, and a 32 kHz mono WAV SHA-256 prefix `30cf23f7226c88d5`; repeating the request returned `X-Cache: HIT`.
  - The service trace for that render recorded text hash `dc1cd935dd239239` and preview `http trace custom text proof`.
- Ready-only startup proof:
  - With `TTSMODACHI_LTD_PREWARM_PRIMER=false`, the worker reached the parked ready loop in `15.302s`, then rendered `ready only first request proof` in `2.965s`.
  - With the same ready-only path plus shader-cache disabled, the worker reached ready in `13.904s`, then rendered `no shader cache proof` in `2.167s`.
  - The shader-cache-disabled output was 32 kHz mono, `1.500s`, peak `26000`, SHA-256 prefix `43816a6ede857587`.
  - Retesting the normal default warm path after making shader-cache disabled by default prewarmed in `17.113s`, then rendered `default shader off proof` in `2.025s`. The output was 32 kHz mono, `1.714s`, peak `26000`, SHA-256 prefix `e4095fcd0d2289fd`, and its dispatch trace recorded preview `default shader off proof`.
  - Ready-only prewarm is now the default warm path. `tools/ltd_warm_render_text.py "ready default no primer proof" "the quick brown fox jumps over the lazy dog"` reported `prewarmed=True` in `14.042s` without rendering the fake primer phrase, then rendered the first real request in `2.963s` and the pangram in `3.580s`.
  - Those default ready-only outputs were 32 kHz mono WAVs, `2.071s`/`3.071s`, peak `26000`, with SHA-256 prefixes `80caa5a8ae767a27` and `cbe146bf242e6634`.
- Readiness-boundary proof:
  - A poll-heavy debug run showed the VoiceText request object and voice context are visible at the early capture site before the parked appliance loop is reached, but dispatching from that point still has to wait for the title/audio consumer path before PCM appears.
  - `is_warm_ready()` now requires `park,waiting-for-text` when `TTSMODACHI_LTD_APPLIANCE_PARK=true`; it no longer treats early capture-site `poll,no-text` debug rows as ready.
  - With `TTSMODACHI_LTD_APPLIANCE_TRACE_POLLS=true`, the fixed readiness check prewarmed in `14.645s`, then rendered `boundary readiness trace fixed` in `2.974s`. The trace reached the parked poll loop, dispatched at `0x8509004`, then saw the first consumer capture at `main+0x465598` about `1.143s` later and direct PCM at `main+0x465714`.
  - Output was a non-silent 32 kHz mono WAV, `2.143s`, peak `26000`, SHA-256 prefix `4d3ed17e6440309b`.
- Primer-prewarm retest:
  - `TTSMODACHI_LTD_PREWARM_PRIMER=true` prewarmed in `17.427s`, then rendered `primer first real user message` in `2.681s` and the pangram in `3.545s`.
  - Outputs were non-silent 32 kHz mono WAVs, `2.143s`/`3.071s`, peak `26000`, with SHA-256 prefixes `0f1fa668c4b5a20a` and `78e396a6067d07d7`.
  - Ready-only prewarm remains the default because the primer adds startup work without a clear first-message latency win on the current profile.
- Consumer/poll tuning retest:
  - Static caller scan with the corrected NSO base found the final consumer copy at NSO `0x8465598` / runtime `main+0x465598`; it has one direct caller at NSO `0x8465430`. The upstream source-ring copy at NSO `0x843F704` / runtime `main+0x43F704` has direct callers at NSO `0x843E674` and `0x87865F4`.
  - String xref scanning found the VoiceText resource selector around NSO `0x880090C` / runtime `main+0x60090C`, with direct caller NSO `0x88000C4`. It references the per-language `VoiceText/tts_single_db(...)` paths and user dictionaries, while nearby xrefs at `main+0x6000B4`, `main+0x6005B0`, `main+0x60074C`, and `main+0x600DAC` touch `VoiceTextMgr` / `VoiceTextSynthesizer`.
  - A narrow LightningJIT block trace over `main+0x60090C` hit once during startup with `x0=0x65f9dbc218`, `x20=0x65f9dbc218`, and return `x30=0x8b060c8`, but the worker did not reach VoiceText ready within `180s`. Treat that block like the broader manager init anchor: useful for static RE, unsafe as a normal live trace target.
  - A second-hop scan over `0x8465430`, `0x843E674`, `0x87865F4`, the request-wrapper callers, and the VoiceText manager caller found no direct `BL` parents. Those paths are reached through indirect scheduler/vtable callbacks or internal blocks, so the remaining no-title bootstrap work needs runtime state reconstruction or targeted indirect-call tracing, not only static xrefs.
  - A consumer-only block-trace run prewarmed in `15.104s`, rendered `consumer indirect caller proof` in `3.121s`, and confirmed the final PCM chain still produces a clean 32 kHz mono WAV. The broader trace that included `main+0x5FFFE8` poisoned startup with `InvalidMemoryRegionException`, so the manager init anchor should stay out of normal block-trace target sets.
  - A narrower entry trace over `main+0x465380` found the indirect parent: `main+0x2ADA74` calls through a vtable into `main+0x465380`, which reaches `main+0x465430 -> main+0x465598 -> main+0x465714`. The parent function starts at `main+0x2AD98C` and has direct callers at NSO `0x82ACA60`, `0x82ACB04`, `0x82ACB80`, `0x82ACD6C`, and `0x852D454`.
  - The Ryubing appliance now saves the full captured consumer argument frame (`x0..x28` and vector regs) before replaying consumer kicks. This keeps the stable default `main+0x465598` replay from depending on incidental live register state.
  - Opt-in replay of the higher-level vtable consumer target works with `TTSMODACHI_LTD_APPLIANCE_CONSUMER_CAPTURE_ADDRS=0x465380` and `TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_ADDR=0x465380`: prewarm `15.127s`, render `1.577s`, 32 kHz mono WAV `1.857s`. A repeat run from the same warm process rendered two requests in `1.400s` and `1.726s`, producing distinct 32 kHz mono WAV hashes. It did not materially beat the current final-copy default, so it stays an experiment rather than the production default.
  - Replay of the parent consumer-step function works with `TTSMODACHI_LTD_APPLIANCE_CONSUMER_CAPTURE_ADDRS=0x2ad98c` and `TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_ADDR=0x2ad98c`: prewarm `15.268s`, repeated warm renders `2.490s` and `1.700s`, producing distinct 32 kHz mono WAV hashes. This stays experimental: later burst tests timed out and logged `Ryujinx.Memory.InvalidMemoryRegionException` on `<AudioFrameworkThread>`.
  - Request-state dumps are now available with `TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_DIR` plus `TTSMODACHI_LTD_APPLIANCE_REQUEST_DUMP_BYTES`. The default dump mode writes one `ready` snapshot and one `dispatch` snapshot; a proof run prewarmed in `14.514s`, rendered `dump once patch proof` in `2.167s`, and produced exactly `2` manifests / `16` binary snapshots. The request object was stable at `0x65F9DBD9D8`, with `text_pointer` at `+0xC0` and `voice_context` at `+0x8E8`.
  - Testing the request function prologue (`TTSMODACHI_LTD_APPLIANCE_REQUEST_ADDR=0x444550`) prewarmed in `14.316s` and dispatched, but emitted no appliance PCM before timeout. The production jump at `main+0x4445CC` is therefore confirmed context-dependent: it uses the captured x21/x22/object-table state from the natural request path, not just `x0=dispatchObject`.
  - Clean default retest after adding the request dump hook, with no debug dumps enabled, prewarmed in `14.853s` and rendered two custom messages in `1.252s` and `2.022s`. Both outputs were 32 kHz mono WAVs, so the dump hook is inert when disabled.
  - `TTSMODACHI_LTD_APPLIANCE_TRACE_REQUEST_REGISTERS=true` now logs the request dispatch register frame, and `tools/ltd_request_registers.py` summarizes those rows. A default parked dispatch trace prewarmed in `14.054s`, rendered `request register trace default` in `2.965s`, and produced a 32 kHz mono WAV (`2.143s`, SHA-256 `4d3ed17e6440309b0c5556309f9f68f826681267eff3fdcd6ac9a717fba0b60a`). The working parked dispatch frame had `x0=0x65f9dbd9d8`, `x1=0x49c7fe1cd0`, `x19=0x65cb09ee10`, `x20=0x49c7fe1cd0`, `x21=0x65cb09ca20`, `x22=0x80000025`, `x29=0x49c7fe10c0`, and `x30=0x8509004`.
  - Opt-in request-context replay (`TTSMODACHI_LTD_APPLIANCE_REQUEST_CONTEXT_REPLAY=true`) is not viable yet. It prewarmed in `14.630s` and reached `dispatch,ok`, but Ryubing raised `InvalidMemoryRegionException` before appliance PCM. The replayed capture-frame registers were materially different from the working parked frame (`x1=0x65fa214d80`, `x19=0x65fa213828`, `x20=0x65fa21e818`, `x21=0x65fa21b7f8`, `x22=0x65fa21d808`), which confirms the capture-site frame cannot be reused as the dispatch-site frame.
  - Opt-in dispatch-context replay can replay the known-good parked dispatch frame for short runs, but it is still unsafe as a default. A two-message proof prewarmed in `14.793s`, rendered in `1.249s` and `0.166s`, and produced distinct non-silent WAVs. A five-message burst then failed on the pangram with `InvalidMemoryRegionException` in the audio framework thread after three successful renders, so `TTSMODACHI_LTD_APPLIANCE_DISPATCH_CONTEXT_REPLAY=false` stays the production default.
  - Clean default retest after the context experiments, with request-context capture and all replay flags off, prewarmed in `14.275s`, then rendered `clean default after context experiments` in `1.249s` and the pangram in `0.175s`. The WAVs were distinct 32 kHz mono files (`2.786s`/`3.071s`, SHA-256 `2ccfb6198bf04094fc8b15466bed0cfef5fb571d9d15ff74a2af079fbf139d0a` and `9ecdceade214b735f4a894f61601b3e537039d05a3ab8bb7cc41770774f34c45`), and the appliance trace recorded the pangram preview/hash at dispatch.
  - Saved guest contexts now include `x31`/SP. This makes trampoline restore more faithful, but it does not make dispatch-frame replay production-safe. A replay burst with SP captured prewarmed in `14.686s`, rendered two messages in `1.258s` and `0.168s`, then timed out on the third request after partial PCM and an `InvalidMemoryRegionException` in the audio framework thread.
  - Clean default retest after SP capture, with dispatch replay still off, prewarmed in `14.674s`, then rendered `clean default after sp capture` in `1.245s` and the pangram in `0.938s`. The WAVs were distinct 32 kHz mono files (`2.143s`/`3.071s`, SHA-256 `4da130b9d171aba034d38a2f5e8811926933222efadb0e92709e66dd863a17fc` and `e44eb278f58a63aca729ffa8146a7ee75757a62fe387fc074d03d9befe18cd6d`).
  - Context tracing is now a separate opt-in hook (`TTSMODACHI_LTD_APPLIANCE_CONTEXT_TRACE_ADDRS`) so constructor frames can be logged without enabling full block tracing. The safe trace set `main+0x5FFFE8,0x600EFC,0x600F04` prewarmed in `13.716s`, rendered in `1.255s`, and produced a valid 32 kHz mono WAV with SHA-256 `9b7413301bae55b288a028f83daa2cae4e6857bd0965510c652706ecf5b3fd76`.
  - The parent init trace over `main+0x5F7554,0x5FF764,0x5FFFE8,0x600EFC` prewarmed in `13.881s`, rendered in `2.493s`, and produced a valid 32 kHz mono WAV with SHA-256 `a11facb53a8c7d0e842b6c766b637749eca797c883e0a3b7afbd5646c379642e`. The smallest confirmed constructor chain is `main+0x5F7554 -> main+0x5FF764 -> main+0x5FFFE8`.
  - `main+0x60090C` is still unsafe even as a one-shot context trace target: it captures the selector frame (`x0=0x65f9dbc218`, `x1=0x49d3f8fb1f`, `x2=0x12`, `x8=0x49d3f8fc38`, `x19=0x65f9dbc178`, `x20=0x65f9dbc218`, `x21=0xaef0a8e`, `x30=0x8b060c8`) but prevents ready prewarm. Keep it out of normal trace runs.
  - The confirmed init strings around this path are `CharaVoiceMgr`, `Mii/VoiceEffectSetting/Default`, `VoicePlayParam/Default`, `VoiceLanguageOffset/Default`, `DefualtVoiceSlot`, `VoiceText/tts_single_db(D32-HIKARI).vtdb2`, and `VoiceTextMgr`. This narrows a true no-title bootstrap to reconstructing the voice manager plus audio queue/consumer setup, not the whole title menu.
  - Clean default retest after adding the context trace hook, with all context trace knobs off, prewarmed in `14.205s` and rendered `clean default after context trace hook` plus the pangram in `3.575s` and `0.176s`. Outputs were distinct 32 kHz mono WAVs (`2.714s`/`3.071s`, SHA-256 `b83e2d8a0048df8fc06ce3eae71f77f53d60acf6d4cbff91e7053b1719da11db` and `95302dff2d5cfd54a9166934bc1d791e066122d8fd5004b6b7a1bd572a307d7f`).
  - `TTSMODACHI_LTD_APPLIANCE_TRACE_CONSUMER_REGISTERS=true` now logs the captured consumer register frame. A parent-step trace rendered in `2.510s` and showed repeated consumer object families such as `x0=0x65f7698a50`, `x19=0x65f7690528`, `x20=0x101`, `x22=0x65f7690608`, with return sites `0x8a33458`, `0x87b2a64`, and trampoline `0x8509004`. Use `tools/ltd_consumer_registers.py` to summarize those captures before the next object-layout pass.
  - `TTSMODACHI_LTD_APPLIANCE_CONSUMER_DUMP_DIR` now dumps selected live consumer objects. A 256-byte dump over `x0,x19,x21,x22` rendered in `2.493s`, produced a valid 32 kHz mono WAV, and wrote `196` small object snapshots under `ltd-work/consumer-object-dump/`. The first `x22` dump starts with pointers back into the `0x65f769...` object family and size/state fields near offsets `0x10`, `0x30`, and `0x70`, which is the next object-layout target for a true bootstrap.
  - A deeper 1 KiB dump of `x19,x22` rendered in `2.499s`, wrote `70` snapshots, and kept valid 32 kHz mono output. `x19` has stable constants at `+0x00=0xb7928e0`, `+0x08=0xb790f90`, `+0x10=0x4000`, float defaults at `+0x90/+0xa8`, and repeated child pointers around `+0x200/+0x208` and `+0x320/+0x328`. `x22` mirrors related child links at `+0x120/+0x128`, `+0x240/+0x248`, and `+0x360/+0x368`, which makes `x19 -> x22 -> child lane` the best current object graph for bootstrap reconstruction.
  - Aggressive final-copy consumer kicking (`TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_MAX=24`, `TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_INTERVAL_MS=0`) prewarmed in `14.089s`, then rendered `consumer aggressive kick one` in `2.794s` and the pangram in `3.586s`. It did not beat the parent-step replay default.
  - Persistent consumer frame replay is available through `TTSMODACHI_LTD_APPLIANCE_CONSUMER_FRAME_FILE`. A normal run saved an `x0..x28` frame for the parent consumer step, prewarmed in `14.984s`, and rendered `consumer frame capture proof` in `2.647s`.
  - Replaying that saved frame in a fresh no-prewarm startup request did not remove the title/audio bootstrap wait. Without after-dispatch chaining, the run rendered in `17.628s`; the loaded frame only kicked when the title naturally hit the later poll loop. With `TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_AFTER_DISPATCH_MAX=8`, replay kicked immediately about `2ms` after request dispatch, but PCM still did not arrive until the real audio runtime populated buffers later; total render was `18.562s`.
  - An early-vs-late dump with `TTSMODACHI_LTD_APPLIANCE_CONSUMER_KICK_AFTER_DISPATCH_MAX=4` showed the same x0/x19/x21/x23/x27 consumer object snapshots for the first early replay and first natural post-replay capture, but the first PCM still appeared only after `67` consumer captures. By the pre-PCM capture, ring/buffer fields had changed materially: x19 `+0x10/+0x20` became `0x4000`, x19 `+0x38` became a live pointer, x19 `+0xe0/+0xe8` moved to populated lane pointers, and x0 gained multiple buffer pointers under `+0x10..+0xc0`. Verdict: a saved call frame is not enough; a true no-title bootstrap must recreate the audio queue/ring-buffer initialization as well.
  - `TTSMODACHI_LTD_APPLIANCE_MEMORY_PATCH_FILE` is now available as an opt-in RE hook that writes captured object snapshots back into guest memory. A cold/no-prewarm run applied `158` captured queue/ring snapshots `33ms` after dispatch and kicked the saved consumer frame `35ms` after dispatch, but first PCM still arrived `11.865s` after dispatch and total wall time was `19.15s`. Verdict: captured object bytes are also insufficient; the missing dependency is live title/audio renderer scheduling state, not only heap object contents.
  - Static disassembly of the object writers confirms the queue/ring constructor cluster around `main+0x651D24`. The nested lane constructor at `main+0x651EE8` writes the x19-family fields, while the parent setup allocates/zeros the ring backing memory and calls SDK helpers from the `main+0x651D90` path. This narrows the next no-title attempt to calling or reimplementing that initialization path, then scheduling the audio consumer, instead of replaying only saved frames or snapshots.
  - A targeted safe context trace over `main+0x651D24,0x651D34,0x651E34,0x651EE8,0x6520C8` prewarmed in `13.848s`, rendered `constructor context trace proof` in `1.275s`, and produced a 32 kHz mono WAV (`2.214s`, SHA-256 `3f8e4edf22e783929f627c57d19a04d7ac9cc444898185f6880e889e83ae1e6a`). It confirmed `main+0x650BC0 -> main+0x651D24`, with the parent frame passing `x0=0x65f7690018`, `x2=0x65f74066b0`, `x3=0x60`, and the lane constructor using `x0=0x65f7690528`, `x1=0x6c08`, `x2=0x20`. Verdict: these frames are stable and trace-safe, but the caller allocates and wires a broader audio object graph around the constructor.
  - Context dumps are now available with `TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_DIR`, `TTSMODACHI_LTD_APPLIANCE_CONTEXT_DUMP_BYTES`, and `tools/ltd_context_dump_summary.py`. The hook dumps selected register-pointed objects for context trace hits and stays inert when the directory/byte count are unset.
  - The LightningJIT appliance hook now also handles direct/indirect call instructions that sit on block boundaries. A proof trace over `main+0x6509E4,0x650BC0,0x650D90,0x650DA8,0x651D24` prewarmed in `15.155s`, rendered `callsite dump proof` in `1.253s`, and produced a valid 32 kHz mono WAV (`1.357s`, SHA-256 `eadd372ab948dc40dfe61f3213546e788e65e41a39043451b09aa6d82ebeb76c`).
  - That callsite dump confirms the smaller audio-runtime parent chain: `main+0x649B9C -> main+0x6509E4`, then the audio object graph calls `main+0x650BC0 -> main+0x651D24`, followed by virtual calls at `main+0x650D90` and `main+0x650DA8` to targets `main+0x5FEAF8` and `main+0x3352B8`. The next true no-title attempt should target this `main+0x649B9C..0x649C0C` cluster instead of only the lower queue constructor.
  - Clean default retest after the callsite hook, with context dump disabled, prewarmed in `14.490s`, then rendered `clean default after callsite hook` and the pangram in `1.261s` and `0.176s`. Outputs were valid 32 kHz mono WAVs (`2.357s`/`3.071s`, SHA-256 `2130fb7e0dd794648445257eec3f266b8e99176d4c6520425ea5b452783588e8` and `d008b82dca130711135bef3788203db22212d3a764faf5285504b11113a4187c`).
  - Clean default retest after adding the consumer-frame hook, with frame replay disabled, prewarmed in `13.413s`, then rendered `clean default after consumer frame hook` and the pangram in `1.237s` and `1.726s`. Outputs were distinct non-silent 32 kHz mono WAVs with SHA-256 `2ccfb6198bf04094fc8b15466bed0cfef5fb571d9d15ff74a2af079fbf139d0a` and `ec8ba127be9a060e72e18b84495f79875d11921dbca86307ae76ea995bcc9873`.
  - Lowering the parked poll interval to `TTSMODACHI_LTD_APPLIANCE_PARK_POLL_MS=1` prewarmed in `15.561s`, then rendered `park poll one millisecond proof` in `3.112s` and the pangram in `3.588s`. The default `25ms` poll remains better.
  - These retests point at actual PCM production/full-output capture as the dominant warm latency after the first fast replay burst, not host polling.
- Tiny window / low-DPI presentation:
  - Ryubing headless still created a Retina-sized Vulkan swapchain by default (`2560x1440`, scale `2.0`) even when appliance mode discarded presentation.
  - `TTSMODACHI_LTD_WINDOW_WIDTH=320`, `TTSMODACHI_LTD_WINDOW_HEIGHT=180`, and `TTSMODACHI_LTD_LOW_DPI_WINDOW=true` now default on for LTD appliance workers. A proof run created a `320x180` swapchain at scale `1.0`, prewarmed in `15.422s`, rendered `tiny window proof` in `1.882s`, and rendered the pangram in `0.175s`.
  - The outputs were valid 32 kHz mono WAVs (`1.214s` and `3.071s`) with SHA-256 `f5d53bc7bc21dbc0b214d167ef52b81df79a0881f3c967ba8a08ec2f13e96961` and `23766b04a4cea2d5e035c48ecc967cfe5612b5e7f204e15da061e7b21743d913`.
- Host park backoff:
  - The Ryubing appliance now exposes the parked TTS wait state to the headless host loops. While the guest is waiting for text, the render/input loops sleep for `TTSMODACHI_LTD_APPLIANCE_HOST_PARK_SLEEP_MS` (`8ms` default) instead of spinning normal frame work.
  - A proof run with host park sleep enabled prewarmed in `14.874s`, showed local parked process CPU around `14.5%` before SIGSTOP, then rendered `host park proof one` in `1.272s` and the pangram in `0.176s`. Both outputs were valid 32 kHz mono WAVs with SHA-256 `eadd372ab948dc40dfe61f3213546e788e65e41a39043451b09aa6d82ebeb76c` and `c27b43ca899379e7521042ab8ac077850d057d9958912b5032de08b7373313a2`.
  - A matched local baseline with `TTSMODACHI_LTD_APPLIANCE_HOST_PARK_SLEEP_MS=0` prewarmed in `14.944s` and showed parked process CPU around `29.2%`, so the host backoff cuts pre-SIGSTOP parked CPU roughly in half without affecting text-in/audio-out.
- Post-trampoline stable proof:
  - Default cold render produced `/Users/cole/Documents/New project 8/ltd-work/ltd-renderer-proof/default-stable-after-trampoline.wav`, 32 kHz mono, `3.071s`, peak `26000`, SHA-256 prefix `18bb41df48948255`.
  - Default warm render prewarmed in `17.587s`, then rendered `warm trampoline one` in `1.547s` and `the quick brown fox jumps over the lazy dog` in `3.583s`. Outputs were 32 kHz mono WAVs with SHA-256 prefixes `ead0f35f2ce49657` and `ad6175a8b27c62b0`.
- Renderer-service fast-profile proof:
  - Running `ttsmodachi_bot.renderer_service` with `TTSMODACHI_WORKER_ROMS=LTD` prewarmed the warm worker in `13.27s`; `/health` reported the then-experimental parent replay (`consumer_capture_addrs=0x2ad98c`, `consumer_kick_addr=0x2ad98c`, `appliance_consumer_kick_max=64`) and `warm_ready=true`.
  - `/render` for `http default fast profile one` returned HTTP 200, `X-Cache: MISS`, `X-Render-Time-Ms: 1354.02`, and a 32 kHz mono WAV. A second uncached request returned `X-Render-Time-Ms: 275.43`, and repeating the first text returned `X-Cache: HIT`.
  - After 12s idle, `/health` reported `warm_paused=true`, confirming the idle suspend governor still works with the parent replay default.
- Coah x64 staging proof:
  - The x64 Ryubing appliance hook has separate ARMeilleure and LightningJIT callback paths. LightningJIT keeps its unmanaged bridge; ARMeilleure uses a managed callback because managed `UnmanagedCallersOnly` calls crash when this hook is emitted directly.
  - `HostMappedUnsafe`/`HostMapped` still abort during x64 CPU memory-manager startup on the current Docker/.NET 10 build, before any LTD hook runs, so coah staging intentionally stays on `SoftwarePageTable`.
  - The stable coah profile uses direct Xvfb, `SoftwarePageTable`, `main+0x3004` parking, no consumer replay, dummy audio, muted sink, and direct PCM capture at `main+0x465714`.
  - Baseline coah API proof on port `18082`: prewarm `103.84s`, first uncached pangram render `12.825s`, 32 kHz mono WAV, cache hit immediate, paused idle CPU around `0.1%`, RSS around `7.9GiB`.
  - Fast `main+0x927c` parking reached ready in `16.972s`, but first PCM did not arrive until `97.888s`; it is not a production profile.
  - Parent consumer replay at `main+0x2AD98C` can speed one request, but corrupts later dispatches on coah x64; keep it disabled there.
  - Primer prewarm is now the coah default: it pays the first synthesis at startup (`111.653s` in the proof run), then real user renders took `2.380s` and `4.577s`. This is the safest current latency win for Discord traffic.
  - Quiet-tail PCM capture produced longer, less aggressively trimmed files but raised render time to `5.237s` and `7.321s`, so it remains an opt-in debug/quality mode instead of default.
  - Bootstrap frame capture at `main+0x649B9C` works and saved the expected parent/audio-runtime register frame (`x0=0x65f7406600`, `x19=0x65f4bbd848`, `x20=0x65f4bbd598`, `x22=0x65f4bc4a80`). That capture run rendered valid TTS, but only after the normal title path reached the audio init point.
  - Replaying the saved `main+0x649B9C` frame from a fresh cold request is not viable. With block trace disabled, replay logged at `main+0x3004`, then produced no appliance PCM and timed out after `95.74s`; `BOOTSTRAP_RETURN_MODE=saved` also timed out after `102.68s`. Triggering from `main+0x927C` hit the same ARMeilleure managed-call crash path before appliance trace output.
  - Cold appliance mode now defaults `TTSMODACHI_LTD_APPLIANCE_BLOCK_TRACE_ADDRS` to empty, matching warm/prod. Enable it only for targeted trace runs; it is not part of the render path.
  - Verdict for no-title bootstrap: a saved guest register frame is insufficient. The missing dependency is live parent object graph plus audio queue/renderer scheduling state, not merely the `END of LOADTTS` callsite registers.

Performance note:

- LightningJIT with `HostMappedUnsafe` is the current performance path on supported hosts and reaches/captures PCM quickly.
- Coah x64 currently cannot use that profile reliably; its safe staging profile is `SoftwarePageTable` plus primer prewarm.
- Hypervisor is still disabled because the hook cannot run inside the Apple Hypervisor engine.
- ARMeilleure/software-page-table mode is primarily for broad tracing and x64 fallback; it is much slower than the mapped-memory path.

## Next reverse-engineering pass

1. Extract PFS0 metadata locally into `ltd-work/metadata`.
2. Use the base program NCA `2e88713715d1d950ece6ce679a2fd456.nca`; it contains `main`, `sdk`, `rtld`, and `main.npdm` in ExeFS.
3. Start from the current string anchors found in `main`: `VoiceSynthesis`, `END of LOADTTS`, `VoiceText/us`, `engttsdict_emb`, `/tts_single_db(D32-GLORIA).vtdb2`, `/tts_single_db(D32-CHLOE).vtdb2`, and the `pcm/` database paths.
   - Static call-site scan found direct wrappers for each `END of LOADTTS` resource lane: `0x8FD0210 -> 0x8FCF710`, `0x909FE10 -> 0x909F270`, `0x910F580 -> 0x910EA00`, `0x9165F90 -> 0x9165410`, `0x91C2010 -> 0x91C1480`, `0x9231280 -> 0x9230700`, `0x9287430 -> 0x92868B0`, `0x93098B0 -> 0x9308D30`, `0x9384080 -> 0x9383500`, `0x93EB800 -> 0x93EAC80`, `0x9452F10 -> 0x9452360`, `0x94BB210 -> 0x94BA660`, and `0x951C330 -> 0x951B790`.
   - The `0x8FCF710` resource loader path and `main+0x60090C` path selector build VoiceText database/path state and are now the best static candidates for a future no-title bootstrap, but calling the request wrapper before the normal audio consumer exists still does not produce PCM.
4. Use `tools/ltd_trace_correlate.py` output and `tools/ltd_memory_trace_summary.py` to inspect pre-audio relative addresses and memory producer/copy chains.
5. Replace the natural UI trigger with a direct post-`END of LOADTTS` call path or package an ExeFS patch that jumps into a minimal TTS loop after the audio renderer and VoiceText queue consumer are initialized. Early request-wrapper dispatch and saved bootstrap-frame replay are both insufficient; the next target is reconstructing the parent object graph around `main+0x649B9C -> main+0x6509E4` and the queue init at `main+0x650BC0 -> main+0x651D24`.
6. Identify the voice parameter struct next to the `main+0x444660` request object and map pitch/speed/quality/tone/accent/intonation.
7. Benchmark warm render latency after moving from natural preview trigger to direct minimal trigger.
