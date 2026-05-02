from __future__ import annotations

import io
import os
import sys
import wave
from array import array


def amplify_wav(wav_bytes: bytes, volume: int) -> bytes:
    gain = volume / 100
    if abs(gain - 1.0) < 0.01:
        return wav_bytes

    with wave.open(io.BytesIO(wav_bytes), "rb") as reader:
        params = reader.getparams()
        frames = reader.readframes(reader.getnframes())

    if params.sampwidth != 2:
        return wav_bytes

    samples = array("h")
    samples.frombytes(frames)
    if sys.byteorder != "little":
        samples.byteswap()

    limit_peak = max(1000, min(int(os.environ.get("TTSMODACHI_OUTPUT_LIMIT_PEAK", "32000")), 32767))
    peak = max((abs(sample) for sample in samples), default=0)
    if peak > 0 and peak * gain > limit_peak:
        gain = limit_peak / peak

    for index, sample in enumerate(samples):
        boosted = int(sample * gain)
        boosted = max(min(boosted, limit_peak), -limit_peak)
        samples[index] = boosted

    if sys.byteorder != "little":
        samples.byteswap()

    out = io.BytesIO()
    with wave.open(out, "wb") as writer:
        writer.setparams(params)
        writer.writeframes(samples.tobytes())
    return out.getvalue()
