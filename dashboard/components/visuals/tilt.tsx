"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

interface TiltProps extends React.ComponentProps<"div"> {
  /** Maximum rotation in degrees on either axis. Small values read as
   * "responsive surface"; large ones read as a novelty toy. */
  max?: number;
  /** Cursor-tracked specular highlight. */
  glare?: boolean;
  /** How far the card lifts toward the viewer while hovered, in px. */
  lift?: number;
}

/**
 * Pointer-tracked 3D tilt with a specular glare, using real perspective
 * projection rather than a 2D skew that only looks 3D head-on.
 *
 * Deliberately opt-out in three cases where the effect is wrong rather than
 * merely unnecessary: reduced-motion users, touch input (there is no hover,
 * so a tilt triggered by a tap is just a flicker), and keyboard focus (the
 * card must not move under someone tabbing through it).
 *
 * Children are laid out in a `preserve-3d` context, so a child can opt into
 * parallax by setting its own `translateZ`.
 */
export function Tilt({
  max = 7,
  glare = true,
  lift = 14,
  className,
  children,
  style,
  ...props
}: TiltProps) {
  const ref = useRef<HTMLDivElement>(null);
  const [interactive, setInteractive] = useState(false);

  useEffect(() => {
    const motionOk = window.matchMedia("(prefers-reduced-motion: no-preference)");
    const hoverOk = window.matchMedia("(hover: hover) and (pointer: fine)");
    const update = () => setInteractive(motionOk.matches && hoverOk.matches);
    update();
    motionOk.addEventListener("change", update);
    hoverOk.addEventListener("change", update);
    return () => {
      motionOk.removeEventListener("change", update);
      hoverOk.removeEventListener("change", update);
    };
  }, []);

  function handleMove(event: React.PointerEvent<HTMLDivElement>) {
    const el = ref.current;
    if (!interactive || !el || event.pointerType !== "mouse") return;

    const rect = el.getBoundingClientRect();
    const x = (event.clientX - rect.left) / rect.width;
    const y = (event.clientY - rect.top) / rect.height;

    el.style.setProperty("--tilt-rx", `${(0.5 - y) * 2 * max}deg`);
    el.style.setProperty("--tilt-ry", `${(x - 0.5) * 2 * max}deg`);
    el.style.setProperty("--tilt-z", `${lift}px`);
    el.style.setProperty("--glare-x", `${x * 100}%`);
    el.style.setProperty("--glare-y", `${y * 100}%`);
    el.style.setProperty("--glare-o", "1");
  }

  function reset() {
    const el = ref.current;
    if (!el) return;
    el.style.setProperty("--tilt-rx", "0deg");
    el.style.setProperty("--tilt-ry", "0deg");
    el.style.setProperty("--tilt-z", "0px");
    el.style.setProperty("--glare-o", "0");
  }

  return (
    <div
      ref={ref}
      onPointerMove={handleMove}
      onPointerLeave={reset}
      className={cn("preserve-3d relative", className)}
      style={{
        transform:
          "perspective(900px) rotateX(var(--tilt-rx, 0deg)) rotateY(var(--tilt-ry, 0deg)) translateZ(var(--tilt-z, 0px))",
        transition: "transform 350ms cubic-bezier(0.22, 1, 0.36, 1)",
        ...style,
      }}
      {...props}
    >
      {children}
      {glare && interactive && (
        <span
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 rounded-[inherit]"
          style={{
            background:
              "radial-gradient(320px circle at var(--glare-x, 50%) var(--glare-y, 50%), color-mix(in oklch, white 22%, transparent), transparent 60%)",
            opacity: "var(--glare-o, 0)",
            transition: "opacity 300ms ease",
          }}
        />
      )}
    </div>
  );
}
