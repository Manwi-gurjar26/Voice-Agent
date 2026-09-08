"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  ArrowRight,
  ArrowUpRight,
  BookOpenText,
  Bot,
  CircleDot,
  Globe,
  MessagesSquare,
  Mic,
  Quote,
  TrendingDown,
  TrendingUp,
  Users,
  Zap,
} from "lucide-react";
import { formatApiError, getAnalyticsOverview } from "@/lib/api";
import type { AnalyticsOverview } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { StatusChip } from "@/components/status-chip";
import {
  BarList,
  ChartLegend,
  Sparkline,
  TrendChart,
  compactNumber,
  type Series,
} from "@/components/visuals/charts";
import { UsageRing } from "@/components/visuals/usage-ring";
import { cn } from "@/lib/utils";

const RANGES = [7, 30, 90] as const;
type Range = (typeof RANGES)[number];

/** Percentage change against the equally-long window before this one.
 * `null` when the previous window was empty: "up 100%" from zero is a
 * meaningless figure dressed as an insight. */
function delta(current: number, previous: number): number | null {
  if (previous === 0) return null;
  return Math.round(((current - previous) / previous) * 100);
}

function Delta({ value, invert = false }: { value: number | null; invert?: boolean }) {
  if (value === null || value === 0) {
    return <span className="text-fg-faint mono-fig text-[11px]">—</span>;
  }
  const good = invert ? value < 0 : value > 0;
  const Icon = value > 0 ? TrendingUp : TrendingDown;
  return (
    <span
      className={cn(
        "mono-fig flex items-center gap-1 text-[11px]",
        good ? "text-success" : "text-fg-dim",
      )}
    >
      <Icon className="size-3" aria-hidden="true" />
      {value > 0 ? "+" : ""}
      {value}%
    </span>
  );
}

function StatTile({
  label,
  value,
  sub,
  change,
  spark,
  sparkColor,
  Icon,
}: {
  label: string;
  value: string;
  sub?: string;
  change?: number | null;
  spark?: number[];
  sparkColor?: string;
  Icon: React.ComponentType<{ className?: string }>;
}) {
  const hasSpark = Boolean(spark?.some((v) => v > 0));
  return (
    <div className="border-rule flex flex-col gap-4 border p-4">
      <div className="flex items-start justify-between gap-3">
        <span className="eyebrow">{label}</span>
        <Icon className="text-fg-faint size-3.5 shrink-0" />
      </div>
      <div>
        <p className="mono-fig text-[1.75rem] leading-none font-semibold tracking-tight">
          {value}
        </p>
        <div className="mt-2 flex items-center justify-between gap-2">
          <span className="text-fg-faint text-[11px]">{sub}</span>
          {change !== undefined && <Delta value={change} />}
        </div>
      </div>
      {/* The sparkline row keeps its height whether or not there is a line to
          draw. Without it, a tile with no series (Grounded replies) let its
          figure drop to the vertical centre while its three neighbours sat on
          a common baseline — the numbers are meant to be read across. */}
      <div className="mt-auto h-[26px]">
        {hasSpark && spark && (
          <Sparkline values={spark} color={sparkColor} width={120} height={26} />
        )}
      </div>
    </div>
  );
}

function Panel({
  title,
  hint,
  action,
  children,
  className,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("border-rule flex flex-col border", className)}>
      <header className="flex items-start justify-between gap-4 border-b px-4 py-3">
        <div>
          <h2 className="text-[13px] font-semibold">{title}</h2>
          {hint && <p className="text-fg-faint mt-0.5 text-[11px]">{hint}</p>}
        </div>
        {action}
      </header>
      <div className="flex-1 p-4">{children}</div>
    </section>
  );
}

function SkeletonBlock({ className }: { className?: string }) {
  return (
    <div className={cn("border-rule overflow-hidden border", className)}>
      <div className="animate-shimmer h-full w-full" />
    </div>
  );
}

