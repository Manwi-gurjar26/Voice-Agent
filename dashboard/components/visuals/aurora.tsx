import { cn } from "@/lib/utils";

const BLOBS = [
  {
    color: "var(--brand-1)",
    size: "46rem",
    top: "-16rem",
    left: "-12rem",
    duration: "26s",
    delay: "0s",
    opacity: 0.5,
  },
  {
    color: "var(--brand-3)",
    size: "38rem",
    top: "-8rem",
    right: "-14rem",
    duration: "32s",
    delay: "-8s",
    opacity: 0.42,
  },
  {
    color: "var(--brand-2)",
    size: "42rem",
    bottom: "-20rem",
    left: "22%",
    duration: "38s",
    delay: "-16s",
    opacity: 0.35,
  },
] satisfies Array<Record<string, string | number>>;

/**
 * Slow-drifting gradient mesh behind the app chrome. Three heavily blurred
 * radial blobs rather than an animated canvas — no JS, no repaint cost
 * beyond the compositor, and it degrades to a static wash under
 * `prefers-reduced-motion` (the global rule freezes the drift) instead of
 * disappearing.
 *
 * `fixed` + `-z-10`: it must sit behind scrolling content without joining
 * the scroll, and must never intercept pointer events.
 */
export function Aurora({ className }: { className?: string }) {
  return (
    <div
      aria-hidden="true"
      className={cn("pointer-events-none fixed inset-0 -z-10 overflow-hidden", className)}
    >
      {BLOBS.map((blob, i) => (
        <div
          key={i}
          className="absolute rounded-full blur-[110px]"
          style={{
            width: blob.size,
            height: blob.size,
            top: "top" in blob ? blob.top : undefined,
            bottom: "bottom" in blob ? blob.bottom : undefined,
            left: "left" in blob ? blob.left : undefined,
            right: "right" in blob ? blob.right : undefined,
            opacity: blob.opacity,
            background: `radial-gradient(circle, ${blob.color}, transparent 70%)`,
            animation: `aurora-drift ${blob.duration} ease-in-out infinite`,
            animationDelay: blob.delay,
          }}
        />
      ))}
      {/* Faint grid over the wash: gives the blur a sense of scale and stops
          the background reading as an unintentional smear. */}
      <div
        className="grid-pattern absolute inset-0 opacity-40"
        style={{
          maskImage: "radial-gradient(ellipse 90% 60% at 50% 0%, black, transparent 75%)",
          WebkitMaskImage: "radial-gradient(ellipse 90% 60% at 50% 0%, black, transparent 75%)",
        }}
      />
    </div>
  );
}
