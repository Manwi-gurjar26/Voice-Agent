import { cn } from "@/lib/utils";

/* A single fixed gradient id is safe here: every instance defines the same
   stops, so duplicate ids across instances resolve identically. useId() would
   force this to be a client component for no benefit. */
const GRADIENT_ID = "va-brand-gradient";

/** Waveform bar heights, centred — the "voice" half of the mark. */
const BARS = [8, 14, 20, 14, 8];

export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={cn("shrink-0", className)}
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={GRADIENT_ID} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="var(--brand-1)" />
          <stop offset="52%" stopColor="var(--brand-2)" />
          <stop offset="100%" stopColor="var(--brand-3)" />
        </linearGradient>
      </defs>
      <rect width="32" height="32" rx="9" fill={`url(#${GRADIENT_ID})`} />
      {BARS.map((h, i) => (
        <rect
          key={i}
          x={7 + i * 4.5}
          y={16 - h / 2}
          width="2.5"
          height={h}
          rx="1.25"
          fill="white"
          opacity={i === 2 ? 1 : 0.78}
        />
      ))}
    </svg>
  );
}

export function Wordmark({ className }: { className?: string }) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      <LogoMark size={28} />
      <span className="text-[0.95rem] font-semibold tracking-tight">Voice Agent</span>
    </span>
  );
}

/** Animated equaliser. Decorative: `aria-hidden`, and the global
 * reduced-motion rule freezes it into a static bar chart. */
export function VoiceWave({
  bars = 5,
  className,
  color = "currentColor",
}: {
  bars?: number;
  className?: string;
  color?: string;
}) {
  return (
    <span aria-hidden="true" className={cn("inline-flex h-4 items-center gap-[3px]", className)}>
      {Array.from({ length: bars }, (_, i) => (
        <span
          key={i}
          className="w-[2px] rounded-full"
          style={{
            height: "100%",
            background: color,
            transformOrigin: "center",
            animation: "wave-bar 1.1s ease-in-out infinite",
            animationDelay: `${(i % 3) * 0.18 + (i > 2 ? 0.09 : 0)}s`,
          }}
        />
      ))}
    </span>
  );
}
