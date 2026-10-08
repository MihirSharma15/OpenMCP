"""Two fixed transcription products with bounded audio, model and retail prices."""

from copy import deepcopy

ORIGIN = "https://api.deepgram.com"
ENGLISH = "deepgram-transcribe-english"
MULTILINGUAL = "deepgram-transcribe-multilingual"
MAX_SECONDS = 120
MAX_BYTES = 12_000_000
INPUT = {
    "type": "object",
    "properties": {
        "audio_url": {
            "type": "string",
            "minLength": 1,
            "maxLength": 2048,
            "description": "HTTPS URL to a mono PCM WAV recording, at most 120 seconds and 12 MB, on an operator-approved audio host. Not an arbitrary website or local file path.",
        },
        "diarize": {
            "type": "boolean",
            "default": False,
            "description": "Label speakers in word timestamps. Included in the prerecorded price.",
        },
        "smart_format": {"type": "boolean", "default": True},
    },
    "required": ["audio_url"],
    "additionalProperties": False,
}
SERVICES = {
    ENGLISH: {
        "name": "English audio transcription",
        "language": "en",
        "rate_microusd_per_minute": 4300,
        "description": "Transcribe English audio using Nova-3. audio_url must be a public HTTPS link on an operator-approved host to mono integer PCM WAV: at most 120 seconds and 12 MB, 8–48 kHz sample rate, 8/16/24/32-bit samples. Returns transcript, confidence, duration, word timestamps and request ID. Optional diarize (default false) adds speaker labels; smart_format defaults to true. MP3/M4A, stereo audio, local files, uploads, streaming and format conversion are not supported. Integration is work in progress.",
    },
    MULTILINGUAL: {
        "name": "Multilingual audio transcription",
        "language": "multi",
        "rate_microusd_per_minute": 5200,
        "description": "Transcribe multilingual or code-switching audio using Nova-3's supported languages. audio_url must be a public HTTPS link on an operator-approved host to mono integer PCM WAV: at most 120 seconds and 12 MB, 8–48 kHz sample rate, 8/16/24/32-bit samples. Returns transcript, confidence, duration, word timestamps and request ID. Optional diarize (default false) adds speaker labels; smart_format defaults to true. MP3/M4A, stereo audio, local files, uploads, streaming and format conversion are not supported. Integration is work in progress.",
    },
}
OUTPUT = {
    "type": "object",
    "properties": {
        "provider": {"const": "Deepgram"},
        "endpoint_id": {"type": "string"},
        "transcript": {"type": "string"},
        "duration_seconds": {"type": "number"},
        "confidence": {"type": "number"},
        "words": {"type": "array", "items": {"type": "object"}},
        "request_id": {"type": "string"},
    },
    "required": [
        "provider",
        "endpoint_id",
        "transcript",
        "duration_seconds",
        "words",
        "request_id",
    ],
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    return {
        "provider_id": "deepgram",
        "name": "Deepgram",
        "description": "Work in progress: two prerecorded Nova-3 speech-to-text queries for English or supported multilingual/code-switching audio. Only public HTTPS links on operator-approved hosts to mono integer PCM WAV recordings up to 120 seconds/12 MB are supported. Returns transcript, word timestamps and optional speaker labels; no streaming, speech generation, uploads or audio conversion.",
        "secret_ref": "DEEPGRAM_API_KEY",
        "queries": [
            {
                "endpoint_id": identifier,
                "name": "Deepgram " + definition["name"],
                "description": definition["description"] + " Flat $0.02 per successful request.",
                "url": ORIGIN + "/v1/listen",
                "adapter": "deepgram",
                "settlement": "api_key",
                "keywords": [
                    "audio",
                    "speech",
                    "transcribe",
                    "transcription",
                    "speakers",
                    "recording",
                ],
                "price_cents": 2,
                "input_schema": deepcopy(INPUT),
                "output_schema": deepcopy(OUTPUT),
                "enabled": True,
                "mode": mode,
                "supports_idempotency": True,
            }
            for identifier, definition in SERVICES.items()
        ],
    }