function relativeTime(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const minutes = Math.round(diff / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function OverviewPage() {
  const [range, setRange] = useState<Range>(30);
  const [data, setData] = useState<AnalyticsOverview | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getAnalyticsOverview(range)
      .then((overview) => {
        if (cancelled) return;
        setData(overview);
        setError(null);
      })
      .catch((err) => {
        if (!cancelled) setError(formatApiError(err));
      });

    return () => {
      cancelled = true;
    };
  }, [range]);

  // Derived rather than a third piece of state set at the top of the effect:
  // the response carries the window it answers for, so "the numbers on screen
  // are not the ones you just asked for" is a fact about the data, not
  // something that needs tracking alongside it. Distinct from `data === null`
  // — switching range dims the existing figures instead of blanking the page
  // back to skeletons.
  const refreshing = data !== null && data.range_days !== range;

  const labels =
    data?.daily.map((point) =>
      new Date(`${point.day}T00:00:00Z`).toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      }),
    ) ?? [];

  const series: Series[] = data
    ? [
        {
          key: "conversations",
          label: "Conversations",
          color: "var(--chart-1)",
          values: data.daily.map((d) => d.conversations),
        },
        {
          key: "messages",
          label: "Messages",
          color: "var(--chart-2)",
          values: data.daily.map((d) => d.messages),
        },
        {
          key: "sessions",
          label: "Widget sessions",
          color: "var(--chart-3)",
          values: data.daily.map((d) => d.sessions),
        },
      ]
    : [];

  const totalTokens = data ? data.totals.input_tokens + data.totals.output_tokens : 0;
  const previousTokens = data
    ? data.previous_totals.input_tokens + data.previous_totals.output_tokens
    : 0;

  // Share of assistant replies that actually used the knowledge base. The
  // single most diagnostic number here: a low value means retrieval is not
  // finding anything, which is invisible in a raw message count.
  const groundedPct =
    data && data.totals.assistant_messages > 0
      ? Math.round((data.totals.cited_replies / data.totals.assistant_messages) * 100)
      : null;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="display text-2xl font-bold">Overview</h1>
          <p className="text-fg-faint mt-1 text-xs">
            {data
              ? `Last ${data.range_days} days · updated ${relativeTime(data.generated_at)}`
              : "Loading workspace activity…"}
          </p>
        </div>

        <div
          role="group"
          aria-label="Time range"
          className="border-rule-strong flex items-center gap-0.5 rounded-md border p-0.5"
        >
          {RANGES.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setRange(value)}
              aria-pressed={range === value}
              className={cn(
                "mono-fig rounded-[4px] px-2.5 py-1 text-[11px] transition-colors",
                range === value
                  ? "bg-secondary text-foreground font-medium"
                  : "text-fg-faint hover:text-foreground",
              )}
            >
              {value}d
            </button>
          ))}
        </div>
      </header>

      {error && (
        <div className="border-destructive/30 bg-destructive/5 text-destructive flex items-start gap-3 rounded-md border p-4 text-sm">
          <AlertCircle className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <p>{error}</p>
        </div>
      )}

      {!data && !error && (
        <div className="flex flex-col gap-6">
          <div className="grid gap-px sm:grid-cols-2 xl:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <SkeletonBlock key={i} className="h-36" />
            ))}
          </div>
          <SkeletonBlock className="h-80" />
        </div>
      )}

      {data && (
        <div className={cn("flex flex-col gap-6 transition-opacity", refreshing && "opacity-60")}>
          {/* ------------------------------------------------------------
              Headline figures.
          ------------------------------------------------------------ */}
          <div className="grid gap-px sm:grid-cols-2 xl:grid-cols-4">
            <StatTile
              label="Conversations"
              Icon={MessagesSquare}
              value={data.totals.conversations.toLocaleString()}
              sub={`${data.totals.sessions.toLocaleString()} widget sessions`}
              change={delta(data.totals.conversations, data.previous_totals.conversations)}
              spark={data.daily.map((d) => d.conversations)}
              sparkColor="var(--chart-1)"
            />
            <StatTile
              label="Messages"
              Icon={Users}
              value={data.totals.messages.toLocaleString()}
              sub={`${data.totals.user_messages.toLocaleString()} asked · ${data.totals.assistant_messages.toLocaleString()} answered`}
              change={delta(data.totals.messages, data.previous_totals.messages)}
              spark={data.daily.map((d) => d.messages)}
              sparkColor="var(--chart-2)"
            />
            <StatTile
              label="Tokens"
              Icon={Zap}
              value={compactNumber(totalTokens)}
              sub={`${compactNumber(data.totals.input_tokens)} in · ${compactNumber(data.totals.output_tokens)} out`}
              change={delta(totalTokens, previousTokens)}
              spark={data.daily.map((d) => d.input_tokens + d.output_tokens)}
              sparkColor="var(--chart-4)"
            />
            <StatTile
              label="Grounded replies"
              Icon={Quote}
              value={groundedPct === null ? "—" : `${groundedPct}%`}
              sub={
                groundedPct === null
                  ? "No replies yet"
                  : `${data.totals.cited_replies.toLocaleString()} of ${data.totals.assistant_messages.toLocaleString()} cited a source`
              }
            />
          </div>

          {/* ------------------------------------------------------------
              Trend.
          ------------------------------------------------------------ */}
          <Panel
            title="Activity"
            hint="Conversations, messages and widget sessions per day."
            action={<ChartLegend series={series} />}
          >
            <TrendChart series={series} labels={labels} height={260} />
          </Panel>

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            {/* ----------------------------------------------------------
                Per-agent table. Every agent appears, including idle ones —
                "which of these is doing nothing" is half the question.
            ---------------------------------------------------------- */}
            <Panel
              title="Agents"
              hint={`${data.agents_active} of ${data.agents_total} active`}
              action={
                <Button
                  render={<Link href="/agents" />}
                  nativeButton={false}
                  variant="ghost"
                  size="sm"
                  className="text-fg-dim gap-1"
                >
                  Manage
                  <ArrowRight className="size-3.5" aria-hidden="true" />
                </Button>
              }
              className="min-w-0"
            >
              {data.agents.length === 0 ? (
                <div className="flex flex-col items-center gap-3 py-10 text-center">
                  <Bot className="text-fg-faint size-6" aria-hidden="true" />
                  <p className="text-fg-dim text-sm">No agents yet.</p>
                  <Button
                    render={<Link href="/agents/new" />}
                    nativeButton={false}
                    size="sm"
                    className="bg-primary text-primary-foreground"
                  >
                    Create your first agent
                  </Button>
                </div>
              ) : (
                <div className="-mx-4 overflow-x-auto">
                  <table className="w-full min-w-[34rem] text-sm">
                    <thead>
                      <tr className="border-b">
                        {/* w-full on the name column: the numeric columns
                            size to their content and this one absorbs the
                            rest, so a short name is not truncated just
                            because the table has spare width elsewhere. */}
                        <th className="eyebrow w-full px-4 pb-2 text-left font-normal">Agent</th>
                        <th className="eyebrow px-2 pb-2 text-right font-normal">Convs</th>
                        <th className="eyebrow px-2 pb-2 text-right font-normal">Msgs</th>
                        <th className="eyebrow px-2 pb-2 text-right font-normal">Tokens</th>
                        <th className="eyebrow px-4 pb-2 text-right font-normal">Last seen</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.agents.map((agent) => (
                        <tr
                          key={agent.id}
                          className="hover:bg-secondary/50 border-b transition-colors last:border-b-0"
                        >
                          <td className="max-w-[16rem] min-w-0 px-4 py-2.5">
                            <Link
                              href={`/agents/${agent.id}`}
                              className="flex items-center gap-2 hover:underline"
                            >
                              <span className="truncate text-[13px]">{agent.name}</span>
                              {agent.voice_enabled && (
                                <Mic
                                  className="text-primary size-3 shrink-0"
                                  aria-label="Voice enabled"
                                />
                              )}
                            </Link>
                            <StatusChip status={agent.status} className="mt-1" />
                          </td>
                          <td className="mono-fig px-2 py-2.5 text-right text-[13px]">
                            {agent.conversations.toLocaleString()}
                          </td>
                          <td className="mono-fig px-2 py-2.5 text-right text-[13px]">
                            {agent.messages.toLocaleString()}
                          </td>
                          <td className="mono-fig text-fg-dim px-2 py-2.5 text-right text-[13px]">
                            {compactNumber(agent.input_tokens + agent.output_tokens)}
                          </td>
                          <td className="text-fg-faint px-4 py-2.5 text-right text-[11px] whitespace-nowrap">
                            {relativeTime(agent.last_activity_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </Panel>

            {/* ---------------------------------------------------------- */}
            <div className="flex min-w-0 flex-col gap-6">
              <Panel
                title="Plan usage"
                hint={`Resets from ${new Date(data.quota.period_started_at).toLocaleDateString(
                  undefined,
                  { day: "numeric", month: "short" },
                )}`}
                action={
                  <Button
                    render={<Link href="/billing" />}
                    nativeButton={false}
                    variant="ghost"
                    size="sm"
                    className="text-fg-dim gap-1"
                  >
                    Billing
                    <ArrowUpRight className="size-3.5" aria-hidden="true" />
                  </Button>
                }
              >
                <div className="flex items-center gap-5">
                  <UsageRing percent={data.quota.percent_used} size={112} stroke={9} caption="used" />
                  <div className="min-w-0 text-sm">
                    <p className="text-[13px] font-semibold capitalize">{data.quota.plan} plan</p>
                    <p className="text-fg-dim mono-fig mt-1.5 text-xs">
                      {data.quota.used.toLocaleString()} / {data.quota.quota.toLocaleString()}
                    </p>
                    <p className="text-fg-faint mono-fig mt-0.5 text-xs">
                      {data.quota.remaining.toLocaleString()} left
                    </p>
                  </div>
                </div>
              </Panel>

              <Panel
                title="Knowledge base"
                hint="Current state, not the selected window."
                action={<BookOpenText className="text-fg-faint size-3.5" aria-hidden="true" />}
              >
                {data.knowledge_base.documents === 0 ? (
                  <p className="text-fg-faint py-4 text-center text-sm">
                    No documents ingested yet.
                  </p>
                ) : (
                  <>
                    <div className="mb-4 flex items-baseline gap-2">
                      <span className="mono-fig text-2xl font-semibold tracking-tight">
                        {data.knowledge_base.documents.toLocaleString()}
                      </span>
                      <span className="text-fg-faint text-xs">
                        documents · {compactNumber(data.knowledge_base.characters)} characters
                      </span>
                    </div>
                    <ul className="flex flex-col gap-1.5">
                      {(
                        [
                          ["Ready", data.knowledge_base.ready, "var(--success)"],
                          ["Processing", data.knowledge_base.processing, "var(--chart-2)"],
                          ["Pending", data.knowledge_base.pending, "var(--warning)"],
                          ["Failed", data.knowledge_base.failed, "var(--destructive)"],
                        ] as const
                      )
                        .filter(([, count]) => count > 0)
                        .map(([label, count, color]) => (
                          <li
                            key={label}
                            className="flex items-center justify-between gap-3 text-xs"
                          >
                            <span className="text-fg-dim flex items-center gap-2">
                              <CircleDot
                                className="size-3"
                                style={{ color }}
                                aria-hidden="true"
                              />
                              {label}
                            </span>
                            <span className="mono-fig">{count.toLocaleString()}</span>
                          </li>
                        ))}
                    </ul>
                    {data.knowledge_base.failed > 0 && (
                      <p className="text-destructive mt-3 text-[11px]">
                        {data.knowledge_base.failed} document
                        {data.knowledge_base.failed === 1 ? "" : "s"} failed to ingest — those
                        pages are not answerable.
                      </p>
                    )}
                  </>
                )}
              </Panel>

              <Panel
                title="Where it is embedded"
                hint="Verified origins from widget sessions."
                action={<Globe className="text-fg-faint size-3.5" aria-hidden="true" />}
              >
                <BarList
                  items={data.origins.map((o) => ({
                    label: o.origin.replace(/^https?:\/\//, ""),
                    value: o.sessions,
                  }))}
                  color="var(--chart-2)"
                  emptyLabel="No sessions in this window."
                />
              </Panel>
            </div>
          </div>

          {/* ------------------------------------------------------------
              Recent threads.
          ------------------------------------------------------------ */}
          <Panel title="Recent conversations" hint="The ten most recent threads, any agent.">
            {data.recent_conversations.length === 0 ? (
              <p className="text-fg-faint py-6 text-center text-sm">
                Nothing yet. Open the Playground to try an agent yourself.
              </p>
            ) : (
              <ul className="divide-rule -my-1 divide-y">
                {data.recent_conversations.map((conversation) => (
                  <li
                    key={conversation.id}
                    className="flex items-center justify-between gap-4 py-2.5"
                  >
                    <div className="flex min-w-0 items-center gap-3">
                      <MessagesSquare
                        className="text-fg-faint size-3.5 shrink-0"
                        aria-hidden="true"
                      />
                      <Link
                        href={`/agents/${conversation.agent_id}`}
                        className="truncate text-[13px] hover:underline"
                      >
                        {conversation.agent_name}
                      </Link>
                      <span className="mono-fig text-fg-faint shrink-0 text-[11px]">
                        {conversation.messages} msg
                      </span>
                    </div>
                    <span className="text-fg-faint shrink-0 text-[11px]">
                      {relativeTime(conversation.last_message_at ?? conversation.started_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>
        </div>
      )}
    </div>
  );
}
