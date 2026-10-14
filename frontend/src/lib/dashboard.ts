import type { Agent, Page, Transaction } from "./account";

export type SpendPeriod = 7 | 30;

export function periodStart(now: number, days: SpendPeriod) {
  const start = new Date(now);
  start.setHours(0, 0, 0, 0);
  start.setDate(start.getDate() - days + 1);
  return start;
}

const dayKey = (date: Date) =>
  `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;

/** Only completed purchases are spending. A returned reservation isn't revenue. */
export function spendingSummary(
  rows: Transaction[],
  days: SpendPeriod,
  now: number,
) {
  const start = periodStart(now, days);
  const series = Array.from({ length: days }, (_, index) => {
    const date = new Date(start);
    date.setDate(date.getDate() + index);
    return {
      key: dayKey(date),
      label: date.toLocaleDateString("en-US", {
        month: "short",
        day: "numeric",
      }),
      cents: 0,
      purchases: 0,
    };
  });
  const buckets = new Map(series.map((day) => [day.key, day]));
  const uniqueRows = new Map(rows.map((row) => [row.id, row]));
  for (const row of uniqueRows.values()) {
    const date = new Date(row.created_at);
    if (
      row.type !== "purchase" ||
      row.status !== "completed" ||
      row.amount_cents >= 0 ||
      date.getTime() > now
    )
      continue;
    const day = buckets.get(dayKey(date));
    if (day) {
      day.cents += -row.amount_cents;
      day.purchases += 1;
    }
  }
  return {
    series,
    cents: series.reduce((sum, day) => sum + day.cents, 0),
    purchases: series.reduce((sum, day) => sum + day.purchases, 0),
  };
}

// The API supplies newest-first pages. Never label a partial page as a full report.
export function hasCompletePeriod(
  page: Page<Transaction>,
  days: SpendPeriod,
  now: number,
) {
  if (!page.next_cursor) return true;
  const dates = page.items
    .map((row) => new Date(row.created_at).getTime())
    .filter(Number.isFinite);
  return (
    dates.length > 0 && Math.min(...dates) < periodStart(now, days).getTime()
  );
}

export function canAgentSpend(agent: Agent, now: number) {
  return (
    agent.status === "active" &&
    agent.remaining_cents > 0 &&
    new Date(agent.expires_at).getTime() > now
  );
}

export function filterActivity(
  rows: Transaction[],
  type: string,
  search: string,
) {
  const query = search.trim().toLowerCase();
  return rows.filter(
    (row) =>
      (type === "all" || row.type === type) &&
      (!query ||
        [row.description, row.agent_name, row.id, row.endpoint_id].some(
          (value) => value?.toLowerCase().includes(query),
        )),
  );
}
