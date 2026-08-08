import { cn } from "@/lib/utils";

const GRADIENT_ID = "va-usage-ring-gradient";

/**
 * Radial usage meter. A ring rather than a bar because the number it frames
 * ("62%") is the headline on the billing page — a bar leaves that number
 * homeless, a ring gives it a natural place to sit.
 *
 * The value is exposed via `role="img"` + `aria-label` so the meter is not
 * purely visual; the numeric readout inside is `aria-hidden` to avoid a
 * screen reader announcing it twice.
 */
export function UsageRing({
  percent,
  size = 148,
  stroke = 11,
  className,
  caption,
}: {
  percent: number;
  size?: number;
  stroke?: number;
  className?: string;
  caption?: string;
}) {
  const clamped = Math.max(0, Math.min(100, percent));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const dashOffset = circumference * (1 - clamped / 100);

  return (
    <div
      className={cn("relative grid shrink-0 place-items-center", className)}
      style={{ width: size, height: size }}
      role="img"
      aria-label={`${clamped}% of the monthly message quota used`}
    >
      <svg width={size} height={size} className="-rotate-90">
        <defs>
          <linearGradient id={GRADIENT_ID} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="var(--brand-1)" />
            <stop offset="55%" stopColor="var(--brand-2)" />
            <stop offset="100%" stopColor="var(--brand-3)" />
          </linearGradient>
        </defs>
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="stroke-muted"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          stroke={`url(#${GRADIENT_ID})`}
          strokeDasharray={circumference}
          strokeDashoffset={dashOffset}
          style={{ transition: "stroke-dashoffset 900ms cubic-bezier(0.22, 1, 0.36, 1)" }}
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center" aria-hidden="true">
        <div>
          <div className="text-2xl font-semibold tracking-tight tabular-nums">{clamped}%</div>
          {caption && <div className="text-muted-foreground mt-0.5 text-[11px]">{caption}</div>}
        </div>
      </div>
    </div>
  );
}
