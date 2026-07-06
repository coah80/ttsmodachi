# TTSmodachi Stream

This is the hosted Twitch bits setup.

The streamer install is:

1. Open `https://stream.coah80.com`.
2. Log in with Twitch.
3. Copy the browser source URL.
4. Add it as an OBS Browser Source.
5. Mute the old bit TTS in Streamlabs, StreamElements, or whatever they already use, but keep the alert sound on.
6. Press the dashboard test button.

The OBS source is audio-only. The streamer can keep their existing alert visuals and alert sounds. The default TTS delay is 1.5 seconds, and it can be changed from the dashboard.

Random voice mode picks a new audible preset per bit message, including deep male, normal male/female, high, tiny, and older voices.

Bit messages are rendered and played through one FIFO audio queue. If two cheers arrive at the same time, TTSmodachi reads one, waits for it to finish, then reads the next. Keep only one TTSmodachi browser source active in OBS to avoid duplicate audio.

## Required server settings

```env
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
TTSMODACHI_STREAM_PUBLIC_BASE_URL=https://stream.coah80.com
TTSMODACHI_STREAM_COOKIE_SECRET=
TTSMODACHI_STREAM_RANDOM_VOICES=deepm,adultm,youngm,adultf,highf,tinyf,oldm,oldf
```

The Twitch app redirect URL must be:

```text
https://stream.coah80.com/auth/twitch/callback
```

Run it with:

```sh
docker compose --profile stream up --build -d tts-worker stream
```

The service listens locally on:

```text
http://127.0.0.1:18120
```
