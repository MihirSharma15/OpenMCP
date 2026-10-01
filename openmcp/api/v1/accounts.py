"""Account and agent routes. The bootstrap route uses the demo connection token."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from openmcp.domain.accounts import (
    IssuedCredential,
    Principal,
    Scope,
    create_account,
    create_agent,
    issue_credential,
    revoke_credential,
)

from .auth import call_account, require_demo_token, require_owner_principal
from .models import (
    AccountCreatedResponse,
    AgentCreatedResponse,
    CreateAgentRequest,
    CredentialCreatedResponse,
    CredentialCreateRequest,
    CredentialRevokedResponse,
)

router = APIRouter(prefix="/v1")


@router.post("/accounts", response_model=AccountCreatedResponse)
def post_account(request: Request) -> AccountCreatedResponse:
    """Create an account. Requires the demo token, not an account credential."""

    require_demo_token(request)
    issued = call_account(lambda: create_account(request.app.state.accounts))
    return _created(issued)


@router.post("/agents", response_model=AgentCreatedResponse)
def post_agent(
    request: Request,
    principal: Annotated[Principal, Depends(require_owner_principal)],
    body: CreateAgentRequest | None = None,
) -> AgentCreatedResponse:
    # ``body`` rejects a caller-supplied account id. The principal owns the agent.
    _ = body
    agent = call_account(lambda: create_agent(request.app.state.accounts, principal))
    return AgentCreatedResponse(agent_id=agent.agent_id, account_id=agent.account_id)


@router.post("/agents/{agent_id}/credentials", response_model=CredentialCreatedResponse)
def post_agent_credential(
    agent_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_owner_principal)],
    body: CredentialCreateRequest | None = None,
) -> CredentialCreatedResponse:
    expires_at = None if body is None else body.expires_at
    issued = call_account(
        lambda: issue_credential(
            request.app.state.accounts,
            principal,
            agent_id=agent_id,
            scopes={Scope.AGENT_EXECUTE},
            expires_at=expires_at,
        )
    )
    return CredentialCreatedResponse(
        account_id=issued.account_id,
        agent_id=agent_id,
        credential_id=issued.credential_id,
        secret=issued.secret,
        scopes=sorted(issued.scopes),
    )


@router.post(
    "/agents/{agent_id}/credentials/{credential_id}/revoke",
    response_model=CredentialRevokedResponse,
)
def post_revoke_agent_credential(
    agent_id: str,
    credential_id: str,
    request: Request,
    principal: Annotated[Principal, Depends(require_owner_principal)],
) -> CredentialRevokedResponse:
    revoked = call_account(
        lambda: revoke_credential(
            request.app.state.accounts,
            principal,
            credential_id,
            agent_id=agent_id,
        )
    )
    return CredentialRevokedResponse(
        credential_id=revoked.credential_id,
        agent_id=agent_id,
        revoked=revoked.revoked,
    )


def _created(issued: IssuedCredential) -> AccountCreatedResponse:
    return AccountCreatedResponse(
        account_id=issued.account_id,
        credential_id=issued.credential_id,
        secret=issued.secret,
        scopes=sorted(issued.scopes),
    )
