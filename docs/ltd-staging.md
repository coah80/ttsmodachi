# LTD staging

TTSModachi keeps the existing 3DS/Citra engine as `tl3ds`. Tomodachi Life: Living the Dream work is isolated as the experimental `ltd-switch` engine until it can render a known test phrase reliably.

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
- Required before enabling in Discord: build id captured, address table versioned, one fixed phrase renders to PCM, and staging benchmark is recorded against current 3DS warm/cache/idle numbers.

## Next reverse-engineering pass

1. Extract PFS0 metadata locally into `ltd-work/metadata`.
2. Use the base program NCA `2e88713715d1d950ece6ce679a2fd456.nca`; it contains `main`, `sdk`, `rtld`, and `main.npdm` in ExeFS.
3. Start from the current string anchors found in `main`: `VoiceSynthesis`, `END of LOADTTS`, `VoiceText/us`, `engttsdict_emb`, `/tts_single_db(D32-GLORIA).vtdb2`, `/tts_single_db(D32-CHLOE).vtdb2`, and the `pcm/` database paths.
4. Build a Ryubing/Ryujinx headless runner in `ryubing-work/` and keep emulator source/build artifacts out of this repo.
5. Add a memory bridge that matches the renderer service contract: input text + voice params in, WAV/PCM bytes out.
