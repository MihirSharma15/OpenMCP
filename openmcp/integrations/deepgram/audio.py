"""Read approved-host WAV assets and reconstruct verified PCM before a paid call."""

import io
import wave
from urllib.parse import urlsplit

from .catalog import MAX_BYTES, MAX_SECONDS


def validate_audio_url(url, allowed_hosts):
    from openmcp.product.config import validate_service_url

    validate_service_url(url, "live")
    parsed = urlsplit(url)
    if (
        parsed.port not in (None, 443)
        or parsed.hostname != parsed.hostname.lower()
        or parsed.hostname not in allowed_hosts
    ):
        raise ValueError("Audio URL must use an operator-approved HTTPS host on port 443")
    return url


def pcm_audio(raw):
    if not raw or len(raw) > MAX_BYTES or raw[:4] != b"RIFF" or raw[8:12] != b"WAVE":
        raise ValueError("Audio must be a bounded PCM WAV recording")
    try:
        with wave.open(io.BytesIO(raw), "rb") as reader:
            channels, width, rate, count = (
                reader.getnchannels(),
                reader.getsampwidth(),
                reader.getframerate(),
                reader.getnframes(),
            )
            if (
                reader.getcomptype() != "NONE"
                or channels != 1
                or width not in (1, 2, 3, 4)
                or not 8000 <= rate <= 48000
                or not 0 < count <= MAX_SECONDS * rate
            ):
                raise ValueError("Audio must be mono PCM WAV, 8–48 kHz, at most 120 seconds")
            frames = reader.readframes(count)
            if len(frames) != count * width:
                raise ValueError("WAV audio data is truncated")
        # Do not forward unverified ancillary chunks or a second hidden audio stream.
        output = io.BytesIO()
        with wave.open(output, "wb") as writer:
            writer.setnchannels(1)
            writer.setsampwidth(width)
            writer.setframerate(rate)
            writer.writeframes(frames)
        return output.getvalue(), count / rate
    except (wave.Error, EOFError, OSError) as exc:
        raise ValueError("Audio is not a supported PCM WAV recording") from exc


async def load_audio(client, url, allowed_hosts):
    validate_audio_url(url, allowed_hosts)
    raw = bytearray()
    # This client has no provider auth headers; never forward the Deepgram key to an asset host.
    async with client.stream("GET", url, headers={"Accept": "audio/wav"}) as response:
        if response.status_code != 200:
            raise ValueError("Audio host did not return a recording")
        async for chunk in response.aiter_bytes():
            raw.extend(chunk)
            if len(raw) > MAX_BYTES:
                raise ValueError("Audio exceeds the 12 MB download limit")
    return pcm_audio(bytes(raw))
