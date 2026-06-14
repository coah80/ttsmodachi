# Hosting

the README has the current setup guide.

short version:

1. make a Discord bot
2. copy `.env.example` to `.env`
3. put your Discord token and client ID in `.env`
4. patch your legal CXI with `tools/patch_rom.py`, or use the manual 3dstool plus Magikoopa flow in the README
5. put the patched CXI in `roms/US.cxi`
6. run `docker compose up --build`

the patch helper does not include or download ROMs. it only works on your own local CXI file.
