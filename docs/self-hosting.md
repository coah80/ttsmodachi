# self hosting notes

the README has the main tutorial. this file is the short version for people who already know Docker and Discord bots.

1. create a Discord application and bot
2. enable Message Content Intent
3. copy `.env.example` to `.env`
4. set `DISCORD_TOKEN`, `TTSMODACHI_BOT_CLIENT_ID`, and `TTSMODACHI_PANEL_URL`
5. patch your legal CXI with `python tools/patch_rom.py --input ./TomodachiLife.cxi --region US`
6. make sure the patched file lands at `roms/US.cxi`
7. set `TTSMODACHI_WORKER_ROMS=US`
8. start with `TTSMODACHI_US_WORKERS=1`
9. run `docker compose up --build`
10. open `http://127.0.0.1:18080/health`
11. invite the bot and run `/setup`, then `/join`

for public hosting, put a reverse proxy in front of port 18080 and set:

```env
TTSMODACHI_PANEL_URL=https://your-domain.example
TTSMODACHI_PUBLIC_HOSTS=your-domain.example
TTSMODACHI_PANEL_SIGNING_KEY=replace_me
TTSMODACHI_PANEL_TOKEN=replace_me
```

do not publish ROMs, `.env`, SQLite data, logs, tokens, or private deployment notes.
