# TTSmodachi

okay so this is TTSmodachi.

it is a Discord TTS bot that talks through the Tomodachi Life / Talkmodachi 3DS voice renderer. you run the Discord bot, a renderer service, and a patched Citra worker pool. people type in a configured text channel and the bot reads it in voice chat with goofy Tomodachi voices.

this repo does not include ROMs, keys, Discord tokens, databases, logs, or my hosted bot config. bring your own legally dumped game files.

## what you get

- Discord slash commands like `/setup`, `/join`, `/leave`, `/skip`, `/voice`, `/voices`, `/replace`, and `/settings`
- a warm renderer service so Citra is not booting for every message
- SQLite storage for server settings, user voices, linked dashboard accounts, and voice targets
- a web voice panel for changing pitch, speed, quality, tone, accent, intonation, language, and volume
- optional second bot support for another voice channel in the same server
- Docker Compose setup for the bot, optional bot2, and renderer worker
- cache pruning so repeated messages can play faster

## before you start

you need:

- Docker Desktop on Windows, or Docker Engine on Linux
- Git
- a Discord application with a bot user
- Message Content Intent enabled for the bot in the Discord Developer Portal
- a legally dumped Tomodachi Life CXI that you patch yourself
- enough CPU for Citra workers. start with 1 worker if you are not sure

do not upload ROMs to GitHub. keep them in `roms/` only.

## make the Discord bot

1. go to the Discord Developer Portal
2. create a new application
3. open Bot, then add a bot
4. copy the bot token
5. enable Message Content Intent
6. open OAuth2, copy the Client ID
7. keep the token private. if it ever gets posted somewhere, reset it

the default permission integer in `.env.example` is `36785216`. that is what this setup uses for the invite URL.

## get the files

```sh
git clone https://github.com/coah80/ttsmodachi.git
cd ttsmodachi
cp .env.example .env
```

on Windows PowerShell, use:

```powershell
Copy-Item .env.example .env
```

now edit `.env`.

minimum local test values:

```env
DISCORD_TOKEN=your_discord_bot_token_here
TTSMODACHI_BOT_CLIENT_ID=your_discord_application_client_id_here
TTSMODACHI_PANEL_URL=http://127.0.0.1:18080
TTSMODACHI_WORKER_ROMS=US
TTSMODACHI_US_WORKERS=1
TTSMODACHI_MAX_INFLIGHT_RENDERS=4
TTSMODACHI_BOT_RENDER_CONCURRENCY=2
```

for a public host, change these:

```env
TTSMODACHI_PANEL_URL=https://your-domain.example
TTSMODACHI_PUBLIC_HOSTS=your-domain.example
TTSMODACHI_PANEL_SIGNING_KEY=put-a-long-random-string-here
TTSMODACHI_SUPPORT_INVITE_URL=https://discord.gg/your-support-server
```

you can make a signing key with:

