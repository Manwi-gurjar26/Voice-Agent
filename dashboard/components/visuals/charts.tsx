"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

/* ---------------------------------------------------------------------------
   Charts are hand-drawn SVG rather than a charting library.

   Not a purity argument — a concrete one. Every candidate (recharts, nivo,
   visx) ships 40–120KB gzipped to draw, here, two line series and a bar list,
   and each brings its own opinion about axes, tooltips, and legends that then
   has to be overridden back to this palette's hairline rules and mono
   figures. The drawing below is ~200 lines, has no runtime dependency, and
   inherits the design tokens directly.
--------------------------------------------------------------------------- */

/** Container width, measured. Charts need real pixel widths (so 11px axis
 * labels render at 11px rather than being scaled by a viewBox), and the
 * width is only knowable client-side. Returns 0 until measured; callers
 * render nothing rather than a wrongly-sized first frame. */
function useElementWidth<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [width, setWidth] = useState(0);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const observer = new ResizeObserver(([entry]) => {
      setWidth(entry.contentRect.width);
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  return [ref, width] as const;
}

/**
 * An axis maximum and a tick count that divide into whole numbers.
 *
 * Returning only a "nice" maximum is not enough: these series are counts, so
 * every gridline label is rounded to an integer, and a max of 2 across five
 * gridlines produced `2, 2, 1, 1, 0` — two pairs of duplicate labels against
 * four visibly different lines. Choosing the divisions alongside the maximum
 * is what guarantees each label is distinct.
 */
function niceScale(value: number): { max: number; ticks: number } {
  // A flat-zero series still needs an axis to hang the gridlines on.
  if (value <= 0) return { max: 4, ticks: 5 };
  // Small counts get one gridline per unit — the common case on a new
  // workspace, and the case the duplicate-label bug showed up in.
  if (value <= 5) return { max: Math.ceil(value), ticks: Math.ceil(value) + 1 };

  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const step = normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  const max = step * magnitude;
  // 5 ticks divides 2·10ⁿ and 10·10ⁿ evenly; 5·10ⁿ needs 6 to stay integral.
  return { max, ticks: step === 5 ? 6 : 5 };
}

export function compactNumber(value: number): string {
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1).replace(/\.0$/, "")}M`;
  if (Math.abs(value) >= 1_000) return `${(value / 1_000).toFixed(1).replace(/\.0$/, "")}k`;
  return String(value);
}

export interface Series {
  key: string;
  label: string;
  /** Any CSS colour. Pass a var(--chart-n) so it tracks the palette. */
  color: string;
  values: number[];
}

interface TrendChartProps {
  series: Series[];
  /** One label per data point. Rendered thinned-out along the x axis, and in
   * full inside the hover readout. */
  labels: string[];
  height?: number;
  className?: string;
  /** Fills the area under the first series. Off for multi-series charts
   * where overlapping fills muddy both. */
  fill?: boolean;
}

/**
 * Multi-series line chart with a hover crosshair.
 *
 * Draws every series against one shared y axis: these are all counts of the
 * same kind of thing (conversations, messages, sessions), so a second axis
 * would let two unrelated scales be visually compared by accident.
 */
export function TrendChart({
  series,
  labels,
  height = 240,
  className,
  fill = true,
}: TrendChartProps) {
  const [ref, width] = useElementWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);

  const count = labels.length;
  const pad = { top: 16, right: 12, bottom: 26, left: 40 };
  const plotW = Math.max(0, width - pad.left - pad.right);
  const plotH = height - pad.top - pad.bottom;

  const { max, ticks } = niceScale(Math.max(0, ...series.flatMap((s) => s.values)));

  const xAt = useCallback(
    (i: number) => pad.left + (count <= 1 ? plotW / 2 : (i * plotW) / (count - 1)),
    [count, plotW, pad.left],
  );
  const yAt = useCallback(
    (v: number) => pad.top + plotH * (1 - v / max),
    [plotH, max, pad.top],
  );

  function handleMove(event: React.PointerEvent<SVGSVGElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    const x = event.clientX - rect.left;
    if (count <= 1) return setHover(0);
    const ratio = (x - pad.left) / (plotW || 1);
    setHover(Math.max(0, Math.min(count - 1, Math.round(ratio * (count - 1)))));
  }

  // Thin the x labels to roughly one per 90px, so a 30-day window on a
  // narrow column shows four dates rather than thirty overlapping ones.
  const labelStride = Math.max(1, Math.ceil(count / Math.max(2, Math.floor(plotW / 90))));
  const gridLines = Array.from({ length: ticks }, (_, i) => i / (ticks - 1));

  return (
    <div ref={ref} className={cn("relative w-full", className)}>
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`${series.map((s) => s.label).join(" and ")} over the last ${count} days`}
          onPointerMove={handleMove}
          onPointerLeave={() => setHover(null)}
          className="touch-none"
        >
          {gridLines.map((t) => {
            const y = pad.top + plotH * t;
            const value = Math.round(max * (1 - t));
            return (
              <g key={t}>
                <line
                  x1={pad.left}
                  x2={width - pad.right}
                  y1={y}
                  y2={y}
                  stroke="var(--rule)"
                  strokeWidth={1}
                />
                <text
                  x={pad.left - 8}
                  y={y + 3.5}
                  textAnchor="end"
                  className="mono-fig"
                  fontSize={10}
                  fill="var(--fg-faint)"
                >
                  {compactNumber(value)}
                </text>
              </g>
            );
          })}

          {labels.map((label, i) =>
            i % labelStride === 0 || i === count - 1 ? (
              <text
                key={label + i}
                x={xAt(i)}
                y={height - 8}
                textAnchor={i === count - 1 ? "end" : i === 0 ? "start" : "middle"}
                className="mono-fig"
                fontSize={10}
                fill="var(--fg-faint)"
              >
                {label}
              </text>
            ) : null,
          )}

          {series.map((s, seriesIndex) => {
            const line = s.values
              .map((v, i) => `${i === 0 ? "M" : "L"}${xAt(i)},${yAt(v)}`)
              .join(" ");
            const area = `${line} L${xAt(count - 1)},${pad.top + plotH} L${xAt(0)},${
              pad.top + plotH
            } Z`;
            const gradientId = `trend-fill-${s.key}`;
            return (
              <g key={s.key}>
                {fill && seriesIndex === 0 && (
                  <>
                    <defs>
                      <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={s.color} stopOpacity={0.28} />
                        <stop offset="100%" stopColor={s.color} stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <path d={area} fill={`url(#${gradientId})`} />
                  </>
                )}
                <path
                  d={line}
                  fill="none"
                  stroke={s.color}
                  strokeWidth={1.75}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              </g>
            );
          })}

          {hover !== null && (
            <g>
              <line
                x1={xAt(hover)}
                x2={xAt(hover)}
                y1={pad.top}
                y2={pad.top + plotH}
                stroke="var(--rule-strong)"
                strokeWidth={1}
              />
              {series.map((s) => (
                <circle
                  key={s.key}
                  cx={xAt(hover)}
                  cy={yAt(s.values[hover] ?? 0)}
                  r={3.5}
                  fill="var(--bg)"
                  stroke={s.color}
                  strokeWidth={1.75}
                />
              ))}
            </g>
          )}
        </svg>
      )}

      {hover !== null && width > 0 && (
        <div
          className="border-rule-strong bg-popover pointer-events-none absolute top-2 z-10 min-w-36 rounded-md border p-2.5 text-xs"
          // Flips to the left of the crosshair past the midpoint so it never
          // runs off the right edge of the card.
          style={
            xAt(hover) > width / 2
              ? { right: width - xAt(hover) + 12 }
              : { left: xAt(hover) + 12 }
          }
        >
          <p className="eyebrow mb-1.5 text-[9px]">{labels[hover]}</p>
          {series.map((s) => (
            <p key={s.key} className="flex items-center justify-between gap-4 py-0.5">
              <span className="text-fg-dim flex items-center gap-1.5">
                <span
                  aria-hidden="true"
                  className="size-1.5 rounded-full"
                  style={{ background: s.color }}
                />
                {s.label}
              </span>
              <span className="mono-fig font-medium">
                {(s.values[hover] ?? 0).toLocaleString()}
              </span>
            </p>
          ))}
        </div>
      )}
    </div>
  );
}

