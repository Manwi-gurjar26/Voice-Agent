"use client";

import { useSyncExternalStore } from "react";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";
import { cn } from "@/lib/utils";

const OPTIONS = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "system", label: "System", Icon: Monitor },
  { value: "dark", label: "Dark", Icon: Moon },
] as const;

/* Hydration detection without a setState-in-effect: the server snapshot is
   `false` and the client snapshot is `true`, so this flips exactly once, at
   hydration, with no subscription and no cascading render. */
const NEVER_CHANGES = () => () => {};

/**
 * Segmented light/system/dark control. `next-themes` was already a
 * dependency and already wired up in providers.tsx, but nothing ever
 * exposed it — the dark palette was unreachable in the UI until now.
 *
 * Renders a fixed-size placeholder until mounted: the resolved theme is only
 * known client-side, so rendering the real state during SSR would either
 * hydrate-mismatch or flash the wrong active segment.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, setTheme } = useTheme();
  const mounted = useSyncExternalStore(
    NEVER_CHANGES,
    () => true,
    () => false,
  );

  return (
    <div
      className={cn(
        "inline-flex items-center gap-0.5 rounded-full border bg-card/60 p-0.5 backdrop-blur",
        className,
      )}
      role="group"
      aria-label="Colour theme"
    >
      {OPTIONS.map(({ value, label, Icon }) => {
        const active = mounted && theme === value;
        return (
          <button
            key={value}
            type="button"
            onClick={() => setTheme(value)}
            aria-label={label}
            aria-pressed={active}
            className={cn(
              "grid size-7 place-items-center rounded-full transition-colors",
              "focus-visible:ring-ring/50 focus-visible:ring-2 focus-visible:outline-none",
              active
                ? "bg-primary text-primary-foreground shadow-sm"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            <Icon className="size-3.5" aria-hidden="true" />
          </button>
        );
      })}
    </div>
  );
}
