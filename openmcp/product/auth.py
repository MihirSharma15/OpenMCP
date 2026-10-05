"""Clerk RS256 sessions and opaque machine credentials have distinct authority."""

import time

import httpx
import jwt
from jwt.algorithms import RSAAlgorithm

from .models import ProductError


class ClerkVerifier:
    def __init__(self, settings, *, transport=None):
        self.settings = settings
        self.http = httpx.AsyncClient(timeout=10, transport=transport, follow_redirects=False)
        self.keys = {}
        self.refreshed = 0.0

    async def close(self):
        await self.http.aclose()

    async def subject(self, token):
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256":
                raise ValueError("Unexpected algorithm")
            key = self.settings.clerk_public_key.replace("\\n", "\n")
            if not key:
                kid = header.get("kid")
                if not kid or not isinstance(kid, str):
                    raise ValueError("Missing key ID")
                # Limit unknown-key fetches; issuer is configured, never taken from an unverified JWT.
                stale = time.monotonic() - self.refreshed > 300
                if stale or (kid not in self.keys and time.monotonic() - self.refreshed > 10):
                    response = await self.http.get(
                        self.settings.clerk_issuer.rstrip("/") + "/.well-known/jwks.json"
                    )
                    response.raise_for_status()
                    self.keys = {
                        item["kid"]: RSAAlgorithm.from_jwk(item)
                        for item in response.json()["keys"]
                        if item.get("kty") == "RSA"
                    }
                    self.refreshed = time.monotonic()
                key = self.keys[kid]
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                issuer=self.settings.clerk_issuer.rstrip("/"),
                audience=self.settings.clerk_audience,
                leeway=5,
                options={
                    "require": ["exp", "nbf", "iat", "sub", "iss"],
                    "verify_aud": bool(self.settings.clerk_audience),
                },
            )
            if claims.get("azp") not in self.settings.clerk_authorized_parties:
                raise ValueError("Unauthorized party")
            if (
                claims.get("sts") == "pending"
                or not isinstance(claims["sub"], str)
                or not claims["sub"]
            ):
                raise ValueError("Incomplete session")
            return claims["sub"]
        except (jwt.PyJWTError, ValueError, KeyError, TypeError) as exc:
            raise ProductError(
                "unauthenticated", "A valid Clerk session is required.", 401
            ) from exc
        except httpx.HTTPError as exc:
            raise ProductError(
                "auth_unavailable", "Session verification is unavailable.", 503, True
            ) from exc
