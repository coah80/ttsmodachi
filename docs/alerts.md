# StreamElements Alerts

The streamer-facing install is a StreamElements Custom Widget. The widget runs inside the overlay they already use, listens for bit events, asks a hosted TTSmodachi service to render the message, then plays the returned audio.

No OBS plugin, no DLL signing, no admin install, no Docker on the streamer's computer.

The widget queues bit messages in event order. If two cheers arrive at once, it starts rendering them immediately but only plays one TTS audio clip at a time.

## Streamer install, easiest path

Give the streamer a finished widget file generated from your hosted alerts URL:

```powershell
.\make-streamer-widget.bat -BaseUrl https://your-alerts-domain.example
```

Then they do this in StreamElements:

1. Open the overlay they already use.
2. Add a Custom Widget.
3. Open the widget editor.
4. Replace the widget JavaScript with the generated file.
5. Save the overlay.
6. Send a test cheer/bit event.

The streamer does not add a new OBS source if their StreamElements overlay is already in OBS.

## Hosted service

Host the alert service next to the renderer. Set:

```env
TTSMODACHI_ALERTS_PUBLIC_BASE_URL=https://your-alerts-domain.example
TTSMODACHI_ALERTS_SHARED_SECRET=optional_token_here
```

You can either open the hosted setup page and copy the generated widget code, or export the same code from this repo:

```powershell
.\make-streamer-widget.bat -BaseUrl https://your-alerts-domain.example
```

If you use a token:

```powershell
.\make-streamer-widget.bat -BaseUrl https://your-alerts-domain.example -Token optional_token_here
```

## Local developer test

This path runs the renderer on your machine and requires Docker Desktop to be open and running:

```powershell
.\start-alerts.bat
```

Open:

```text
http://127.0.0.1:18081/setup
```

If you see `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`, Docker Desktop is not running. Open Docker Desktop, wait for it to finish starting, then run `.\start-alerts.bat` again.

## Useful settings

```env
TTSMODACHI_ALERTS_HOST=127.0.0.1
TTSMODACHI_ALERTS_HOST_PORT=18081
TTSMODACHI_ALERTS_PUBLIC_BASE_URL=
TTSMODACHI_ALERTS_VOICE=youngf
TTSMODACHI_ALERTS_INCLUDE_TYPES=cheer,cheer-latest,cheerPurchase,cheerPurchase-latest
TTSMODACHI_ALERTS_MESSAGE_TEMPLATE={user} cheered {amount} bits. {message}
TTSMODACHI_ALERTS_NO_MESSAGE_TEMPLATE={user} cheered {amount} bits.
TTSMODACHI_ALERTS_DEDUPE_SECONDS=90
TTSMODACHI_ALERTS_SHARED_SECRET=
```

`TTSMODACHI_ALERTS_INCLUDE_TYPES` can include more event types later, such as `tip`.