/** Legend for a TrendChart. Separate from the chart so it can sit in the
 * card header next to the title rather than floating inside the plot. */
export function ChartLegend({ series }: { series: Series[] }) {
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1">
      {series.map((s) => (
        <li key={s.key} className="text-fg-dim flex items-center gap-1.5 text-xs">
          <span
            aria-hidden="true"
            className="h-0.5 w-3 rounded-full"
            style={{ background: s.color }}
          />
          {s.label}
        </li>
      ))}
    </ul>
  );
}

export interface BarItem {
  label: string;
  value: number;
  /** Secondary text on the right, e.g. a percentage or a timestamp. */
  hint?: string;
  href?: string;
}

/**
 * Ranked horizontal bars.
 *
 * The bar is drawn as a tinted track *behind* the label rather than as a
 * separate column beside it — at these row heights a conventional bar chart
 * spends most of its width on the axis, and the label ends up truncated to
 * make room for it.
 */
export function BarList({
  items,
  color = "var(--chart-1)",
  emptyLabel = "Nothing yet.",
  className,
}: {
  items: BarItem[];
  color?: string;
  emptyLabel?: string;
  className?: string;
}) {
  if (items.length === 0) {
    return <p className="text-fg-faint py-6 text-center text-sm">{emptyLabel}</p>;
  }
  const max = Math.max(...items.map((i) => i.value), 1);

  return (
    <ul className={cn("flex flex-col gap-1.5", className)}>
      {items.map((item) => (
        <li key={item.label} className="relative overflow-hidden rounded-sm">
          <span
            aria-hidden="true"
            className="absolute inset-y-0 left-0 rounded-sm transition-[width] duration-700 ease-out"
            style={{
              width: `${Math.max(2, (item.value / max) * 100)}%`,
              background: `color-mix(in oklch, ${color} 22%, transparent)`,
              borderLeft: `2px solid ${color}`,
            }}
          />
          <span className="relative flex items-center justify-between gap-3 px-2.5 py-1.5 text-xs">
            <span className="truncate" title={item.label}>
              {item.label}
            </span>
            <span className="flex shrink-0 items-center gap-2.5">
              {item.hint && <span className="text-fg-faint">{item.hint}</span>}
              <span className="mono-fig font-medium">{item.value.toLocaleString()}</span>
            </span>
          </span>
        </li>
      ))}
    </ul>
  );
}

/**
 * Inline trend, no axes. Sized in px because it sits inside a stat card whose
 * width is already fixed by the grid — measuring here would cost a
 * ResizeObserver per card for no benefit.
 */
export function Sparkline({
  values,
  width = 96,
  height = 28,
  color = "var(--chart-1)",
  className,
}: {
  values: number[];
  width?: number;
  height?: number;
  color?: string;
  className?: string;
}) {
  if (values.length < 2) return null;
  const max = Math.max(...values, 1);
  const step = width / (values.length - 1);
  const points = values.map((v, i) => [i * step, height - (v / max) * (height - 2) - 1]);
  const line = points.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x},${y}`).join(" ");
  const last = points[points.length - 1];

  return (
    <svg
      width={width}
      height={height}
      className={cn("overflow-visible", className)}
      aria-hidden="true"
    >
      <path d={line} fill="none" stroke={color} strokeWidth={1.5} strokeLinejoin="round" />
      <circle cx={last[0]} cy={last[1]} r={2} fill={color} />
    </svg>
  );
}
