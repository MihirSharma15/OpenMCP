"use client";

import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";
import { useReducedMotion } from "motion/react";
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { earningsSeries, isReceived, type Period } from "@/lib/providers";
import { money } from "@/lib/demo";
import type { ProviderTransaction } from "@/lib/openmcp";

export function EarningsChart({
  transactions,
  period,
  now,
  loaded,
}: {
  transactions: ProviderTransaction[];
  period: Period;
  now: number;
  loaded: boolean;
}) {
  const reducedMotion = useReducedMotion();
  const series = loaded ? earningsSeries(transactions, period, now) : [];
  const hasPayments = transactions.some(isReceived);
  return (
    <div className="provider-chart">
      <div className="provider-chart-caption">
        <span>
          <i />
          Net provider earnings
        </span>
        <span>USD</span>
      </div>
      <div className="provider-chart-frame">
        <ChartContainer
          config={{
            cents: { label: "Net earnings", color: "var(--lavender)" },
          }}
          className="h-[200px] w-full aspect-auto"
          aria-label="Net provider earnings over time"
        >
          <BarChart
            accessibilityLayer
            data={series}
            margin={{ left: -12, right: 8, top: 8 }}
          >
            <CartesianGrid vertical={false} strokeDasharray="3 4" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tickMargin={10}
              minTickGap={40}
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              tickFormatter={(value) => money(value)}
              domain={[
                0,
                (max: number) => Math.max(100, Math.ceil(max / 100) * 100),
              ]}
              width={52}
              tickCount={4}
            />
            <ChartTooltip
              cursor={{ fill: "var(--tint)" }}
              content={
                <ChartTooltipContent
                  formatter={(value) => (
                    <span className="font-mono">
                      {money(Number(value))} USD
                    </span>
                  )}
                />
              }
            />
            <Bar
              dataKey="cents"
              fill="var(--color-cents)"
              radius={[4, 4, 0, 0]}
              maxBarSize={36}
              isAnimationActive={!reducedMotion}
            />
          </BarChart>
        </ChartContainer>
        {!hasPayments && (
          <div className="provider-chart-empty">
            <span>
              {loaded
                ? "Your next payment starts here"
                : "Connecting to your earnings"}
            </span>
            <p>
              {loaded
                ? "Confirmed payments will appear automatically."
                : "Reading your provider ledger…"}
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
