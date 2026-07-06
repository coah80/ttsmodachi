# stream.coah80.com live setup

Live app:

```text
https://stream.coah80.com
```

Local service:

```text
http://127.0.0.1:18120
```

Compose service:

```sh
docker compose --profile stream up -d --no-deps stream
```

Tunnel service:

```sh
systemctl --user status cloudflared-ttsmodachi-stream.service
```

Twitch app values still needed in `.env`:

```env
TWITCH_CLIENT_ID=
TWITCH_CLIENT_SECRET=
```

Twitch redirect URL:

```text
https://stream.coah80.com/auth/twitch/callback
```
