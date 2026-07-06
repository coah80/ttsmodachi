# How the Tomodachi Life voice engine handles voices

Notes from reverse-engineering the US ROM (`code.bin`, remaster `0002`) plus
an empirical render sweep against the live renderer. This is the reference for
keeping the web voice panel faithful to the game.

## The game's own voice editor (authoritative)

Decompressed from `romfs/message/Game/Game_US_English_LZ.bin` (LZ11 -> DARC ->
`Edit.msbt`). The in-game "Mii Voice" screen offers three ways to set a voice,
then six custom sliders:

| In-game text  | Internal label      | Meaning |
|---------------|---------------------|---------|
| Preset        | `VoiceEasySet`      | Pick a ready-made voice |
| Random        | `VoiceRandomSet`    | Roll a random voice |
| Custom / Edit Voice | `VoiceCustomSet` / `VoiceCustomEdit` | Tweak the six sliders |
| Pitch         | `VoiceCustom_Pitch` | |
| Speed         | `VoiceCustom_Speed` | |
| Quality       | `VoiceCustom_Warp`  | internal name is "Warp" |
| Tone          | `VoiceCustom_Phrase`| internal name is "Phrase" |
| Accent        | `VoiceCustom_Accent`| |
| Intonation    | `VoiceCustom_Intona`| |

Tutorial text: *"Give this Mii a voice! You can select a preset or random
setting or customize it yourself."* The panel mirrors this: Preset buttons,
a Random Voice button, and the six Custom sliders.

## The six parameters

The game's TTS is `libNTTS` (Nintendo TTS, data in `romfs/libNTTS`). A single
voice is described by six values. The patch (`gamePatch/source`) drives them
through six engine setters, which are virtual-dispatch thunks on the
`mainTtsClass` vtable:

| Parameter   | Setter thunk          | vtable slot |
|-------------|-----------------------|-------------|
| Pitch       | `setVoicePitch`       | `+0x7c`     |
| Speed       | `setVoiceSpeed`       | `+0x80`     |
| Quality     | `setVoiceQuality`     | `+0x84`     |
| Tone        | `setVoiceTone`        | `+0x88`     |
| Accent      | `setVoiceAccent`      | `+0x8c`     |
| Intonation  | `setVoiceIntonation`  | `+0x90`     |

Pitch/Speed/Quality/Tone/Accent take a 0–100 value with 50 as the neutral
centre (the patch defaults every one to 50, matching the game's default Mii
voice). Intonation is a small enum (the bot exposes 1–4).

## Measured behaviour (live renderer sweep)

Rendering "test one two three four" and varying one parameter at a time, then
measuring median fundamental frequency (f0) and clip duration:

| Param     | value 0 | 25    | 50 (default) | 75    | 100   | What it does |
|-----------|---------|-------|--------------|-------|-------|--------------|
| pitch     | ~86 Hz  | 124   | 246          | 291   | ~246* | Voice frequency; low = deep, high = squeaky. Dominant f0 control. |
| tone      | 167 Hz  | 219   | 246          | 254   | 291   | Brightness / formant shift; also reads as pitch. |
| speed     | 2.54 s  | 1.82  | 1.45         | 1.15  | 0.99  | Talking speed. 0 slow, 100 fast. f0 unaffected. |
| quality   | ~242 Hz | 237   | 246          | 246   | 246   | Timbre/clarity. Subtle; barely moves f0 or duration. |
| accent    | 198 Hz  | 235   | 246          | 230   | 248   | Emphasis on the pitch *contour*, not steady f0. |
| intonation| mode 1 flat | mode 2 gentle | mode 3 lively (longer, 1.57 s) | mode 4 questioning | | Sentence melody / mood. |

\* the 100 reading is an octave-detection artefact in the crude f0 estimator,
not a real drop — perceived pitch keeps rising past 75.

Takeaways for the panel:
- Pitch and Tone are the big, obvious controls (both raise perceived pitch).
- Speed is a clean duration control.
- Quality and Accent are fine-detail; keep them but set expectations low.
- Intonation is four discrete moods, not a continuous slider.

The web panel mirrors the game's "Edit Voice" screen exactly: the five sliders
appear in the game's top-to-bottom order (Pitch, Speed, Quality, Tone, Accent)
with a neutral-centre tick at 50, and Intonation is a row of four mood buttons
(Flat, Gentle, Lively, Questioning) rather than a slider. The whole editor keeps
the dashboard's existing dark theme instead of imitating the game's art.

## Internals (partial)

The concrete setters (`0x7d9xxx` in the US dump) index a 10-byte-stride table
in the engine object (`this->0xc`), reading per-field bytes (tone at +2, accent
at +4, pitch at +6, speed at +8, intonation at +9). This is the engine's
slider-value -> coefficient response curve (indexed by the 0-100 value), which
is why the measured response is monotonic-ish but not perfectly linear.

## Assets that exist but are not shipped

- The in-game voice-editor UI is in `romfs/layout/layout_editor_LZ.bin`
  (LZ11 -> DARC): `Voice.bclyt` / `VoiceDetail.bclyt` layouts plus
  `Voice_*.bclim` textures. Decoding BCLIM (3DS tile-swizzle + ETC1) is a
  separate pipeline, and the art is Nintendo's, so it is intentionally not
  baked into this repo. The panel recreates the layout in CSS instead.
- Tools used: `docs`/`ntools.py`-style LZ11 + DARC + MSBT parsing (not committed;
  reproducible from any US dump with `3dstool`).

## Not yet done

- Non-English voices need the EU ROM (`roms/EU.cxi`) and EU-specific gamePatch
  hook addresses; the US dump only produces US English. See `gamePatch/hooks`.
