"use client";

import { useEffect, useState } from "react";
import { motion } from "motion/react";
import {
  ArrowUpRight,
  Bot,
  Ellipsis,
  Pause,
  Play,
  RotateCcw,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { NumberTicker } from "@/components/ui/number-ticker";
import {
  DEMO_ALLOWANCE_CENTS,
  DEMO_STAGE_DURATION_MS,
  demoProviders,
  demoStages,
  formatDemoCost,
  nextDemoStage,
} from "@/lib/landing-demo";
import { useAnimationVisibility } from "./use-animation-visibility";

export function ProductDemo() {
  const [stage, setStage] = useState(0);
  const [playing, setPlaying] = useState(true);
  const [run, setRun] = useState(0);
  const { ref, canAnimate, reducedMotion } =
    useAnimationVisibility<HTMLElement>();
  const complete = stage === demoStages.length - 1;
  const running = playing && canAnimate && !complete;
  const transition = {
    duration: reducedMotion ? 0 : 0.5,
    ease: [0.22, 1, 0.36, 1] as const,
  };

  useEffect(() => {
    if (!running) return;
    const timer = window.setTimeout(
      () => setStage(nextDemoStage),
      DEMO_STAGE_DURATION_MS,
    );
    return () => window.clearTimeout(timer);
  }, [stage, running, run]);

  function replay() {
    setStage(0);
    setRun((value) => value + 1);
    setPlaying(true);
  }

  return (
    <section
      ref={ref}
      id="in-action"
      className="product-story container"
      aria-labelledby="demo-title"
    >
      <h2 id="demo-title">See it in action</h2>

      <Tabs
        value={demoStages[stage].id}
        onValueChange={(id) => {
          const next = demoStages.findIndex((item) => item.id === id);
          if (next < 0) return;
          setStage(next);
          setPlaying(false);
        }}
        className="product-demo"
        data-running={running}
      >
        <TabsList
          variant="line"
          aria-label="How OpenMCP works"
          className="demo-steps"
          onFocusCapture={() => setPlaying(false)}
        >
          {demoStages.map((item, index) => (
            <TabsTrigger value={item.id} key={item.id} className="demo-step">
              <strong>{item.label}</strong>
              <span className="demo-step-detail">{item.detail}</span>
              <span className="demo-step-track" aria-hidden="true">
                {stage === index && (
                  <span
                    key={`${run}-${stage}-${running}`}
                    className="demo-step-progress"
                    style={{ animationDuration: `${DEMO_STAGE_DURATION_MS}ms` }}
                    data-complete={!running}
                  />
                )}
              </span>
            </TabsTrigger>
          ))}
        </TabsList>

        <div className="demo-scene">
          <TabsContent value="intent" className="demo-panel">
            <motion.div
              className="demo-task"
              initial={{ opacity: 0, y: reducedMotion ? 0 : 9 }}
              animate={{ opacity: 1, y: 0 }}
              transition={transition}
            >
              <span className="demo-caption">
                A little research, for example
              </span>
              <p>
                “Find the latest research
                <br />
                on battery recycling.”
              </p>
              <ArrowUpRight
                className="demo-task-arrow"
                strokeWidth={1.2}
                aria-hidden="true"
              />
            </motion.div>
          </TabsContent>

          <TabsContent value="budget" className="demo-panel">
            <motion.div
              className="demo-budget"
              initial={{ opacity: 0, y: reducedMotion ? 0 : 9 }}
              animate={{ opacity: 1, y: 0 }}
              transition={transition}
            >
              <span className="demo-caption">An allowance for your agent</span>
              <div className="demo-budget-amount">
                <span>$</span>
                <NumberTicker value={DEMO_ALLOWANCE_CENTS / 100} />
              </div>
              <p>
                <ShieldCheck size={15} strokeWidth={1.5} aria-hidden="true" />{" "}
                It can spend less. Never more.
              </p>
            </motion.div>
          </TabsContent>

          <TabsContent value="work" className="demo-panel">
            <motion.div
              className="demo-work"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={transition}
            >
              <div
                className="demo-service-flow"
                role="group"
                aria-label="Your agent connects to the OpenMCP wallet, then to the providers"
              >
                <div className="demo-agent demo-flow-node">
                  <Bot size={34} strokeWidth={1.2} aria-hidden="true" />
                  <span>Your agent</span>
                </div>
                <svg
                  className="demo-transfer"
                  viewBox="0 0 60 12"
                  preserveAspectRatio="none"
                  fill="none"
                  aria-hidden="true"
                >
                  <path d="M0 6H57M52 2L57 6L52 10" stroke="#e1dce5" />
                  <motion.path
                    d="M0 6H57M52 2L57 6L52 10"
                    stroke="#9687aa"
                    initial={{ pathLength: reducedMotion ? 1 : 0 }}
                    animate={{ pathLength: 1 }}
                    transition={{
                      duration: reducedMotion ? 0 : 0.45,
                      delay: reducedMotion ? 0 : 0.1,
                    }}
                  />
                </svg>
                <motion.div
                  className="demo-wallet demo-flow-node"
                  initial={{ opacity: 0, y: reducedMotion ? 0 : 3 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{
                    ...transition,
                    delay: reducedMotion ? 0 : 0.35,
                  }}
                >
                  <Wallet size={34} strokeWidth={1.2} aria-hidden="true" />
                  <span>OpenMCP</span>
                </motion.div>
                <svg
                  className="demo-branch"
                  viewBox="0 0 110 200"
                  preserveAspectRatio="none"
                  fill="none"
                  aria-hidden="true"
                >
                  <path
                    d="M0 100H35Q50 100 50 85V40Q50 25 65 25H110M50 75H110M35 100Q50 100 50 115V160Q50 175 65 175H110M50 125H110"
                    stroke="#e1dce5"
                  />
                  <motion.path
                    d="M0 100H35Q50 100 50 85V40Q50 25 65 25H110M50 75H110M35 100Q50 100 50 115V160Q50 175 65 175H110M50 125H110"
                    stroke="#9687aa"
                    initial={{ pathLength: reducedMotion ? 1 : 0 }}
                    animate={{ pathLength: 1 }}
                    transition={{
                      duration: reducedMotion ? 0 : 0.9,
                      delay: reducedMotion ? 0 : 0.65,
                    }}
                  />
                </svg>
                <div className="demo-services">
                  <span className="demo-cost-label">Example costs</span>
                  {demoProviders.map((provider, index) => (
                    <motion.div
                      key={provider.id}
                      className="demo-service"
                      initial={{ opacity: 0, x: reducedMotion ? 0 : -5 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{
                        ...transition,
                        delay: reducedMotion ? 0 : 0.9 + index * 0.3,
                      }}
                    >
                      <img
                        src={provider.logo}
                        alt={provider.name}
                        width={provider.width}
                        height={provider.height}
                        className="demo-provider-logo"
                      />
                      <span
                        className="demo-service-price"
                        aria-label={`Example cost: ${formatDemoCost(provider.exampleCostCents)}`}
                      >
                        {formatDemoCost(provider.exampleCostCents)}
                      </span>
                    </motion.div>
                  ))}
                  <motion.div
                    className="demo-service demo-more-providers"
                    initial={{ opacity: 0, x: reducedMotion ? 0 : -5 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{
                      ...transition,
                      delay: reducedMotion ? 0 : 1.8,
                    }}
                  >
                    <Ellipsis size={20} strokeWidth={1.4} aria-hidden="true" />
                    <span>More added every day</span>
                  </motion.div>
                </div>
              </div>
              <motion.div
                className="demo-outcome"
                initial={{ opacity: 0, y: reducedMotion ? 0 : 6 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ ...transition, delay: reducedMotion ? 0 : 2 }}
              >
                <p>
                  <span>No API keys.</span> <span>No extra sign-ups.</span>
                </p>
              </motion.div>
            </motion.div>
          </TabsContent>
        </div>
      </Tabs>

      <div className="demo-playback">
        {reducedMotion ? (
          <span>Select a step to explore.</span>
        ) : (
          <Button
            variant="ghost"
            size="sm"
            onClick={complete ? replay : () => setPlaying((value) => !value)}
            aria-label={
              complete
                ? "Replay walkthrough"
                : playing
                  ? "Pause walkthrough"
                  : "Play walkthrough"
            }
          >
            {complete ? <RotateCcw /> : playing ? <Pause /> : <Play />}
            {complete ? "Replay" : playing ? "Pause" : "Play"}
          </Button>
        )}
      </div>
    </section>
  );
}
