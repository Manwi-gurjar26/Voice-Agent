import { cn } from "@/lib/utils";

/**
 * The page's ground: a fine rule grid fading out downward, with one very low
 * magenta bloom behind the top of the content.
 *
 * This replaces the previous drifting three-blob aurora. On a true-black page
 * a saturated animated mesh is the whole design — everything else has to
 * shout over it, and a chart drawn on top of a moving wash is unreadable. A
 * static grid does the one job a backdrop should: give the black a sense of
 * scale, and stay behind the content.
 *
 * `fixed` + `-z-10` so it never joins the scroll, and `pointer-events-none`
 * so it never intercepts a click.
 */
export function Backdrop({
  className,
  bloom = true,
}: {
  className?: string;
  /** Off for dense data screens, where even a faint wash tints the charts. */
  bloom?: boolean;
}) {
  return (
    <div
      aria-hidden="true"
      className={cn("pointer-events-none fixed inset-0 -z-10 overflow-hidden", className)}
    >
      <div
        className="grid-pattern absolute inset-0"
        style={{
          maskImage: "linear-gradient(to bottom, black, transparent 70%)",
          WebkitMaskImage: "linear-gradient(to bottom, black, transparent 70%)",
        }}
      />
      {bloom && (
        <div
          className="absolute -top-64 left-1/2 h-[42rem] w-[70rem] -translate-x-1/2 rounded-full blur-[140px]"
          style={{
            background:
              "radial-gradient(circle, color-mix(in oklch, var(--magenta) 16%, transparent), transparent 68%)",
          }}
        />
      )}
      {/* A single hairline at the horizon, which is what stops the grid's
          fade from looking like a rendering artefact. */}
      <div className="absolute inset-x-0 top-[70%] h-px bg-[var(--rule)] opacity-40" />
    </div>
  );
}
