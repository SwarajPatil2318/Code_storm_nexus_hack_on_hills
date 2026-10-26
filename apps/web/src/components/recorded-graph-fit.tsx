"use client";
import { useEffect, useRef } from "react";
import { useNodesInitialized, useReactFlow } from "@xyflow/react";

// Fit on initial measurement and viewport resize, never on an event/replay tick.
// The mobile text overview remains available for labels too small to read at graph scale.
export function RecordedGraphFit() {
  const marker = useRef<HTMLSpanElement>(null);
  const initialized = useNodesInitialized();
  const { fitView } = useReactFlow();
  useEffect(() => {
    const canvas = marker.current?.closest(".react-flow");
    if (!canvas || !initialized) return;
    let frame = 0;
    const fit = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        void fitView({ padding: 0.12, minZoom: 0.1, maxZoom: 1, duration: 0 });
      });
    };
    const observer = new ResizeObserver(fit);
    observer.observe(canvas);
    fit();
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [initialized, fitView]);
  return <span ref={marker} aria-hidden="true" className="sr-only" />;
}
