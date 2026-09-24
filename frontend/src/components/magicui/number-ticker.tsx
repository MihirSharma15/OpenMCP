"use client";

import { useMotionValue, useReducedMotion, useSpring } from "motion/react";
import {
  type ComponentPropsWithoutRef,
  useEffect,
  useMemo,
  useRef,
} from "react";

interface NumberTickerProps extends ComponentPropsWithoutRef<"span"> {
  value: number;
  startValue?: number;
  direction?: "up" | "down";
  delay?: number;
  decimalPlaces?: number;
}

// Adapted from Magic UI's Number Ticker:
// https://magicui.design/docs/components/number-ticker
export function NumberTicker({
  value,
  startValue = 0,
  direction = "up",
  delay = 0,
  decimalPlaces = 0,
  className,
  "aria-label": ariaLabel,
  ...props
}: NumberTickerProps) {
  const ref = useRef<HTMLSpanElement>(null);
  const initialValue = direction === "down" ? value : startValue;
  const initialValueRef = useRef(initialValue);
  const targetValue = direction === "down" ? startValue : value;
  const motionValue = useMotionValue(initialValueRef.current);
  const springValue = useSpring(motionValue, {
    damping: 60,
    stiffness: 100,
  });
  const shouldReduceMotion = useReducedMotion();
  const formatter = useMemo(
    () =>
      new Intl.NumberFormat("en-US", {
        minimumFractionDigits: decimalPlaces,
        maximumFractionDigits: decimalPlaces,
      }),
    [decimalPlaces],
  );

  useEffect(
    () =>
      springValue.on("change", latest => {
        if (ref.current) {
          ref.current.textContent = formatter.format(
            Number(latest.toFixed(decimalPlaces)),
          );
        }
      }),
    [decimalPlaces, formatter, springValue],
  );

  useEffect(() => {
    if (
      motionValue.get() === targetValue &&
      springValue.get() === targetValue
    ) {
      return;
    }

    const timer = window.setTimeout(() => {
      if (shouldReduceMotion) {
        motionValue.jump(targetValue);
        springValue.jump(targetValue);
        return;
      }
      motionValue.set(targetValue);
    }, delay * 1000);

    return () => window.clearTimeout(timer);
  }, [
    delay,
    motionValue,
    shouldReduceMotion,
    springValue,
    targetValue,
  ]);

  return (
    <span
      {...props}
      className={["number-ticker", className].filter(Boolean).join(" ")}
      aria-label={ariaLabel ?? formatter.format(targetValue)}
    >
      <span ref={ref} aria-hidden="true">
        {formatter.format(initialValueRef.current)}
      </span>
    </span>
  );
}
