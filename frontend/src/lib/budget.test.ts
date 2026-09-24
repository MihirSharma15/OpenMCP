import { describe, expect, it } from "vitest";
import { clampBudgetCents, formatBudgetInput, parseBudgetInput } from "./budget";

describe("parseBudgetInput", () => {
  it.each([
    ["0.01", 1, "0.01"],
    ["4.27", 427, "4.27"],
    ["15", 1500, "15.00"],
    ["15.00", 1500, "15.00"],
    ["15.01", 1501, "15.01"],
    ["20", 2000, "20.00"],
    [" 2.5 ", 250, "2.50"],
  ])("accepts %s", (input, cents, formatted) => {
    expect(parseBudgetInput(input)).toEqual({ valid: true, cents, formatted });
  });

  it.each(["", "0", "0.00", "-0.01", "1.001", "hello", "1e2", ".50"])(
    "rejects %s",
    input => {
      expect(parseBudgetInput(input).valid).toBe(false);
    },
  );
});

describe("formatBudgetInput", () => {
  it("always formats cents with two decimal places", () => {
    expect(formatBudgetInput(1)).toBe("0.01");
    expect(formatBudgetInput(1500)).toBe("15.00");
    expect(formatBudgetInput(2000)).toBe("20.00");
  });
});

describe("clampBudgetCents", () => {
  it("keeps entered values positive without an upper cap", () => {
    expect(clampBudgetCents(-1)).toBe(1);
    expect(clampBudgetCents(0)).toBe(1);
    expect(clampBudgetCents(427.4)).toBe(427);
    expect(clampBudgetCents(1501)).toBe(1501);
    expect(clampBudgetCents(50_000)).toBe(50_000);
  });
});
