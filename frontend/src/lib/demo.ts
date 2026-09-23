export const LAST_STEP = 12;
const BUDGET = 1500;

export const services = [
  { id: "ops", name: "Operational health", provider: "Meridian Freight Data", endpoint: "/v1/carriers/ops", price: 400, req: "req_7f3a", text: "On-time performance has slipped over the last four quarters, concentrated in two Midwest lanes. Ageing tractors and driver turnover are the main operational risks." },
  { id: "legal", name: "Legal liabilities", provider: "Docketline", endpoint: "/v1/filings/search", price: 600, req: "req_91c2", text: "Two open matters: a wage-and-hour class action in California and an environmental notice tied to the Joliet yard. No judgments on record." },
  { id: "mkt", name: "Competitor market share", provider: "Tidemark Analytics", endpoint: "/v1/markets/share", price: 300, req: "req_c05e", text: "FreightFlow sits mid-pack in regional LTL, behind two national carriers. Pricing pressure is strongest on its highest-volume lanes." },
];

// The supplied design is a local simulation. All amounts are kept in cents.
export function money(cents: number) { return `$${(cents / 100).toFixed(2)}`; }

export function getDemoState(step: number) {
  const rows = services.map((service, index) => {
    const base = 3 + index * 3;
    const delivered = step >= base + 2;
    return {
      ...service,
      status: step < base ? "Quoted" : step === base ? "Paying" : step === base + 1 ? "Receiving" : "Delivered",
      delivered,
      fresh: step === base + 2,
      active: step === base || step === base + 1,
      fee: Math.round(service.price * .05),
      earned: delivered ? service.price - Math.round(service.price * .05) : 0,
    };
  });
  const ledger = rows.filter(row => row.delivered).reverse();
  const spent = ledger.reduce((sum, row) => sum + row.price, 0);
  const fees = ledger.reduce((sum, row) => sum + row.fee, 0);
  const remaining = BUDGET - spent;
  const current = step >= 3 && step <= 11 ? Math.floor((step - 3) / 3) : -1;
  const phase = step >= 3 && step <= 11 ? (step - 3) % 3 : -1;
  const stageIndex = step === 0 ? -1 : step <= 2 ? 0 : step === LAST_STEP ? 3 : phase === 0 ? 1 : 2;
  let actionTitle = "Waiting for the agent";
  let actionTag = "Ready";
  let actionCode = "Press Run demo to hand the agent its task.";
  if (step === 1) {
    actionTitle = "Searching for matching services";
    actionTag = "Discovering";
    actionCode = 'POST /discover\n{ "query": "FreightFlow due diligence", "budget": 15.00 }';
  } else if (step === 2) {
    actionTitle = "Three services match, $13.00 total";
    actionTag = "Quoted";
    actionCode = "200 OK  3 endpoints · each with a price and pay_to wallet";
  } else if (step === LAST_STEP) {
    actionTitle = "Report ready";
    actionTag = "Complete";
    actionCode = 'GET /balance\n200 OK  { "remaining": 2.00 }';
  } else if (current >= 0) {
    const service = rows[current];
    actionTag = `Service ${current + 1} of 3`;
    if (phase === 0) {
      actionTitle = `Paying for ${service.name.toLowerCase()}`;
      actionCode = `POST /execute\n{ "endpoint": "${service.endpoint}", "amount": ${(service.price / 100).toFixed(2)} }`;
    } else if (phase === 1) {
      actionTitle = `${service.provider} is returning data`;
      actionCode = `→ forwarded to ${service.provider}\n  awaiting response`;
    } else {
      actionTitle = `${service.name} delivered`;
      actionCode = `200 OK  settled ${money(service.price)} · provider ${money(service.earned)} · fee ${money(service.fee)}`;
    }
  }
  return { rows, ledger, spent, fees, remaining, stageIndex, actionTitle, actionTag, actionCode, discovered: step >= 2, complete: step === LAST_STEP };
}
