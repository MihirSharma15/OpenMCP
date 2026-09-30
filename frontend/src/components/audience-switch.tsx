"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";

const audiences = [
  {
    id: "agents",
    label: "For agents",
    title: "One connection. More possibilities.",
    description: "Give your agent access to useful APIs through one connection and one wallet. Find the right data, pay per request, and keep working.",
    benefits: [
      ["Discover with a goal", "Find relevant services and see their prices before you buy."],
      ["Keep spending in bounds", "Set a budget and a price limit for each request. Your agent works within them."],
      ["Skip the repeated setup", "Access services through OpenMCP without managing a separate account and API key for each one."],
    ],
  },
  {
    id: "apis",
    label: "For APIs",
    title: "Your API. An audience of agents.",
    description: "Make your data available where agents look for it. Turn your existing API into a pay-per-call service and earn whenever it is used.",
    benefits: [
      ["Get discovered", "Make your service discoverable to agents looking for the capabilities you offer."],
      ["Keep your existing API", "Add a payment-gated wrapper around your endpoints, using the service you already built."],
      ["Earn per request", "Receive payments in your provider wallet and follow every receipt from your dashboard."],
    ],
  },
];

export default function AudienceSwitch() {
  const [selected, setSelected] = useState(0);
  const tabs = useRef<(HTMLButtonElement | null)[]>([]);

  useEffect(() => {
    function syncHash() {
      if (window.location.hash === "#services") setSelected(1);
      if (window.location.hash === "#how") setSelected(0);
    }
    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);

  function select(index: number) {
    setSelected(index);
    // Keep existing section links useful after changing the selected audience.
    window.history.replaceState(window.history.state, "", index === 1 ? "#services" : "#how");
  }

  function handleKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    let next: number;
    if (event.key === "ArrowRight" || event.key === "ArrowLeft") next = 1 - index;
    else if (event.key === "Home") next = 0;
    else if (event.key === "End") next = 1;
    else return;
    event.preventDefault();
    select(next);
    tabs.current[next]?.focus();
  }

  return (
    <section id="how" className="audience-section container section-space" aria-label="OpenMCP for agents and APIs">
      <div id="services" className="audience-switch" role="tablist" aria-label="Choose your audience">
        <span className="audience-switch-thumb" style={{ transform: `translateX(${selected * 100}%)` }} aria-hidden="true" />
        {audiences.map((audience, index) => (
          <button
            key={audience.id}
            ref={element => { tabs.current[index] = element; }}
            type="button"
            role="tab"
            id={`audience-tab-${audience.id}`}
            aria-controls={`audience-panel-${audience.id}`}
            aria-selected={selected === index}
            tabIndex={selected === index ? 0 : -1}
            onClick={() => select(index)}
            onKeyDown={event => handleKeyDown(event, index)}
          >{audience.label}</button>
        ))}
      </div>
      <div className="audience-panels">
        {audiences.map((audience, index) => (
          <div
            key={audience.id}
            id={`audience-panel-${audience.id}`}
            role="tabpanel"
            aria-labelledby={`audience-tab-${audience.id}`}
            tabIndex={0}
            hidden={selected !== index}
            className={`audience-panel audience-panel-${audience.id}`}
          >
            <div className="audience-intro">
              <h2>{audience.title}</h2>
              <p>{audience.description}</p>
            </div>
            <ul className="audience-benefits">
              {audience.benefits.map(([title, description], benefitIndex) => (
                <li key={title}>
                  <span className="audience-number" aria-hidden="true">0{benefitIndex + 1}</span>
                  <h3>{title}</h3>
                  <p>{description}</p>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
