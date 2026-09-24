"use client";

// Adapted from Magic UI's Number Ticker (MIT).
// https://magicui.design/r/number-ticker.json
// Local changes: inherited styling, accessible settled values, reduced motion,
// and stable text nodes so polling never restarts an in-progress animation.
import { useEffect, useMemo, useRef, type ComponentPropsWithoutRef } from "react";
import { useInView, useMotionValue, useReducedMotion, useSpring } from "motion/react";

interface NumberTickerProps extends Omit<ComponentPropsWithoutRef<"span">, "children"> {
  value: number;
  startValue?: number;
  direction?: "up" | "down";
  delay?: number;
  decimalPlaces?: number;
}

export function NumberTicker({
  value,
  startValue = 0,
  direction = "up",
  delay = 0,
  decimalPlaces = 0,
  className = "",
  ...props
}: NumberTickerProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const initialValue = useRef(direction === "down" ? value : startValue);
  const motionValue = useMotionValue(initialValue.current);
  const springValue = useSpring(motionValue, { damping: 60, stiffness: 100 });
  const isInView = useInView(ref, { once: true, margin: "0px" });
  const reducedMotion = useReducedMotion();
  const target = direction === "down" ? startValue : value;
  const formatter = useMemo(() => new Intl.NumberFormat("en-US", {
    minimumFractionDigits: decimalPlaces,
    maximumFractionDigits: decimalPlaces,
  }), [decimalPlaces]);

  useEffect(() => {
    const update = (latest: number) => {
      if (ref.current) ref.current.textContent = formatter.format(Number(latest.toFixed(decimalPlaces)));
    };
    update(springValue.get());
    return springValue.on("change", update);
  }, [springValue, formatter, decimalPlaces]);

  useEffect(() => {
    if (reducedMotion) {
      motionValue.set(target);
      springValue.jump(target);
      return;
    }
    if (!isInView) return;
    const timer = setTimeout(() => motionValue.set(target), delay * 1000);
    return () => clearTimeout(timer);
  }, [motionValue, springValue, isInView, reducedMotion, delay, target]);

  return (
    <span className={`number-ticker ${className}`} {...props}>
      <span ref={ref} aria-hidden="true">{formatter.format(initialValue.current)}</span>
      <span className="number-ticker-accessible">{formatter.format(target)}</span>
    </span>
  );
}
