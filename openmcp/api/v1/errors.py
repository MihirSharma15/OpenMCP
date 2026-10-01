"""JSON errors for /v1 credit routes."""

from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from openmcp.domain.credits import InvalidAmount
from openmcp.models import OpenMCPError

_AMOUNT_FIELDS = frozenset({"amount_cents", "price_cents"})
_INVALID_AMOUNT = str(InvalidAmount(0))


def credit_validation_response(exc: RequestValidationError) -> JSONResponse:
    error = _validation_error(exc)
    return JSONResponse({"error": error.as_dict()}, status_code=error.status)


def _validation_error(exc: RequestValidationError) -> OpenMCPError:
    problems = exc.errors()
    if problems and all(_is_amount_problem(problem) for problem in problems):
        return OpenMCPError("invalid_amount", _INVALID_AMOUNT, status=422)
    return OpenMCPError("invalid_request", "Request validation failed.", status=422)


def _is_amount_problem(problem: dict) -> bool:
    location = problem.get("loc") or ()
    return bool(location) and location[-1] in _AMOUNT_FIELDS
