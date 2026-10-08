"""Bounded GET requests; no One Call subscriptions or paid products."""

import math

from jsonschema import Draft202012Validator

from .catalog import CURRENT, FORECAST, ORIGIN, SERVICES


def validate_target(endpoint_id, url, mode):
    selected = SERVICES.get(endpoint_id)
    if not selected or url != ORIGIN + selected["path"] or mode not in {"test", "live"}:
        raise ValueError("OpenWeather must use its approved weather route")


def request_cost(value):
    if (
        not isinstance(value, str)
        or not value.isascii()
        or not value.isdecimal()
        or int(value) > 1_000_000
    ):
        raise ValueError(
            "OPENWEATHER_REQUEST_COST_MICROUSD must be a nonnegative integer up to 1000000"
        )
    return int(value)


def prepare(endpoint_id, url, mode, payload, secret):
    validate_target(endpoint_id, url, mode)
    if next(Draft202012Validator(SERVICES[endpoint_id]["input_schema"]).iter_errors(payload), None):
        raise ValueError("Payload exceeds OpenWeather service limits")
    if not all(math.isfinite(payload[k]) for k in ("latitude", "longitude")):
        raise ValueError("Coordinates must be finite")
    if not secret or any(c.isspace() for c in secret):
        raise ValueError("OpenWeather API key is invalid")
    params = {
        "lat": payload["latitude"],
        "lon": payload["longitude"],
        "units": payload.get("units", "metric"),
    }
    if endpoint_id == FORECAST:
        params["cnt"] = payload.get("limit", 40)
    return params, secret


def snapshot(value):
    if not isinstance(value, dict) or type(value.get("dt")) is not int or value["dt"] <= 0:
        raise ValueError("OpenWeather observation timestamp is missing")
    main = value.get("main")
    if (
        not isinstance(main, dict)
        or type(main.get("temp")) not in (int, float)
        or not math.isfinite(main["temp"])
    ):
        raise ValueError("OpenWeather temperature is missing")
    weather = value.get("weather")
    if (
        not isinstance(weather, list)
        or not weather
        or not all(
            isinstance(w, dict)
            and type(w.get("id")) is int
            and isinstance(w.get("description"), str)
            for w in weather
        )
    ):
        raise ValueError("OpenWeather conditions are missing")
    # Explicit fields avoid carrying arbitrary upstream metadata or echoed secrets.
    return {
        k: value[k]
        for k in ("dt", "main", "weather", "wind", "clouds", "rain", "snow", "visibility", "pop")
        if k in value
    }


def parse(endpoint_id, payload, body, cost):
    if (
        not isinstance(body, dict)
        or type(body.get("cod")) not in (int, str)
        or str(body["cod"]) != "200"
    ):
        raise ValueError("OpenWeather did not confirm successful weather data")
    data = {
        "provider": "OpenWeather",
        "endpoint_id": endpoint_id,
        "latitude": payload["latitude"],
        "longitude": payload["longitude"],
        "units": payload.get("units", "metric"),
        "attribution": {"name": "OpenWeather", "url": "https://openweathermap.org/"},
    }
    if endpoint_id == CURRENT:
        data["current"] = snapshot(body)
        if isinstance(body.get("name"), str):
            data["location_name"] = body["name"]
        if type(body.get("timezone")) is int:
            data["timezone_offset_seconds"] = body["timezone"]
    else:
        rows = body.get("list")
        if (
            not isinstance(rows, list)
            or not 1 <= len(rows) <= payload.get("limit", 40)
            or type(body.get("cnt")) is not int
            or body["cnt"] != len(rows)
        ):
            raise ValueError("OpenWeather forecast count is invalid")
        data["forecast"] = [snapshot(row) for row in rows]
        city = body.get("city")
        if not isinstance(city, dict):
            raise ValueError("OpenWeather forecast location is missing")
        data["location"] = {
            k: city[k] for k in ("name", "country", "timezone", "sunrise", "sunset") if k in city
        }
    receipt = {
        "method": "api_key",
        "provider": "openweather",
        "status": "success",
        "cost_microusd": cost,
        "cost_basis": "configured_per_request_estimate",
        "requests_accounted": 1,
    }
    return data, receipt, cost
