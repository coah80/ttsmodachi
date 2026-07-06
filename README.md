# TTSmodachi

okay so this is TTSmodachi.

it is a Discord TTS bot that talks through the Tomodachi Life / Talkmodachi 3DS voice renderer. you run the Discord bot, a renderer service, and a patched Citra worker pool. people type in the voice channel chat, or a text channel you pick with `/channel`, and the bot reads it out loud with goofy Tomodachi voices.

this repo does not include ROMs, bring your own legally dumped game files.

## what you get

- Discord slash commands like `/join`, `/leave`, `/channel`, `/skip`, `/voice`, `/voices`, `/replace`, and `/settings`
- a warm renderer service so Citra is not booting for every message
- SQLite storage for server settings, user voices, linked dashboard accounts, and voice targets
- a web voice panel for changing pitch, speed, quality, tone, accent, intonation, language, and volume
- optional StreamElements bit alerts through existing AlertBox custom code
- optional hosted Twitch bits overlay at `stream.coah80.com`
- optional second bot support for another voice channel in the same server
- Docker Compose setup for the bot, optional bot2, and renderer worker
- cache pruning so repeated messages can play faster

## before you start

to self-host the Discord bot, renderer, or alert service, you need:

- Docker Desktop on Windows, or Docker Engine on Linux
- Git
- a Discord application with a bot user
- Message Content Intent enabled for the bot in the Discord Developer Portal
- a legally dumped Tomodachi Life CXI
- enough CPU for Citra workers. start with 1 worker if you are not sure

the StreamElements streamer install does not need Docker. they only need the generated AlertBox custom code if you host the alert service for them.

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
DISCORD_TOKEN=replace_me
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
TTSMODACHI_PANEL_SIGNING_KEY=replace_me
TTSMODACHI_SUPPORT_INVITE_URL=https://discord.gg/your-support-server
```

you can make a signing key with:

```sh
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## patch your ROM

this part is the least friendly part, sorry. there is a tool way now, and then the manual way if the tool is annoying on your setup.

### where the game dump comes from

you dump your own copy of Tomodachi Life from your own 3DS with custom firmware (Luma3DS + GodMode9). if your 3DS is not modded yet, follow https://3ds.hacks.guide first.

- physical cartridge: in GodMode9, open the gamecart, use `NCSD image options` > `Decrypt & extract` (or dump the cart as a decrypted `.3ds`)
- digital / eShop copy: in GodMode9, find the installed title and dump it decrypted. a `.cia`, or the extracted `.app` content, both work
- already have a dump on your PC: `.cxi`, `.app`, `.3ds`/`.cci`, and decrypted `.cia` are all accepted by the patch tool below, it unwraps them itself

the one thing that does not work is an **encrypted** dump. if the tool complains about encryption, re-dump with GodMode9 using a decrypt option.

the renderer expects patched files named like this:

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

### tool way

you still need `3dstool` and Magikoopa installed (`ctrtool` too if your input is a `.cia`). the helper does the extract and rebuild steps, then pauses while you run the Magikoopa patch step.

from the repo folder, with any accepted format:

```sh
python tools/patch_rom.py --input ./TomodachiLife.cxi --region US
python tools/patch_rom.py --input ./TomodachiLife.3ds --region US
python tools/patch_rom.py --input ./TomodachiLife.cia --region US
```

on Windows, if `python` is not on PATH:

```powershell
py -3 tools\patch_rom.py --input C:\path\to\TomodachiLife.cxi --region US
```

if `3dstool` is not on PATH:

```sh
python tools/patch_rom.py --input ./TomodachiLife.cxi --region US --three-dstool /path/to/3dstool
```

if you want the helper to launch Magikoopa for you:

```sh
python tools/patch_rom.py --input ./TomodachiLife.cxi --region US --magikoopa /path/to/Magikoopa
```

what the tool does:

1. extracts the CXI into `.rom-patch-work/`
2. extracts ExeFS and tries to decompress `code.bin`
3. stages a Magikoopa working folder at `.rom-patch-work/gamePatch/`
4. waits for you to press Make and Insert in Magikoopa
5. rebuilds the CXI into `roms/US.cxi`

if Magikoopa is easier to run manually, start with:

```sh
python tools/patch_rom.py --input ./TomodachiLife.cxi --region US --prepare-only
```

open `.rom-patch-work/gamePatch/` in Magikoopa, press Make and Insert, then run the resume command the tool prints.

### manual way

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
- `ctrtool` (only for `.cia` input): https://github.com/3DSGuy/Project_CTR/releases
- Magikoopa: https://github.com/RicBent/Magikoopa
- GodMode9 on your own 3DS for dumping your own game: https://github.com/d0k3/GodMode9

## run it

build and start the normal one-bot setup:

```sh
docker compose up --build
```

the first build compiles the patched Citra from source, so it can take a long while (10 to 30+ minutes depending on CPU). later builds reuse the cached Citra layer and are fast.

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

## StreamElements bit alerts

the easiest streamer install is hosted: you run the TTSmodachi alert service, then give the streamer finished StreamElements AlertBox custom code.

