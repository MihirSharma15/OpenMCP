/** Illustrative only. No account data, endpoints, or payment requests. */
export const DEMO_ALLOWANCE_CENTS = 2500;
export const DEMO_STAGE_DURATION_MS = 3400;

export const demoStages = [
  {
    id: "intent",
    label: "Set a task",
    detail: "Start with what you need.",
  },
  {
    id: "budget",
    label: "Set a budget",
    detail: "You choose the limit.",
  },
  {
    id: "work",
    label: "Let it work",
    detail: "It finds services. It pays. It delivers.",
  },
] as const;

// Official wordmarks, stored locally to avoid third-party requests in the demo.
// Sources: exa.ai/brand, elevenlabs.io, firecrawl.dev.
// Provider logos are illustrative, not live integration or availability status.
// Example costs are demo values, not live provider quotes.
export const demoProviders = [
  {
    id: "exa",
    name: "Exa",
    logo: "/images/providers/exa.svg",
    width: 80,
    height: 25,
    exampleCostCents: 2,
  },
  {
    id: "elevenlabs",
    name: "ElevenLabs",
    logo: "/images/providers/elevenlabs.svg",
    width: 126,
    height: 16,
    exampleCostCents: 5,
  },
  {
    id: "firecrawl",
    name: "Firecrawl",
    logo: "/images/providers/firecrawl.svg",
    width: 105,
    height: 20,
    exampleCostCents: 2,
  },
] as const;

export function nextDemoStage(stage: number) {
  return Math.min(stage + 1, demoStages.length - 1);
}
