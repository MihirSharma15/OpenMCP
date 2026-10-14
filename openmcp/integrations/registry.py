"""The supported adapters. Provider-specific transport and billing stay in each package."""

from importlib import import_module

BUILTINS = (
    "api2pdf",
    "builtwith",
    "companies_house",
    "dataforseo",
    "deepgram",
    "exa",
    "firecrawl",
    "nansen",
    "openweather",
    "tavily",
)


def adapter(name):
    if name in {"http", "creator"}:
        return import_module("openmcp.integrations.http")
    if name not in BUILTINS:
        raise ValueError(f"Unsupported service adapter: {name}")
    return import_module(f"openmcp.integrations.{name}.adapter")


def provider(name, mode):
    name = name.replace("-", "_")
    if name not in BUILTINS:
        raise ValueError("Unknown provider; use `openmcp providers list --builtins`")
    return import_module(f"openmcp.integrations.{name}.catalog").provider(mode)
