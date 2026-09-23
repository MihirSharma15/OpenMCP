"""The single paid provider application served on port 9001."""

from openmcp_provider import create_provider_app

from .courtlens import provider as courtlens
from .marketscope import provider as marketscope
from .supplysignal import provider as supplysignal

PROVIDERS = (supplysignal, courtlens, marketscope)

app = create_provider_app(PROVIDERS)
