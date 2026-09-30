"""Issued-card tool adapter over an already connected, user-scoped MCP session.

The session's lifecycle and connection tokens belong to the application. Do not
share sessions across users or expose this adapter directly as an agent tool.
"""

from typing import Protocol

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, ValidationError
from mcp.types import CallToolResult, ListToolsResult

from .models import AgentCardError, IssuedCardRequest


class ToolSession(Protocol):
    async def list_tools(self, cursor: str | None = None) -> ListToolsResult: ...

    async def call_tool(self, name: str, arguments: dict) -> CallToolResult: ...


class IssuedCards:
    def __init__(self, session: ToolSession):
        self._session = session

    async def _call(self, name: str, arguments: dict, *, mutation: bool) -> CallToolResult:
        cursor = None
        seen = set()
        schema = None
        # Discover schemas at runtime. Discovery does not grant permission to call
        # every upstream tool; only the explicit methods below are exposed here.
        try:
            for _ in range(100):
                page = await self._session.list_tools(cursor=cursor)
                tool = next((tool for tool in page.tools if tool.name == name), None)
                if tool is not None:
                    schema = tool.inputSchema
                    break
                cursor = page.nextCursor
                if not cursor:
                    break
                if cursor in seen:
                    raise AgentCardError("invalid_tool_catalog")
                seen.add(cursor)
            else:
                raise AgentCardError("invalid_tool_catalog")
        except AgentCardError:
            raise
        except Exception:
            raise AgentCardError("tool_discovery_failed") from None
        if schema is None:
            raise AgentCardError("tool_unavailable")
        try:
            Draft202012Validator.check_schema(schema)
            Draft202012Validator(schema).validate(arguments)
        except (SchemaError, ValidationError):
            raise AgentCardError("tool_contract_mismatch") from None
        try:
            result = await self._session.call_tool(name, arguments)
        except Exception:
            # No retry wrapper: the upstream mutation may already have happened.
            raise AgentCardError("tool_call_failed", outcome_unknown=mutation) from None
        if result.isError:
            # Raw MCP error text can contain secrets. Workflow code must reconcile.
            raise AgentCardError("tool_rejected", outcome_unknown=mutation)
        return result

    async def balance(self) -> CallToolResult:
        return await self._call("get_balance", {}, mutation=False)

    async def funding_link(self, amount_cents: int) -> CallToolResult:
        if type(amount_cents) is not int or amount_cents <= 0:
            raise ValueError("Funding amount must be a positive integer in USD cents")
        return await self._call("add_funds", {"amount_cents": amount_cents}, mutation=True)

    async def create(self, request: IssuedCardRequest) -> CallToolResult:
        """Call after persisting a card intent and reserving the entire card limit.

        The public issuing guide does not specify MCP create_card idempotency.
        A lost reply must stay outcome_unknown until reconciled; do not call again.
        Raw results are server-internal and may contain sensitive card information.
        """
        return await self._call("create_card", request.tool_arguments(), mutation=True)
