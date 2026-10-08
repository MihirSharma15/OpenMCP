"""One self-contained Markdown-to-PDF query; no arbitrary browser options."""

from copy import deepcopy

ORIGIN = "https://v2.api2pdf.com"
MARKDOWN = "api2pdf-markdown-to-pdf"
URL = ORIGIN + "/chrome/pdf/markdown"
MAX_CHARACTERS = 20_000
MAX_COST_MICROUSD = 30_000
INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {
            "type": "string",
            "minLength": 1,
            "maxLength": MAX_CHARACTERS,
            "pattern": r"^(?![\s\S]*<)(?![\s\S]*!\s*\[)[\s\S]*\S[\s\S]*$",
            "description": "Self-contained Markdown, at most 20,000 characters. No raw HTML/less-than characters or image syntax, including inside code blocks. Normal Markdown hyperlinks are allowed.",
        },
        "filename": {
            "type": "string",
            "maxLength": 100,
            "pattern": r"^[A-Za-z0-9][A-Za-z0-9._-]*\.pdf(?![\s\S])",
            "default": "report.pdf",
            "description": "Download filename ending in .pdf; letters, digits, dots, underscores and hyphens only. No directories.",
        },
    },
    "required": ["markdown"],
    "additionalProperties": False,
}


def provider(mode="test"):
    if mode not in {"test", "live"}:
        raise ValueError("Choose test or live account mode")
    return {
        "provider_id": "api2pdf",
        "name": "API2PDF",
        "description": "Generate a downloadable PDF from a self-contained Markdown report. OpenMCP exposes only Markdown-to-PDF with bounded text input and a temporary vendor-hosted download link; no URL/Office conversion, raw HTML, images, screenshots, document merging or custom storage.",
        "secret_ref": "API2PDF_API_KEY",
        "queries": [
            {
                "endpoint_id": MARKDOWN,
                "name": "API2PDF Markdown report to PDF",
                "description": "Convert markdown (1–20,000 characters) into a PDF report using Headless Chrome. Supports headings, lists, emphasis, code and normal Markdown hyperlinks. No raw HTML/less-than characters or image syntax, even inside code blocks. Optional filename defaults to report.pdf. Returns file_url, filename, vendor response ID and retention_seconds=86400: give the user a download link and explain it is temporary. Link access does not require an OpenMCP login, so treat the URL as private. No file bytes, permanent storage or rendering options. Flat $0.03 per successful conversion.",
                "keywords": ["pdf", "document", "markdown", "report", "download", "convert"],
                "url": URL,
                "adapter": "api2pdf",
                "settlement": "api_key",
                "price_cents": 3,
                "input_schema": deepcopy(INPUT_SCHEMA),
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "provider": {"const": "API2PDF"},
                        "endpoint_id": {"const": MARKDOWN},
                        "file_url": {"type": "string", "pattern": "^https://"},
                        "filename": {"type": "string"},
                        "retention_seconds": {"const": 86400},
                        "vendor_reference": {"type": "string"},
                    },
                    "required": [
                        "provider",
                        "endpoint_id",
                        "file_url",
                        "filename",
                        "retention_seconds",
                        "vendor_reference",
                    ],
                },
                "enabled": True,
                "mode": mode,
                # Durable OpenMCP replay; not a vendor-side idempotency guarantee.
                "supports_idempotency": True,
            }
        ],
    }
