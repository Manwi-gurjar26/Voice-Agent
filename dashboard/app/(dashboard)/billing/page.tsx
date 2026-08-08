"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { ArrowUpRight, Check, ExternalLink, Sparkles } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { createCheckoutSession, createPortalSession, formatApiError } from "@/lib/api";
import type { PaidPlan, PlanTier } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Tilt } from "@/components/visuals/tilt";
import { UsageRing } from "@/components/visuals/usage-ring";
import { cn } from "@/lib/utils";

const PLAN_ORDER: PlanTier[] = ["free", "starter", "pro", "enterprise"];
const PAID_PLANS: PaidPlan[] = ["starter", "pro", "enterprise"];

/** Mirrors PLAN_QUOTAS in backend/app/services/billing.py. Hand-maintained
 * for the same reason lib/types.ts is: the surface is tiny and stable, and a
 * codegen pipeline for four integers would cost more than it saves. Prices
 * are deliberately absent — they live in the merchant's Dodo dashboard and
 * differ per environment, so showing a number here would risk showing a
 * wrong one. */
const PLAN_QUOTAS: Record<PlanTier, number> = {
  free: 1_000,
  starter: 10_000,
  pro: 50_000,
  enterprise: 500_000,
};

/** Nothing in the backend gates features by tier — only the monthly message
 * quota changes — so this says exactly that rather than inventing a
 * feature matrix. */
const PLAN_PITCH: Record<PaidPlan, string> = {
  starter: "For a single site with steady traffic.",
  pro: "For busy sites, or several of them at once.",
  enterprise: "For high-volume deployments.",
};

function planRank(plan: PlanTier): number {
  return PLAN_ORDER.indexOf(plan);
}

