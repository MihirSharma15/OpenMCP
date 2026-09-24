import assert from "node:assert/strict";
import test from "node:test";
import { earningsSeries, isReceived, paymentTime, paymentsCsv, periodStart, scopedTransactions } from "../src/lib/providers.ts";
import type { ProviderOverview, ProviderTransaction } from "../src/lib/openmcp.ts";

const now = new Date(2026, 8, 23, 14).getTime();
const paidAt = now / 1000;
function transaction(values: Partial<ProviderTransaction> = {}): ProviderTransaction {
  return {
    execution_id: "exec_example", session_id: "session_example", status: "completed",
    endpoint_id: "operations", provider: "SupplySignal", currency: "pathUSD",
    price_cents: 40, platform_fee_cents: 4, provider_amount_cents: 36,
    agent_to_openmcp: { status: "success", reference: "0xincoming" },
    openmcp_to_provider: { status: "success", reference: "0xoutgoing" },
    error: null, replayed: false, payment_mode: "mpp_tempo_testnet",
    created_at: paidAt - 10, paid_at: paidAt, ...values,
  };
}

test("earnings require a verified outgoing receipt, independently of fulfillment", () => {
  assert.equal(isReceived(transaction({ openmcp_to_provider: null })), false);
  assert.equal(isReceived(transaction({ openmcp_to_provider: { status: "success" } })), false);
  assert.equal(isReceived(transaction({ openmcp_to_provider: { status: "failed", reference: "0x" } })), false);
  assert.equal(isReceived(transaction({ status: "provider_pending" })), true);
});

test("reporting periods include the whole local starting day and scope the provider", () => {
  const start = new Date(2026, 8, 17).getTime() / 1000;
  assert.equal(periodStart("7", now), start);
  const data = { transactions: [
    transaction({ execution_id: "inside", paid_at: start }),
    transaction({ execution_id: "outside", paid_at: start - 1 }),
    transaction({ execution_id: "other", endpoint_id: "legal" }),
  ] } as ProviderOverview;
  assert.deepEqual(scopedTransactions(data, "operations", "7", now).map(row => row.execution_id), ["inside"]);
  assert.equal(scopedTransactions(data, "all", "all", now).length, 3);
});

test("chart buckets preserve exact net totals and exclude unpaid requests", () => {
  const rows = [transaction(), transaction({ provider_amount_cents: 45 }), transaction({ openmcp_to_provider: null })];
  const series = earningsSeries(rows, "7", now);
  assert.equal(series.length, 7);
  assert.equal(series.reduce((sum, point) => sum + point.cents, 0), 81);
  assert.equal(series.at(-1)?.cents, 81);
  assert.equal(earningsSeries([], "all", now).length, 7);
});

test("chart keeps a long history within 30 buckets without dropping earnings", () => {
  const rows = [transaction({ paid_at: paidAt - 200 * 86400 }), transaction()];
  const series = earningsSeries(rows, "all", now);
  assert.ok(series.length <= 30);
  assert.equal(series.reduce((sum, point) => sum + point.cents, 0), 72);
});

test("legacy receipts provide the payment date when no event is available", () => {
  assert.equal(paymentTime(transaction({ paid_at: null, openmcp_to_provider: { timestamp: "2026-09-22T12:00:00Z" } })), Date.parse("2026-09-22T12:00:00Z") / 1000);
  assert.equal(paymentTime(transaction({ paid_at: null, openmcp_to_provider: null })), paidAt - 10);
});

test("CSV escapes provider text and never exports pending amounts as received", () => {
  const csv = paymentsCsv([
    transaction({ provider: '=HYPERLINK("example")' }),
    transaction({ provider: 'A, "B"', openmcp_to_provider: null, paid_at: null, status: "provider_pending" }),
  ]);
  assert.ok(csv.includes('"\'=HYPERLINK(""example"")"'));
  assert.ok(csv.includes('"A, ""B"""'));
  assert.ok(csv.includes('"0.40","0.04","0.36","0xoutgoing"'));
  assert.ok(csv.includes('"Pending","0.40","","","","0xincoming"'));
});
