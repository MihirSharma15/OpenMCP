"""Fixed Nova-3 options and duration-based vendor cost estimates."""

import math
from decimal import ROUND_CEILING, Decimal

from jsonschema import Draft202012Validator

from .audio import validate_audio_url
from .catalog import INPUT, MAX_SECONDS, ORIGIN, SERVICES


def validate_target(endpoint_id, url, mode):
    if endpoint_id not in SERVICES or url != ORIGIN + "/v1/listen" or mode not in {"test", "live"}:
        raise ValueError("Deepgram must use its approved prerecorded route")


def prepare(endpoint_id, url, mode, payload, secret, allowed_hosts):
    validate_target(endpoint_id, url, mode)
    if next(Draft202012Validator(INPUT).iter_errors(payload), None):
        raise ValueError("Payload exceeds Deepgram service limits")
    validate_audio_url(payload["audio_url"], allowed_hosts)
    if not secret or not secret.isascii() or any(c.isspace() for c in secret):
        raise ValueError("Deepgram API key is invalid")
    return parameters(endpoint_id, payload), "Token " + secret


def parameters(endpoint_id, payload):
    return {
        "model": "nova-3",
        "language": SERVICES[endpoint_id]["language"],
        "smart_format": str(payload.get("smart_format", True)).lower(),
        "diarize": str(payload.get("diarize", False)).lower(),
        "multichannel": "false",
        "mip_opt_out": "true",
    }


def number(value, minimum, maximum):
    return type(value) in (int, float) and math.isfinite(value) and minimum <= value <= maximum


def parse(endpoint_id, body, verified_duration):
    if not isinstance(body, dict) or any(k in body for k in ("err_code", "err_msg", "error")):
        raise ValueError("Deepgram did not confirm transcription")
    metadata = body.get("metadata")
    if (
        not isinstance(metadata, dict)
        or not isinstance(metadata.get("request_id"), str)
        or not 1 <= len(metadata["request_id"]) <= 100
        or not number(metadata.get("duration"), 0.001, MAX_SECONDS + 0.25)
        or abs(metadata["duration"] - verified_duration) > 0.25
        or type(metadata.get("channels")) is not int
        or metadata["channels"] != 1
    ):
        raise ValueError("Deepgram audio metadata does not match verified audio")
    results = body.get("results")
    channels = results.get("channels") if isinstance(results, dict) else None
    if not isinstance(channels, list) or len(channels) != 1 or not isinstance(channels[0], dict):
        raise ValueError("Deepgram did not return a mono transcript")
    alternatives = channels[0].get("alternatives")
    if (
        not isinstance(alternatives, list)
        or not alternatives
        or not isinstance(alternatives[0], dict)
    ):
        raise ValueError("Deepgram transcript is missing")
    best = alternatives[0]
    words = best.get("words")
    if (
        not isinstance(best.get("transcript"), str)
        or not number(best.get("confidence"), 0, 1)
        or not isinstance(words, list)
        or len(words) > 10000
    ):
        raise ValueError("Deepgram transcript or confidence is invalid")
    normalized = []
    for word in words:
        if (
            not isinstance(word, dict)
            or not isinstance(word.get("word"), str)
            or not number(word.get("start"), 0, verified_duration + 0.25)
            or not number(word.get("end"), 0, verified_duration + 0.25)
            or word["start"] > word["end"]
            or not number(word.get("confidence"), 0, 1)
            or ("speaker" in word and (type(word["speaker"]) is not int or word["speaker"] < 0))
        ):
            raise ValueError("Deepgram word timestamps are invalid")
        normalized.append(
            {
                k: word[k]
                for k in ("word", "punctuated_word", "start", "end", "confidence", "speaker")
                if k in word
            }
        )
    rate = SERVICES[endpoint_id]["rate_microusd_per_minute"]
    duration = metadata["duration"]
    cost = int((Decimal(str(duration)) * rate / 60).to_integral_value(rounding=ROUND_CEILING))
    data = {
        "provider": "Deepgram",
        "endpoint_id": endpoint_id,
        "model": "nova-3",
        "duration_seconds": duration,
        "transcript": best["transcript"],
        "confidence": best["confidence"],
        "words": normalized,
        "request_id": metadata["request_id"],
    }
    receipt = {
        "method": "api_key",
        "provider": "deepgram",
        "status": "success",
        "request_id": metadata["request_id"],
        "cost_microusd": cost,
        "cost_basis": "duration_at_published_payg_rate_estimate",
        "rate_microusd_per_minute": rate,
        "duration_seconds": duration,
        "requests_accounted": 1,
    }
    return data, receipt, cost