generate the AlertBox code from your hosted alerts URL:

```powershell
.\make-alertbox-tts.bat -BaseUrl https://your-alerts-domain.example -InstallId streamer-name
```

for the hosted `stream.coah80.com` setup:

```powershell
.\make-alertbox-tts.bat -BaseUrl https://stream.coah80.com -InstallId streamer-name
```

the streamer appends the generated HTML and JS to the Twitch bits/cheer alert in their existing StreamElements AlertBox. StreamElements keeps the alert queue, normal alert sound, visuals, and OBS overlay; TTSmodachi only renders and plays the Tomodachi voice. no OBS plugin, no DLL, no Docker on their computer.

for local developer testing, start the alert companion:

```sh
docker compose --profile alerts up --build tts-worker alerts
```

or on Windows:

```powershell
.\start-alerts.bat
```

if Windows says `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`, Docker Desktop is not running. open Docker Desktop, wait for it to fully start, then run `.\start-alerts.bat` again.

open the setup page:

```text
http://127.0.0.1:18081/setup
```

append the generated HTML and JS to the StreamElements AlertBox custom code for Twitch bits/cheers. the fallback Custom Widget path is still available with `.\make-streamer-widget.bat` if editing the existing AlertBox is annoying. see `docs/alerts.md` for hosted and local setup details.

## Twitch bits OBS audio source

for the easiest streamer setup, host the stream service and let the streamer add one OBS Browser Source:

```sh
docker compose --profile stream up --build -d tts-worker stream
```

set these in `.env` first:

```env
TWITCH_CLIENT_ID=your_twitch_app_client_id
TWITCH_CLIENT_SECRET=your_twitch_app_client_secret
TTSMODACHI_STREAM_PUBLIC_BASE_URL=https://your-stream-domain.example
TTSMODACHI_STREAM_COOKIE_SECRET=replace_me
```

local setup page (or your public domain if you put a reverse proxy in front):

```text
http://127.0.0.1:18120
```

the streamer logs in with Twitch, copies their private browser source URL, adds it in OBS, and mutes only their existing alert TTS. random mode picks a different audible voice per bit message. speech is queued FIFO, so simultaneous bits are read one at a time. see `docs/stream.md`.

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

1. join a voice channel
2. run `/join`
3. type in that voice channel's built-in chat, or run `/channel #some-channel` to pick a normal text channel
4. use `/voice` to open your personal voice dashboard

## useful commands

- `/join` joins your current voice channel
- `/leave` leaves voice
- `/channel` sets the text channel the bot reads into the voice channel it is joined in
- `/skip` clears queued TTS and stops current playback
- `/settings` shows current server settings
- `/set read_non_vc_messages true` reads voice-channel chat from people not in that voice channel
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

`/channel #some-channel` sets a normal text channel for TTS. messages sent there get read into the voice channel TTSmodachi is currently joined in. run `/channel` with no channel to clear it and go back to just voice channel chat.

`/set bot_ignore false` lets other bots and webhooks get read from the current voice channel chat or configured `/channel` text channel too, including embed-only messages. Automated messages do not need a prefix or required role once you opt in. TTSmodachi still needs to already be in voice, because bots and webhooks do not tell it which voice channel to join.

`/set read_non_vc_messages true` is off by default. when it is on, people who are not in voice can type in a voice channel's built-in chat and be read in that same voice channel. it still needs `text_in_voice` on, and it does not make TTSmodachi read the rest of the server.

## tuning

start small:

```env
TTSMODACHI_US_WORKERS=1
TTSMODACHI_MAX_INFLIGHT_RENDERS=4
TTSMODACHI_BOT_RENDER_CONCURRENCY=2
TTSMODACHI_OUTPUT_GAIN_PERCENT=125
TTSMODACHI_GRAMMAR_PAUSES=true
```

if your CPU has room, raise workers later. each worker is a warm Citra instance. more workers can make latency worse if the machine is already out of CPU.

the defaults in `.env.example` are intentionally small. once it works, raise workers and concurrency slowly.

`TTSMODACHI_OUTPUT_GAIN_PERCENT` is the master volume boost after rendering. `100` is normal, `125` is the louder default, and `150` is pretty spicy.

`TTSMODACHI_GRAMMAR_PAUSES` adds short native pauses after punctuation so sentences read less flat. leave it on unless the renderer starts acting weird.

by default, the bot joins voice undeafened so Discord does not show it as deafened. if you want the old behavior:

```env
TTSMODACHI_VOICE_SELF_DEAF=true
```

## public hosting notes

keep the renderer bound to localhost unless you know what you are doing:

```env
RENDERER_BIND=127.0.0.1
```

if you put a reverse proxy in front of it, set:

```env
TTSMODACHI_PANEL_URL=https://your-domain.example
TTSMODACHI_PUBLIC_HOSTS=your-domain.example
TTSMODACHI_PANEL_SIGNING_KEY=replace_me
TTSMODACHI_PANEL_TOKEN=replace_me
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