```sh
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## patch your ROM

this part is the least friendly part, sorry.

you need a legal Tomodachi Life dump as a CXI. the renderer expects patched files named like this:

```text
roms/US.cxi
roms/EU.cxi
roms/JP.cxi
roms/KR.cxi
```

only put the regions you are actually using in `.env`. for example:

```env
TTSMODACHI_WORKER_ROMS=US
TTSMODACHI_US_WORKERS=1
```

the original Talkmodachi patch flow is:

1. extract `code.bin` and `exheader.bin` from your CXI with `3dstool`
2. if `code.bin` is compressed, decompress it
3. put `code.bin` and `exheader.bin` in `gamePatch/`
4. build the patch with Magikoopa
5. put the patched files back into the extracted CXI contents
6. rebuild the CXI
7. put the final patched CXI in `roms/`

example `3dstool` commands, using a US dump:

```sh
3dstool -xvtf cxi ./TomodachiLife.cxi --header header --exefs exefs --exh exheader.bin --logo logo --plain plain --romfs romfs
3dstool -xvtf exefs ./exefs --exefs-dir exefsd --header exfsheader
3dstool -u --file ./exefsd/code.bin --compress-type blz --compress-out ./exefsd/code_unc.bin
mv ./exefsd/code_unc.bin ./exefsd/code.bin
```

after patching with Magikoopa:

```sh
3dstool -cvtf exefs ./exefs --exefs-dir exefsd --header exfsheader
3dstool -cvtf cxi ./US.cxi --header header --exefs exefs --exh exheader.bin --logo logo --plain plain --romfs romfs --not-encrypt
mkdir -p roms
mv ./US.cxi ./roms/US.cxi
```

tools you probably need:

- `3dstool`: https://github.com/dnasdw/3dstool
- Magikoopa: https://github.com/RicBent/Magikoopa
- GodMode9 on your own 3DS for dumping your own game

## run it

build and start the normal one-bot setup:

```sh
docker compose up --build
```

or run it in the background:

```sh
docker compose up --build -d
docker compose logs -f tts-worker bot
```

open the panel locally:

```text
http://127.0.0.1:18080
```

check renderer health:

```sh
curl http://127.0.0.1:18080/health
```

if you also want the second bot container:

```sh
docker compose --profile bot2 up --build -d
```

then set `DISCORD_TOKEN_2` and `TTSMODACHI_SECOND_BOT_CLIENT_ID` in `.env`.

## invite it

when the renderer is up, visit:

```text
http://127.0.0.1:18080
```

if `TTSMODACHI_BOT_CLIENT_ID` is set, the page can generate an invite link. you can also build one yourself:

```text
https://discord.com/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=36785216&scope=bot%20applications.commands
```

inside Discord:

1. run `/setup #your-tts-text-channel`
2. join a voice channel
3. run `/join`
4. type in the setup channel
5. use `/voice` to open your personal voice dashboard

## useful commands

- `/setup #channel` sets the channel the bot reads
- `/join` joins your current voice channel
- `/leave` leaves voice
- `/skip` clears queued TTS and stops current playback
- `/settings` shows current server settings
- `/voice` opens the signed voice dashboard link
- `/unlink` removes your dashboard link and panel voice preset
- `/voices list` shows built-in and saved voices
- `/voices save` saves a custom voice
- `/voices use` selects your voice
- `/voices default` sets the server default
- `/replace add/remove/list/clear` manages pronunciation replacements

text shortcuts also exist:

- `-skip` skips the current playback
- `-message here` skips your own message from TTS

## tuning

start small:

```env
TTSMODACHI_US_WORKERS=1
TTSMODACHI_MAX_INFLIGHT_RENDERS=4
TTSMODACHI_BOT_RENDER_CONCURRENCY=2
```

if your CPU has room, raise workers later. each worker is a warm Citra instance. more workers can make latency worse if the machine is already out of CPU.

the defaults in `.env.example` are intentionally small. once it works, raise workers and concurrency slowly.

## public hosting notes

keep the renderer bound to localhost unless you know what you are doing:

```env
RENDERER_BIND=127.0.0.1
```

if you put a reverse proxy in front of it, set:

```env
TTSMODACHI_PANEL_URL=https://your-domain.example
TTSMODACHI_PUBLIC_HOSTS=your-domain.example
TTSMODACHI_PANEL_SIGNING_KEY=long-random-string
TTSMODACHI_PANEL_TOKEN=another-long-random-string
```

`TTSMODACHI_PANEL_TOKEN` locks public `/render` and `/api/config` requests. internal Docker calls from the Discord bot still work without sending that token.

## things that should never go in git

- `.env`
- Discord bot tokens
- panel signing keys
- patched or unpatched ROMs
- save files, databases, and logs
- SSH keys
- server IPs or private deploy notes

`.gitignore` and `.dockerignore` try to help, but still check before pushing.

## credits

this is based on:

- Talkmodachi by dylanpdx: https://github.com/dylanpdx/talkmodachi
- Discord-TTS/Bot: https://github.com/Discord-TTS/Bot

Talkmodachi is the reason the Tomodachi Life renderer part exists. Discord-TTS/Bot inspired a lot of the Discord bot shape and command ideas.

## license

there is no new license file in this repo right now because the upstream Talkmodachi repo does not publish a license file at the time this README was written. check the upstream projects before redistributing modified copies or using this for anything serious.
