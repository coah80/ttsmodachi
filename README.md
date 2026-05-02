# TTSModachi

Discord-first Tomodachi Life TTS using the Talkmodachi patched Citra renderer.

TTSModachi keeps the original Talkmodachi engine work and turns it into a server bot: admins run `/setup`, someone runs `/join`, then normal messages in the configured channel are spoken with Tomodachi-style voices.

## What Changed

- Discord bot UX inspired by Discord-TTS/Bot: `/setup`, `/join`, `/leave`, `/skip`, `/settings`, `/set ...`, `/replace ...`, and `/voice ...`.
- Warm renderer service instead of per-request Citra startup.
- File cache keyed by text, voice params, language, mode, and engine version, with duplicate in-flight renders collapsed.
- SQLite storage for guild settings and user/guild voice presets.
- Louder WAV output through a cached per-voice volume parameter.
- Renderer-hosted voice panel with sliders, built-in presets, test playback, and bounded sample-pack generation.
- Experimental `ltd-switch` engine for Tomodachi Life: Living the Dream using a patched headless Ryubing appliance path.
- Isolated warm Citra workers with fixed UDP ports, native-resolution software rendering, dummy SDL audio/video, timeout restart, idle suspend/resume, and lower idle CPU in the game patch wait loop.
- Direct WAV wrapping for raw PCM instead of `pydub`.

## Local Run

1. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.
2. Put patched ROMs in `roms/`, starting with `roms/US.cxi`.
3. Run `docker compose up --build`.

The renderer exposes health on the host at `http://127.0.0.1:18080/health` by default, including Citra PID, paused state, idle seconds, last render timing, resume count, and restart count. Override `RENDERER_HOST_PORT` if that port is already in use.

## Voice Panel

The renderer serves a voice panel at `/`. Set `TTSMODACHI_PUBLIC_HOSTS=tomo.coah80.com` and `TTSMODACHI_PANEL_SIGNING_KEY` when exposing it publicly. `/voice` sends a private signed link for that Discord user; clicking Save in the panel writes the global per-user `panel` voice preset and selects it for that user across servers. Add `TTSMODACHI_PANEL_TOKEN` if you also want public `/render` and `/api/config` requests locked down while internal Docker calls from the Discord bot stay token-free.

The panel includes sliders for `pitch`, `speed`, `quality`, `tone`, `accent`, `intonation`, `lang`, and `volume`. The sample-pack button renders a capped preset/matrix set, and `TTSMODACHI_CACHE_MAX_BYTES` bounds the WAV cache.

## Living the Dream

`ltd-switch` is experimental but locally verified: it starts a warm patched Ryubing process, dispatches text directly into the LTD VoiceText request path, taps the generated PCM before game output mixing, and returns voice-only WAV. Appliance mode disables scripted controller/touch input by default, dispatches at the early VoiceText capture point with context restore, replays the stable final-copy audio consumer path for warm requests, disables DSP trace/dump files, disables shader-cache loading, uses Ryubing's dummy audio driver, mutes the host audio sink, uses a tiny low-DPI window, and discards presented frames after guest acquire/release callbacks, so Ryubing is only used to advance the VoiceText path and capture direct PCM. The default warm prewarm renders one primer phrase, so the first real Discord request avoids the initial synthesis setup cost, then idles with `SIGSTOP`/`SIGCONT` so the process stays warm in memory without burning CPU between uncached requests. LTD still needs the title/audio initialization once per warm worker; strict extracted standalone VoiceText is not complete. It does not commit or ship game files, keys, firmware, or Ryubing binaries.

Set `TTSMODACHI_WORKER_ROMS=LTD`, `TTSMODACHI_LTD_ENABLED=true`, `TTSMODACHI_LTD_GAME_PATH`, and `TTSMODACHI_LTD_RYUBING_PATH` to test it through `/render` or the voice panel engine selector. For fresh worker data dirs, set `TTSMODACHI_LTD_SEED_DATA_DIR` to a private prepared Ryubing root-data-dir with firmware, profiles, and a minimal LTD save/Mii context; the worker copies it before booting. Voice sliders are persisted with the engine choice; LTD pitch/speed/tone currently use a fast post-render transform while native in-game parameter mapping remains future work.

For isolated LTD staging, put private assets under `ltd/game` and `ltd/seed`, then run:

```sh
docker compose -f docker-compose.yml -f docker-compose.ltd.yml up -d --build tts-worker
```

## Commands

- `/setup #channel` sets the text channel to read from.
- `/join` joins your current voice channel.
- `/leave` leaves voice.
- `/skip` clears queued TTS and stops current playback.
- `/settings` shows current server settings.
- `/set autojoin` controls whether messages can make the bot join automatically. It is off by default.
- `/set say_name` controls whether messages are prefixed with the speaker name.
- `/set say_emoji` and `/set skip_emoji` control emoji pronunciation.
- `/set required_prefix`, `/set required_role`, `/set message_length`, `/set repeated_characters`, `/set text_in_voice`, `/set bot_ignore`, and `/set require_same_vc` mirror the common Discord-TTS/Bot server settings.
- `/set nickname` changes the spoken name used for a user.
- `/replace add/remove/list/clear` manages server pronunciation replacements before TTS.
- `/voice` opens the signed web voice panel.
- `/voices list` lists built-in and saved voices.
- `/voices save` saves a custom voice from TTSModachi parameters, including volume.
- `/voices use` selects your voice.
- `/voices default` sets the server default.
- `/voices current` shows your selected voice.
- `/voices random` picks a random built-in voice.
- `/voices delete` deletes one of your custom voices.

## Upstream Credit

This project is a Discord-first fork based on Talkmodachi by dylanpdx: https://github.com/dylanpdx/talkmodachi

Talkmodachi uses a patched Tomodachi Life build and custom Citra fork to render speech. You need legally obtained and patched CXI files for the regions you enable.
