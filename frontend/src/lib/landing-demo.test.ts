import { describe, expect, it } from "vitest";
import {
  demoProviders,
  demoStages,
  formatDemoCost,
  nextDemoStage,
} from "./landing-demo";
import temple from "../components/landing/temple-triangles.json";

describe("illustrative landing walkthrough", () => {
  it("formats example costs as dollar amounts with two decimal places", () => {
    expect(
      demoProviders.map((provider) =>
        formatDemoCost(provider.exampleCostCents),
      ),
    ).toEqual(["$0.02", "$0.05", "$0.02"]);
    expect(formatDemoCost(10)).toBe("$0.10");
    expect(formatDemoCost(100)).toBe("$1.00");
  });
  it("shows three local provider logos with explicitly modeled example costs", () => {
    expect(demoProviders.map((provider) => provider.name)).toEqual([
      "Exa",
      "ElevenLabs",
      "Firecrawl",
    ]);
    for (const provider of demoProviders) {
      expect(provider.logo).toBe(`/images/providers/${provider.id}.svg`);
      expect(Number.isInteger(provider.exampleCostCents)).toBe(true);
      expect(provider.exampleCostCents).toBeGreaterThan(0);
    }
    expect(demoProviders.map((provider) => provider.exampleCostCents)).toEqual([
      2, 5, 2,
    ]);
  });
  it("plays in order and settles on the result instead of endlessly looping", () => {
    expect(demoStages.map((stage) => stage.id)).toEqual([
      "intent",
      "budget",
      "work",
    ]);
    expect([0, 1, 2].map(nextDemoStage)).toEqual([1, 2, 2]);
  });
  it("ships the 1,000 real Primitive triangles with reproducible provenance", () => {
    expect(temple.generator).toBe("fogleman/primitive@0373c216458b");
    expect(temple.triangles).toHaveLength(1000);
    for (const triangle of temple.triangles) {
      expect(triangle.points.trim().split(/\s+/)).toHaveLength(3);
      expect(
        triangle.points
          .split(/[\s,]+/)
          .every((point) => Number.isFinite(Number(point))),
      ).toBe(true);
      expect(triangle.fill).toMatch(/^#[a-f0-9]{6}$/i);
      expect(triangle.opacity).toBeGreaterThan(0);
      expect(triangle.opacity).toBeLessThanOrEqual(1);
    }
  });
});
