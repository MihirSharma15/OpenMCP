"use client";

import type { ReactNode } from "react";
import { useAnimationVisibility } from "./use-animation-visibility";

export function AmbientScene({ children }: { children: ReactNode }) {
  const { ref, canAnimate } = useAnimationVisibility<HTMLDivElement>();

  return (
    <div ref={ref} className="temple-scene" data-running={canAnimate}>
      <div className="temple-art" aria-hidden="true">
        {children}
      </div>
    </div>
  );
}
