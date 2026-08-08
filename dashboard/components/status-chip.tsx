import type { AgentRead } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<AgentRead["status"], { dot: string; chip: string }> = {
  active: { dot: "bg-success", chip: "bg-success/10 text-success ring-success/20" },
  draft: { dot: "bg-warning", chip: "bg-warning/10 text-warning ring-warning/20" },
  disabled: { dot: "bg-muted-foreground", chip: "bg-muted text-muted-foreground ring-border" },
};

/** Status pill shared by the agent list and the agent detail header. The
 * status word is kept as its own text node so it reads as one label rather
 * than being split by the dot. */
export function StatusChip({
  status,
  className,
}: {
  status: AgentRead["status"];
  className?: string;
}) {
  const style = STATUS_STYLE[status];
  return (
    <span
      className={cn(
        "inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-medium ring-1 ring-inset",
        style.chip,
        className,
      )}
    >
      <span aria-hidden="true" className={cn("size-1.5 rounded-full", style.dot)} />
      <span>{status}</span>
    </span>
  );
}
