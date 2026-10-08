"""Current weather and five-day forecast on OpenWeather's free API collection."""

from copy import deepcopy

CURRENT = "openweather-current"
FORECAST = "openweather-forecast"
ORIGIN = "https://api.openweathermap.org/data/2.5"
INPUT = {
    "type": "object",
    "properties": {
        "latitude": {"type": "number", "minimum": -90, "maximum": 90},
        "longitude": {"type": "number", "minimum": -180, "maximum": 180},
        "units": {
            "type": "string",
            "enum": ["metric", "imperial", "standard"],
            "default": "metric",
        },
    },
    "required": ["latitude", "longitude"],
    "additionalProperties": False,
}
SERVICES = {
    CURRENT: {
        "path": "/weather",
        "name": "Current weather",
        "description": "Get current weather for latitude (-90 to 90) and longitude (-180 to 180). Returns observation time, temperature, conditions, humidity, pressure and wind where available, plus available location/timezone metadata. units is metric (default, Celsius), imperial (Fahrenheit) or standard (Kelvin). Coordinates are required; city-name lookup is not supported. Flat $0.02 per successful request.",
        "input_schema": deepcopy(INPUT),
    },
    FORECAST: {
        "path": "/forecast",
        "name": "Five-day weather forecast",
        "description": "Get forecast weather for latitude (-90 to 90) and longitude (-180 to 180) in three-hour steps for up to five days. limit is 1–40 timestamps, default 40. Returns forecast times, temperature, conditions and available wind/precipitation/location metadata. units is metric (default, Celsius), imperial (Fahrenheit) or standard (Kelvin). No historical weather or alerts. Flat $0.02 per successful request.",
        "input_schema": deepcopy(INPUT),
    },
}
SERVICES[FORECAST]["input_schema"]["properties"]["limit"] = {
    "type": "integer",
    "minimum": 1,
    "maximum": 40,
    "default": 40,
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    return {
        "provider_id": "openweather",
        "name": "OpenWeather",
        "description": "Current weather and a five-day forecast in three-hour intervals for latitude/longitude coordinates worldwide. These two OpenMCP queries support metric, imperial or standard units; city-name geocoding, historical weather and One Call alerts are not exposed.",
        "secret_ref": "OPENWEATHER_API_KEY",
        "queries": [
            {
                "endpoint_id": identifier,
                "name": "OpenWeather " + definition["name"],
                "description": definition["description"],
                "url": ORIGIN + definition["path"],
                "keywords": ["weather", "temperature", "wind", "forecast"],
                "adapter": "openweather",
                "settlement": "api_key",
                "price_cents": 2,
                "input_schema": deepcopy(definition["input_schema"]),
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {"const": "OpenWeather"},
                        "endpoint_id": {"const": identifier},
                    },
                    "required": ["provider", "endpoint_id"],
                },
                "enabled": True,
                "mode": mode,
                "supports_idempotency": True,
            }
            for identifier, definition in SERVICES.items()
        ],
    }
