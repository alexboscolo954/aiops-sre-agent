import type { Point } from "./api";

export type Res = "cpu" | "memory";
const SCALE = { cpu: 1000, memory: 1 / 2 ** 20 }; // millicores, MiB

/** uPlot's columns: times, then request, Sizing and usage basis per point. */
export function series(points: Point[], res: Res): [number[], ...(number | null)[][]] {
  const pick = (f: "current" | "target" | "basis") =>
    points.map((p) => {
      const v = p[res]?.[f];
      return v == null ? null : v * SCALE[res];
    });
  return [points.map((p) => p.at), pick("current"), pick("target"), pick("basis")];
}