export default function BillingPage() {
  const { tenant, refresh } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [pendingAction, setPendingAction] = useState<string | null>(null);

  useEffect(() => {
    const checkout = searchParams.get("checkout");
    if (!checkout) return;

    if (checkout === "success") {
      toast.success("Payment received — this can take a few seconds to reflect below.");
      void refresh();
    } else if (checkout === "cancelled") {
      toast.info("Checkout was cancelled — your plan hasn't changed.");
    }
    router.replace("/billing");
  }, [searchParams, router, refresh]);

  if (!tenant) return null;

  async function handleUpgrade(plan: PaidPlan) {
    setPendingAction(plan);
    try {
      const { url } = await createCheckoutSession(plan);
      window.location.href = url;
    } catch (err) {
      toast.error(formatApiError(err));
      setPendingAction(null);
    }
  }

  async function handleManageBilling() {
    setPendingAction("portal");
    try {
      const { url } = await createPortalSession();
      window.location.href = url;
    } catch (err) {
      toast.error(formatApiError(err));
      setPendingAction(null);
    }
  }

  const usagePct = Math.min(
    100,
    Math.round((tenant.messages_used_in_period / Math.max(tenant.monthly_message_quota, 1)) * 100),
  );
  const remaining = Math.max(0, tenant.monthly_message_quota - tenant.messages_used_in_period);
  const upgradeOptions = PAID_PLANS.filter((plan) => planRank(plan) > planRank(tenant.plan));

  return (
    <div className="flex flex-col gap-8">
      <header>
        <h1 className="text-3xl font-semibold tracking-tight">Billing</h1>
        <p className="text-muted-foreground mt-1.5 text-sm">
          Usage resets at the start of each billing period.
        </p>
      </header>

      <section className="bg-card/60 elev-2 sheen relative overflow-hidden rounded-2xl border p-6 backdrop-blur-sm sm:p-8">
        <span aria-hidden="true" className="bg-brand-gradient absolute inset-x-0 top-0 h-1" />
        <div className="flex flex-col items-center gap-8 sm:flex-row sm:items-center">
          <UsageRing percent={usagePct} caption="used" />

          <div className="min-w-0 flex-1 text-center sm:text-left">
            {/* "free plan" must stay one text run so it reads (and tests) as
                a single label. */}
            <h2 className="text-xl font-semibold tracking-tight capitalize">
              {tenant.plan} plan
            </h2>

            <p className="text-muted-foreground mt-2 text-sm">
              <span className="text-foreground font-semibold tabular-nums">
                {tenant.messages_used_in_period.toLocaleString()}
              </span>{" "}
              of{" "}
              <span className="text-foreground font-semibold tabular-nums">
                {tenant.monthly_message_quota.toLocaleString()}
              </span>{" "}
              messages used
            </p>

            <div className="text-muted-foreground mt-3 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-xs sm:justify-start">
              <span className="tabular-nums">{remaining.toLocaleString()} remaining</span>
              <span aria-hidden="true">·</span>
              <span>
                since {new Date(tenant.period_started_at).toLocaleDateString(undefined, {
                  day: "numeric",
                  month: "short",
                  year: "numeric",
                })}
              </span>
            </div>

            {tenant.plan !== "free" && (
              <Button
                variant="outline"
                size="sm"
                className="mt-5 gap-1.5"
                disabled={pendingAction !== null}
                onClick={() => void handleManageBilling()}
              >
                {pendingAction === "portal" ? "Opening…" : "Manage billing"}
                <ExternalLink className="size-3.5" aria-hidden="true" />
              </Button>
            )}
          </div>
        </div>
      </section>

      {upgradeOptions.length > 0 && (
        <section className="flex flex-col gap-5">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Upgrade</h2>
            <p className="text-muted-foreground mt-1 text-sm">
              Every tier has the same features — only the monthly message allowance changes.
            </p>
          </div>

          <div className="scene-3d grid gap-5 sm:grid-cols-3">
            {upgradeOptions.map((plan) => {
              const featured = plan === "pro";
              return (
                <Tilt key={plan} className="h-full">
                  <div
                    className={cn(
                      "bg-card/70 relative flex h-full flex-col overflow-hidden rounded-2xl border p-6 backdrop-blur-sm",
                      featured ? "border-primary/40 elev-3" : "elev-1",
                    )}
                  >
                    {featured && (
                      <>
                        <span
                          aria-hidden="true"
                          className="bg-brand-gradient absolute inset-x-0 top-0 h-1"
                        />
                        <span className="bg-primary/10 text-primary mb-3 inline-flex w-fit items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-semibold">
                          <Sparkles className="size-3" aria-hidden="true" />
                          Most popular
                        </span>
                      </>
                    )}

                    <h3 className="text-base font-semibold capitalize">{plan}</h3>
                    <p className="text-muted-foreground mt-1 text-xs">{PLAN_PITCH[plan]}</p>

                    <p className="mt-5 flex items-baseline gap-1.5">
                      <span className="text-2xl font-semibold tracking-tight tabular-nums">
                        {PLAN_QUOTAS[plan].toLocaleString()}
                      </span>
                      <span className="text-muted-foreground text-xs">messages / month</span>
                    </p>

                    <p className="text-muted-foreground mt-3 flex items-center gap-1.5 text-xs">
                      <Check className="text-success size-3.5 shrink-0" aria-hidden="true" />
                      Chat, voice, and website crawling
                    </p>

                    <Button
                      className={cn(
                        "mt-6 w-full",
                        featured && "bg-brand-gradient elev-2 border-0 text-white hover:opacity-95",
                      )}
                      variant={featured ? "default" : "outline"}
                      disabled={pendingAction !== null}
                      onClick={() => void handleUpgrade(plan)}
                    >
                      {pendingAction === plan ? "Redirecting…" : `Upgrade to ${plan}`}
                      {pendingAction !== plan && (
                        <ArrowUpRight className="size-4" aria-hidden="true" />
                      )}
                    </Button>
                  </div>
                </Tilt>
              );
            })}
          </div>
        </section>
      )}
    </div>
  );
}
