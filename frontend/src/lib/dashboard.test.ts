import { describe, expect, it } from "vitest";
import {
  canAgentSpend,
  filterActivity,
  hasCompletePeriod,
  periodStart,
  spendingSummary,
} from "./dashboard";
import type { Agent, Transaction } from "./account";

const now = new Date(2026, 9, 13, 17).getTime();
const transaction = (patch: Partial<Transaction> = {}): Transaction => ({
  id: "one",
  type: "purchase",
  status: "completed",
  amount_cents: -123,
  currency: "usd_credits",
  description: "Web search",
  created_at: new Date(now).toISOString(),
  balance_after_cents: null,
  agent_id: "agent",
  agent_name: "Research assistant",
  endpoint_id: "web",
  execution_id: null,
  related_transaction_id: null,
  receipt_url: null,
  ...patch,
});

describe("dashboard financial summaries", () => {
  it("counts exact cents only for completed purchases, without double counting", () => {
    const purchase = transaction();
    const rows = [
      purchase,
      purchase,
      ...["pending", "failed", "refunded", "needs_review"].map(
        (status, index) =>
          transaction({
            id: String(index),
            status: status as Transaction["status"],
          }),
      ),
      transaction({ id: "deposit", type: "deposit", amount_cents: 1000 }),
      transaction({ id: "refund", type: "refund", amount_cents: 123 }),
      transaction({ id: "bad-sign", amount_cents: 99 }),
    ];
    expect(spendingSummary(rows, 7, now)).toMatchObject({
      cents: 123,
      purchases: 1,
    });
  });
  it("uses local calendar boundaries and excludes earlier and future transactions", () => {
    const start = periodStart(now, 7);
    const result = spendingSummary(
      [
        transaction({ id: "start", created_at: start.toISOString() }),
        transaction({
          id: "old",
          created_at: new Date(start.getTime() - 1).toISOString(),
        }),
        transaction({
          id: "future",
          created_at: new Date(now + 1).toISOString(),
        }),
        transaction({ id: "invalid", created_at: "invalid" }),
      ],
      7,
      now,
    );
    expect(result.cents).toBe(123);
    expect(result.series).toHaveLength(7);
    expect(result.series[0].cents).toBe(123);
    expect(spendingSummary([], 30, now).series).toHaveLength(30);
  });
  it("labels incomplete paginated history instead of claiming full-period totals", () => {
    expect(
      hasCompletePeriod(
        { items: [transaction()], next_cursor: "next" },
        7,
        now,
      ),
    ).toBe(false);
    expect(hasCompletePeriod({ items: [], next_cursor: "next" }, 7, now)).toBe(
      false,
    );
    expect(
      hasCompletePeriod({ items: [transaction()], next_cursor: null }, 7, now),
    ).toBe(true);
    expect(
      hasCompletePeriod(
        {
          items: [
            transaction({
              created_at: new Date(
                periodStart(now, 7).getTime() - 1,
              ).toISOString(),
            }),
          ],
          next_cursor: "next",
        },
        7,
        now,
      ),
    ).toBe(true);
  });
  it("filters by transaction type and searches names, IDs, and endpoints", () => {
    const rows = [
      transaction(),
      transaction({ id: "topup", type: "deposit", agent_name: null }),
    ];
    expect(filterActivity(rows, "purchase", " RESEARCH ")).toHaveLength(1);
    expect(filterActivity(rows, "all", "topup")[0].id).toBe("topup");
    expect(filterActivity(rows, "refund", "")).toEqual([]);
  });
  it("does not count expired, exhausted, or revoked agents as spend-ready", () => {
    const agent: Agent = {
      agent_id: "agent",
      name: "Agent",
      remaining_cents: 100,
      spend_limit_cents: 200,
      spent_cents: 100,
      reserved_cents: 0,
      status: "active",
      expires_at: new Date(now + 1000).toISOString(),
      credentials: [],
    };
    expect(canAgentSpend(agent, now)).toBe(true);
    expect(canAgentSpend({ ...agent, remaining_cents: 0 }, now)).toBe(false);
    expect(
      canAgentSpend({ ...agent, expires_at: new Date(now).toISOString() }, now),
    ).toBe(false);
    expect(canAgentSpend({ ...agent, status: "revoked" }, now)).toBe(false);
  });
});
