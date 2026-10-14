"use client";
import { Label } from "@/components/ui/label";
import { SelectField } from "@/components/select-field";
import { Progress } from "@/components/ui/progress";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Alert } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";

import { useEffect, useRef, useState } from "react";
import {
  accountRequest,
  errorMessage,
  localDate,
  money,
  parseAllowance,
  type Agent,
  type Credential,
  type Page,
} from "@/lib/account";
import {
  Empty,
  ErrorNotice,
  Icon,
  Loading,
  Modal,
  Status,
  useResource,
} from "@/components/account/common";
import { useAccount } from "@/components/account/shell";

function CreateAgent({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (agent: Agent) => void;
}) {
  const [name, setName] = useState("");
  const [cap, setCap] = useState("2.00");
  const [days, setDays] = useState("7");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lock = useRef(false);
  const cents = parseAllowance(cap);
  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (lock.current || !cents || !name.trim()) return;
    lock.current = true;
    setBusy(true);
    setError(null);
    try {
      const agent = await accountRequest<Agent>("/agents", {
        method: "POST",
        body: {
          name: name.trim(),
          spend_limit_cents: cents,
          expires_at: new Date(
            Date.now() + Number(days) * 86_400_000 - 60_000,
          ).toISOString(),
        },
      });
      onCreated(agent);
    } catch (caught) {
      setError(
        `${errorMessage(caught)} If you lost your connection, close this dialog and refresh your agents before trying again.`,
      );
      lock.current = false;
      setBusy(false);
    }
  }
  return (
    <Modal title="Give your agent an allowance" onClose={onClose} busy={busy}>
      <p className="account-dialog-copy">
        An allowance is the most this agent can spend in total. Your wallet
        provides the funds; this limit provides permission.
      </p>
      <form onSubmit={create} className="account-form">
        <Label>
          Agent name
          <Input
            autoFocus
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Research assistant"
            required
            maxLength={80}
            disabled={busy}
          />
        </Label>
        <div className="account-form-columns">
          <Label>
            Total allowance (USD)
            <Input
              value={cap}
              onChange={(event) => setCap(event.target.value)}
              inputMode="decimal"
              placeholder="2.00"
              required
              aria-describedby="allowance-help"
              disabled={busy}
            />
          </Label>
          <Label>
            Expires in
            <SelectField
              value={days}
              onValueChange={setDays}
              disabled={busy}
              label="Expires in"
              className="w-full"
              options={[
                { value: "1", label: "1 day" },
                { value: "7", label: "7 days" },
                { value: "30", label: "30 days" },
              ]}
            />
          </Label>
        </div>
        <p id="allowance-help" className="account-helper">
          Enter $0.01–$10,000. This is a lifetime spending cap. Adding money to
          your wallet or replacing a key will not reset it. Create a new agent
          to authorize more spending.
        </p>
        {Boolean(error) && (
          <p role="alert" className="account-form-error">
            {error}
          </p>
        )}
        <Button
          variant="default"
          className="button account-full-button"
          disabled={busy || !cents || !name.trim()}
        >
          {busy
            ? "Creating agent…"
            : `Authorize${cents ? ` ${money(cents)}` : " agent"}`}
        </Button>
      </form>
    </Modal>
  );
}
function ConnectionInstructions() {
  const { publicApiOrigin } = useAccount();
  const origin = publicApiOrigin
    ? `'${publicApiOrigin.replaceAll("'", "'\\''")}'`
    : "'https://YOUR_OPENMCP_API_ORIGIN'";
  const command = `uv run openmcp connect --base-url ${origin}\nuv run openmcp install all --mode account --scope user\nuv run openmcp check-mcp --mode account`;
  return (
    <div className="account-connection">
      <h3>Connect your LLM</h3>
      <p>
        From your OpenMCP checkout, run these commands. Paste your key into the
        private prompt when asked. This installs the account connection for
        Codex, Claude Code, and Cursor.
      </p>
      <pre className="account-code">{command}</pre>
      <p className="account-helper">
        Restart your LLM client after installation. Ask it to check its balance
        and discover services. Discovery is free. Keep the saved credential file
        private.
      </p>
    </div>
  );
}
function NewCredential({
  credential,
  onClose,
}: {
  credential: Credential;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [show, setShow] = useState(false);
  const [copyError, setCopyError] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(credential.secret);
      setCopied(true);
      setCopyError(false);
    } catch {
      setCopyError(true);
    }
  }
  return (
    <Modal title="Save your agent key" onClose={onClose}>
      <p className="account-dialog-copy">
        This key is shown once. Save it privately before closing. Anyone with it
        can use this agent’s remaining allowance until it expires or you revoke
        it.
      </p>
      <div className="account-secret-field">
        <Label htmlFor="agent-secret">Agent key</Label>
        <Input
          id="agent-secret"
          type={show ? "text" : "password"}
          value={credential.secret}
          readOnly
          autoComplete="off"
          spellCheck={false}
          onFocus={(event) => event.target.select()}
        />
        <div className="account-button-row">
          <Button
            variant="outline"
            size="sm"
            className="account-secondary"
            onClick={copy}
          >
            {copied ? "Copied" : "Copy key"}
          </Button>
          <Button
            variant="link"
            size="sm"
            className="account-link-button"
            onClick={() => setShow((value) => !value)}
          >
            {show ? "Hide key" : "Show key"}
          </Button>
        </div>
        {copyError && (
          <p className="account-form-error" role="alert">
            Clipboard access is unavailable. Show the key and copy it manually.
          </p>
        )}
        <p className="account-helper" role="status">
          {copied
            ? "Key copied. Paste it into the private OpenMCP connection prompt."
            : `Expires ${localDate(credential.expires_at)}`}
        </p>
      </div>
      <ConnectionInstructions />
      <Button
        variant="default"
        className="button account-full-button"
        onClick={onClose}
      >
        I’ve saved my key
      </Button>
    </Modal>
  );
}
export default function AgentsPage() {
  const { account } = useAccount();
  const agents = useResource<Page<Agent>>("/agents?limit=100", (data) =>
    data.items.some((item) => item.reserved_cents > 0),
  );
  const [create, setCreate] = useState(false);
  const [credential, setCredential] = useState<Credential | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const lock = useRef(false);
  const [additionalAgents, setAdditionalAgents] = useState<Agent[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const pageGeneration = useRef(0);
  useEffect(() => {
    pageGeneration.current += 1;
    setAdditionalAgents([]);
    setNextCursor(agents.data?.next_cursor ?? null);
  }, [agents.data]);
  const displayedAgents = [
    ...new Map(
      [...(agents.data?.items ?? []), ...additionalAgents].map((agent) => [
        agent.agent_id,
        agent,
      ]),
    ).values(),
  ];
  async function loadMoreAgents() {
    if (!nextCursor || loadingMore) return;
    const generation = pageGeneration.current;
    setLoadingMore(true);
    setError(null);
    try {
      const result = await accountRequest<Page<Agent>>(
        `/agents?limit=100&cursor=${encodeURIComponent(nextCursor)}`,
      );
      if (generation === pageGeneration.current) {
        setAdditionalAgents((previous) => [...previous, ...result.items]);
        setNextCursor(result.next_cursor);
      }
    } catch (caught) {
      if (generation === pageGeneration.current) setError(caught);
    } finally {
      setLoadingMore(false);
    }
  }
  async function issue(agent: Agent) {
    if (lock.current) return;
    lock.current = true;
    setBusy(agent.agent_id);
    setError(null);
    try {
      const result = await accountRequest<Credential>(
        `/agents/${encodeURIComponent(agent.agent_id)}/credentials`,
        { method: "POST", body: {} },
      );
      setCredential(result);
      agents.reload();
    } catch (caught) {
      setError(caught);
      agents.reload();
    } finally {
      lock.current = false;
      setBusy(null);
    }
  }
  async function revoke(agentId: string, credentialId: string) {
    if (lock.current) return;
    lock.current = true;
    setBusy(credentialId);
    setError(null);
    try {
      await accountRequest(
        `/agents/${encodeURIComponent(agentId)}/credentials/${encodeURIComponent(credentialId)}/revoke`,
        { method: "POST", body: {} },
      );
      agents.reload();
    } catch (caught) {
      setError(caught);
    } finally {
      lock.current = false;
      setBusy(null);
    }
  }
  function created(agent: Agent) {
    setCreate(false);
    agents.reload();
    void issue(agent);
  }
  return (
    <>
      <div className="account-page-heading">
        <div>
          <h1>Agents</h1>
          <p>Give each agent an allowance and a key to your wallet.</p>
        </div>
        <Button
          variant="default"
          className="button"
          disabled={account.status !== "active"}
          onClick={() => setCreate(true)}
        >
          <Icon name="plus" size={17} />
          Create agent
        </Button>
      </div>
      <Alert role="status" className="account-notice">
        <Icon name="wallet" />
        <p>
          Wallet funds and agent allowances work together. An agent can spend
          only what both have available. Top-ups and new keys never reset an
          allowance.
        </p>
      </Alert>
      {Boolean(error) && <ErrorNotice error={error} />}{" "}
      {Boolean(agents.error) && (
        <ErrorNotice error={agents.error} retry={agents.reload} />
      )}{" "}
      {agents.loading ? (
        <Loading text="Loading your agents…" />
      ) : displayedAgents.length ? (
        <div className="account-agents-grid">
          {displayedAgents.map((agent) => (
            <Card
              as="section"
              className="account-panel account-agent-card"
              key={agent.agent_id}
              id={`agent-${agent.agent_id}`}
            >
              <div className="account-agent-heading">
                <Avatar className="account-agent-avatar">
                  <AvatarFallback>
                    <Icon name="agent" size={22} />
                  </AvatarFallback>
                </Avatar>
                <div>
                  <h2>{agent.name}</h2>
                  <p>Expires {localDate(agent.expires_at)}</p>
                </div>
                <Status value={agent.status} />
              </div>
              <div className="account-allowance-heading">
                <span>Remaining allowance</span>
                <strong>
                  {money(agent.remaining_cents)}
                  <small> / {money(agent.spend_limit_cents)}</small>
                </strong>
              </div>
              <Progress
                className="account-allowance-progress"
                value={Math.min(
                  agent.spent_cents + agent.reserved_cents,
                  agent.spend_limit_cents,
                )}
                max={agent.spend_limit_cents}
                aria-label={`${agent.name} allowance used`}
              />
              <div className="account-agent-spend">
                <span>
                  Spent <strong>{money(agent.spent_cents)}</strong>
                </span>
                <span>
                  Pending <strong>{money(agent.reserved_cents)}</strong>
                </span>
              </div>
              <div className="account-credential-heading">
                <h3>Access keys</h3>
                <Button
                  variant="link"
                  size="sm"
                  className="account-link-button"
                  disabled={
                    Boolean(busy) ||
                    !["active", "revoked"].includes(agent.status) ||
                    account.status !== "active" ||
                    new Date(agent.expires_at).getTime() <= Date.now()
                  }
                  onClick={() => issue(agent)}
                >
                  {busy === agent.agent_id ? "Creating key…" : "Create key"}
                </Button>
              </div>
              {agent.credentials.length ? (
                <ul className="account-credentials">
                  {agent.credentials.map((key) => (
                    <li key={key.credential_id}>
                      <div>
                        <code>{key.credential_id}</code>
                        <span>
                          {key.revoked
                            ? "Revoked"
                            : new Date(key.expires_at).getTime() <= Date.now()
                              ? "Expired"
                              : `Created ${localDate(key.created_at)}`}
                        </span>
                      </div>
                      {!key.revoked && (
                        <Button
                          variant="link"
                          size="sm"
                          className="account-revoke"
                          disabled={Boolean(busy)}
                          onClick={() =>
                            revoke(agent.agent_id, key.credential_id)
                          }
                        >
                          {busy === key.credential_id ? "Revoking…" : "Revoke"}
                        </Button>
                      )}
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="account-helper">
                  No keys yet. Create a key to connect this agent.
                </p>
              )}
              {agent.status === "exhausted" && (
                <p className="account-inline-warning">
                  This allowance is used up. Create a new agent to authorize
                  additional spending.
                </p>
              )}
            </Card>
          ))}
        </div>
      ) : (
        agents.data && (
          <Card as="section" className="account-panel">
            <Empty icon="agent" title="An agent’s first step starts with you">
              <p>
                Create an allowance for a task or an assistant, then connect
                your LLM. You can discover services before adding money.
              </p>
              <Button
                variant="default"
                className="button"
                onClick={() => setCreate(true)}
                disabled={account.status !== "active"}
              >
                Create your first agent
              </Button>
            </Empty>
          </Card>
        )
      )}
      {nextCursor && (
        <div className="account-load-more">
          <Button
            variant="outline"
            size="sm"
            className="account-secondary"
            disabled={loadingMore}
            onClick={loadMoreAgents}
          >
            {loadingMore ? "Loading…" : "Load more agents"}
          </Button>
        </div>
      )}
      <Card
        as="section"
        id="connect"
        className="account-panel account-instructions-panel"
      >
        <ConnectionInstructions />
      </Card>
      {create && (
        <CreateAgent onClose={() => setCreate(false)} onCreated={created} />
      )}{" "}
      {credential && (
        <NewCredential
          credential={credential}
          onClose={() => setCredential(null)}
        />
      )}
    </>
  );
}
