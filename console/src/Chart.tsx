// A container's requests, Sizing and usage basis over time (uPlot: canvas, no markup
// from data; uPlot styles its elements through the DOM, which the CSP allows).
import { useEffect, useRef } from "react";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import type { Point } from "./api";
import { type Res, series } from "./series";

const UNIT = { cpu: "m", memory: "Mi" };

export default function Chart({ points, res }: { points: Point[]; res: Res }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!box.current) return;
    const plot = new uPlot(
      {
        width: Math.max(320, box.current.clientWidth),
        height: 220,
        scales: { x: { time: true } },
        axes: [{}, { size: 70, values: (_u, ticks) => ticks.map((t) => `${t}${UNIT[res]}`) }],
        series: [
          {},
          { label: "request", stroke: "#888", width: 2 },
          { label: "Sizing", stroke: "#2a7", width: 2 },
          { label: res === "cpu" ? "p95 (basis)" : "peak (basis)", stroke: "#36c", dash: [4, 4] },
        ],
      },
      series(points, res),
      box.current,
    );
    return () => plot.destroy();
  }, [points, res]);
  return <div className="chart" ref={box} aria-label={`${res} over time`} />;
}
