import { cn } from "@/lib/utils";

/** Meridian count. Six reads as a sphere without turning into moiré at small
 * sizes; more rings look like noise once each is only a pixel wide. */
const MERIDIANS = 6;

/** Latitude rings as [z-offset, radius-scale] pairs on a unit sphere —
 * radius = sqrt(1 - offset²), so they actually sit on the sphere's surface
 * instead of floating at arbitrary sizes. */
const LATITUDES: Array<[number, number]> = [
  [0, 1],
  [0.5, 0.866],
  [-0.5, 0.866],
];

const ORBITERS = [
  { angle: 0, radius: 0.52, size: 7, delay: "0s" },
  { angle: 120, radius: 0.46, size: 5, delay: "-3s" },
  { angle: 235, radius: 0.55, size: 6, delay: "-6s" },
];

interface VoiceOrbProps {
  /** Rendered size in px. The whole thing scales from this one number. */
  size?: number;
  className?: string;
}

/**
 * A wireframe sphere built from real 3D-transformed rings inside a
 * `preserve-3d` rotor — actual perspective projection, not a flat image or a
 * stack of ellipse SVGs faking depth. Costs no JavaScript at runtime and no
 * KB of dependencies (a three.js scene would be ~150KB gzipped for what is,
 * here, decoration), and animates entirely on the compositor.
 *
 * Purely decorative, so it is `aria-hidden` and every animation inside it is
 * suppressed by the global `prefers-reduced-motion` rule in globals.css.
 */
export function VoiceOrb({ size = 320, className }: VoiceOrbProps) {
  const r = size / 2;

  return (
    <div
      aria-hidden="true"
      className={cn("scene-3d relative shrink-0", className)}
      style={{ width: size, height: size }}
    >
      {/* Atmospheric halo, deliberately outside the rotor so it stays put
          while the sphere turns. */}
      <div
        className="absolute inset-0 rounded-full blur-2xl"
        style={{
          background:
            "radial-gradient(circle at 50% 50%, color-mix(in oklch, var(--brand-2) 55%, transparent), transparent 68%)",
          animation: "orb-pulse 6s ease-in-out infinite",
        }}
      />

      <div
        className="preserve-3d absolute inset-0"
        style={{ animation: "orb-spin 26s linear infinite" }}
      >
        {Array.from({ length: MERIDIANS }, (_, i) => (
          <div
            key={`m${i}`}
            className="absolute inset-0 rounded-full border"
            style={{
              transform: `rotateY(${(i * 180) / MERIDIANS}deg)`,
              borderColor: `color-mix(in oklch, ${
                i % 2 === 0 ? "var(--brand-1)" : "var(--brand-3)"
              } ${38 + i * 5}%, transparent)`,
            }}
          />
        ))}

        {LATITUDES.map(([offset, scale], i) => (
          <div
            key={`l${i}`}
            className="absolute inset-0 rounded-full border"
            style={{
              transform: `rotateX(90deg) translateZ(${offset * r}px) scale(${scale})`,
              borderColor: "color-mix(in oklch, var(--brand-3) 42%, transparent)",
            }}
          />
        ))}

        {/* Orbiters sit inside the rotor, so they genuinely pass behind the
            sphere on the far half of each revolution. */}
        {ORBITERS.map((o, i) => (
          <div
            key={`o${i}`}
            className="absolute top-1/2 left-1/2"
            style={{ transform: `rotateY(${o.angle}deg) translateZ(${o.radius * size}px)` }}
          >
            <div
              className="rounded-full"
              style={{
                width: o.size,
                height: o.size,
                marginLeft: -o.size / 2,
                marginTop: -o.size / 2,
                background: "var(--brand-3)",
                boxShadow: "0 0 12px 2px color-mix(in oklch, var(--brand-3) 70%, transparent)",
                animation: `orb-pulse 4s ease-in-out infinite`,
                animationDelay: o.delay,
              }}
            />
          </div>
        ))}
      </div>

      {/* Lit core. The off-centre highlight is what makes a flat circle read
          as a sphere; a centred gradient reads as a disc. */}
      <div
        className="absolute rounded-full"
        style={{
          inset: `${r * 0.56}px`,
          background:
            "radial-gradient(circle at 34% 30%, color-mix(in oklch, white 80%, var(--brand-3)), var(--brand-1) 52%, color-mix(in oklch, var(--brand-1) 55%, black) 100%)",
          boxShadow:
            "0 0 40px 6px color-mix(in oklch, var(--brand-1) 55%, transparent), inset 0 -6px 18px color-mix(in oklch, black 35%, transparent)",
        }}
      />

      {/* Sonar rings — the "voice" half of the metaphor. */}
      {[0, 1].map((i) => (
        <div
          key={`p${i}`}
          className="absolute rounded-full border"
          style={{
            inset: `${r * 0.56}px`,
            borderColor: "color-mix(in oklch, var(--brand-3) 60%, transparent)",
            animation: "ping-ring 3.6s cubic-bezier(0, 0, 0.2, 1) infinite",
            animationDelay: `${i * 1.8}s`,
          }}
        />
      ))}
    </div>
  );
}
