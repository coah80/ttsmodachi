# How the Tomodachi Life voice engine handles voices

Notes from reverse-engineering the US ROM (`code.bin`, remaster `0002`) plus
an empirical render sweep against the live renderer. This is the reference for
keeping the web voice panel faithful to the game.

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

## Internals (partial)

The concrete setters (`0x7d9xxx` in the US dump) index a 10-byte-stride record
in the engine object (`this->0xc`), reading per-field bytes (tone at +2, accent
at +4, pitch at +6, speed at +8, intonation at +9). So values pass through an
engine lookup rather than being applied linearly, which is why the measured
response above is monotonic-ish but not perfectly linear.

## Not yet done

- Non-English voices need the EU ROM (`roms/EU.cxi`) and EU-specific gamePatch
  hook addresses; the US dump only produces US English. See `gamePatch/hooks`.
- Pixel-faithful UI textures (the in-game voice-editor art) live in the
  LZ11-compressed DARC layout archives under `romfs/layout`; not extracted yet.
