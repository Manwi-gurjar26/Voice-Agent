import type { AgentRead } from "@/lib/types";
import { cn } from "@/lib/utils";

const STATUS_STYLE: Record<AgentRead["status"], { dot: string; text: string }> = {
  active: { dot: "bg-success", text: "text-success" },
  draft: { dot: "bg-warning", text: "text-warning" },
  disabled: { dot: "bg-fg-faint", text: "text-fg-faint" },
};

/** Status marker shared by the agent list, the agent detail header and the
 * overview table.
 *
 * A dot plus a mono label rather than a filled pill: on a black ground a
 * tinted capsule reads as a button, and there are already enough of those on
 * an agent card. The status word stays its own text node so it reads (and
 * tests) as one label rather than being split by the dot. */
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
        "mono-fig inline-flex shrink-0 items-center gap-1.5 text-[10px] tracking-wider uppercase",
        style.text,
        className,
      )}
    >
      <span aria-hidden="true" className={cn("size-1.5 rounded-full", style.dot)} />
      <span>{status}</span>
    </span>
  );
}
