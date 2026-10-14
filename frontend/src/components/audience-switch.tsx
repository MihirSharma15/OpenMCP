"use client";

import { useEffect, useState } from "react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

const audiences = [
  {
    id: "agents",
    label: "For agents",
    title: "One connection. More possibilities.",
    description:
      "Give your agent access to useful APIs through one connection and one wallet. Find the right data, pay per request, and keep working.",
    benefits: [
      [
        "Discover with a goal",
        "Find relevant services and see their prices before you buy.",
      ],
      [
        "Keep spending in bounds",
        "Set a budget and a price limit for each request. Your agent works within them.",
      ],
      [
        "Skip the repeated setup",
        "Access services through OpenMCP without managing a separate account and API key for each one.",
      ],
    ],
  },
  {
    id: "apis",
    label: "For APIs",
    title: "Your API. An audience of agents.",
    description:
      "OpenMCP connects agents to registered pay-per-call services. Each service has clear inputs, a listed price, and a payment destination.",
    benefits: [
      [
        "Clear capabilities",
        "Agents discover registered services by what they do and review the required inputs.",
      ],
      [
        "Upfront pricing",
        "The listed price includes the platform fee. Agents approve a maximum before each purchase.",
      ],
      [
        "Payments with receipts",
        "Providers receive MPP payments. Customers can follow purchase status and receipts in their account.",
      ],
    ],
  },
];

export default function AudienceSwitch() {
  const [selected, setSelected] = useState("agents");

  useEffect(() => {
    function syncHash() {
      if (window.location.hash === "#services") setSelected("apis");
      if (window.location.hash === "#how") setSelected("agents");
    }
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);

  function select(value: string) {
    setSelected(value);
    // Keep existing section links useful after changing the selected audience.
    window.history.replaceState(
      window.history.state,
      "",
      value === "apis" ? "#services" : "#how",
    );
  }

  return (
    <section
      id="how"
      className="audience-section container section-space"
      aria-label="OpenMCP for agents and APIs"
    >
      <div className="eyebrow audience-section-label">
        BOTH SIDES OF THE CONNECTION
      </div>
      <Tabs value={selected} onValueChange={select} className="audience-tabs">
        <TabsList
          id="services"
          className="audience-switch"
          aria-label="Choose your audience"
        >
          {audiences.map((audience) => (
            <TabsTrigger key={audience.id} value={audience.id}>
              {audience.label}
            </TabsTrigger>
          ))}
        </TabsList>
        <div className="audience-panels">
          {audiences.map((audience) => (
            <TabsContent
              key={audience.id}
              value={audience.id}
              forceMount
              aria-hidden={selected !== audience.id}
              inert={selected !== audience.id}
              tabIndex={selected === audience.id ? 0 : -1}
              className={`audience-panel audience-panel-${audience.id}`}
            >
              <div className="audience-intro">
                <h2>{audience.title}</h2>
                <p>{audience.description}</p>
              </div>
              <ul className="audience-benefits">
                {audience.benefits.map(([title, description]) => (
                  <li key={title}>
                    <h3>{title}</h3>
                    <p>{description}</p>
                  </li>
                ))}
              </ul>
            </TabsContent>
          ))}
        </div>
      </Tabs>
    </section>
  );
}
