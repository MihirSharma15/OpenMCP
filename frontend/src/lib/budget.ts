export const MIN_BUDGET_CENTS = 1;
export const DEFAULT_BUDGET_CENTS = 1500;

export type BudgetParseResult =
  | { valid: true; cents: number; formatted: string }
  | { valid: false; message: string };

const DECIMAL_AMOUNT = /^\d+(?:\.\d{0,2})?$/;

export function formatBudgetInput(cents: number): string {
  return (cents / 100).toFixed(2);
}

export function clampBudgetCents(cents: number): number {
  return Math.max(MIN_BUDGET_CENTS, Math.round(cents));
}

export function parseBudgetInput(value: string): BudgetParseResult {
  const input = value.trim();
  if (!input) {
    return { valid: false, message: "Enter a positive amount." };
  }
  if (!DECIMAL_AMOUNT.test(input)) {
    return { valid: false, message: "Use a number with no more than two decimal places." };
  }

  const amount = Number(input);
  const cents = Math.round(amount * 100);
  if (!Number.isFinite(amount) || amount <= 0 || !Number.isSafeInteger(cents) || cents < 1) {
    return { valid: false, message: "Amount must be a positive number." };
  }

  return { valid: true, cents, formatted: formatBudgetInput(cents) };
}
