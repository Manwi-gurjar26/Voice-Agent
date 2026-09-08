import { cn } from "@/lib/utils";

/** Waveform bar heights, centred — the "voice" half of the mark. */
const BARS = [7, 13, 20, 13, 7];

/**
 * The mark: a hairline-ruled square holding a magenta equaliser.
 *
 * Deliberately not a gradient-filled rounded chip any more. On a true-black
 * page a saturated filled tile is the loudest thing on screen and fights the
 * headline for attention; an outlined square with a single accent inside
 * sits in the same visual register as the rest of the chrome, which is what
 * the reference does throughout.
 */
export function LogoMark({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      width={size}
      height={size}
      className={cn("shrink-0", className)}
      aria-hidden="true"
    >
      <rect
        x="0.5"
        y="0.5"
        width="31"
        height="31"
        rx="5.5"
        fill="var(--ink-1)"
        stroke="var(--rule-strong)"
      />
      {BARS.map((h, i) => (
        <rect
          key={i}
          x={7 + i * 4.5}
          y={16 - h / 2}
          width="2.5"
          height={h}
          rx="1.25"
          fill="var(--magenta)"
          // The centre bar at full strength, the outer pairs stepped back —
          // the fade is what makes five rectangles read as a waveform.
          opacity={i === 2 ? 1 : i === 1 || i === 3 ? 0.72 : 0.42}
        />
      ))}
    </svg>
  );
}

export function Wordmark({
  className,
  showMark = true,
}: {
  className?: string;
  showMark?: boolean;
}) {
  return (
    <span className={cn("flex items-center gap-2.5", className)}>
      {showMark && <LogoMark size={26} />}
      <span className="text-[15px] font-bold tracking-tight">
        Voice Agent
        {/* The accent lives in one glyph. Cheaper than a coloured logotype
            and it survives being rendered at 13px in a sidebar. */}
        <span className="text-primary" aria-hidden="true">
          .
        </span>
      </span>
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
