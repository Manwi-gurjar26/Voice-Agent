"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { useAuth } from "@/lib/auth-context";
import { createCheckoutSession, createPortalSession, formatApiError } from "@/lib/api";
import type { PaidPlan, PlanTier } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";

const PLAN_ORDER: PlanTier[] = ["free", "starter", "pro", "enterprise"];
const PAID_PLANS: PaidPlan[] = ["starter", "pro", "enterprise"];

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
  const upgradeOptions = PAID_PLANS.filter((plan) => planRank(plan) > planRank(tenant.plan));

  return (
    <div className="flex flex-col gap-6">
      <h1 className="text-xl font-semibold">Billing</h1>

      <Card>
        <CardHeader>
          <CardTitle className="capitalize">{tenant.plan} plan</CardTitle>
          <CardDescription>
            {tenant.messages_used_in_period.toLocaleString()} /{" "}
            {tenant.monthly_message_quota.toLocaleString()} messages used this period (since{" "}
            {new Date(tenant.period_started_at).toLocaleDateString()})
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
            <div className="h-full rounded-full bg-primary" style={{ width: `${usagePct}%` }} />
          </div>
          {tenant.plan !== "free" && (
            <Button
              variant="outline"
              size="sm"
              className="self-start"
              disabled={pendingAction !== null}
              onClick={() => void handleManageBilling()}
            >
              {pendingAction === "portal" ? "Opening…" : "Manage billing"}
            </Button>
          )}
        </CardContent>
      </Card>

      {upgradeOptions.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-3">
          {upgradeOptions.map((plan) => (
            <Card key={plan}>
              <CardHeader>
                <CardTitle className="capitalize">{plan}</CardTitle>
              </CardHeader>
              <CardContent>
                <Button
                  className="w-full"
                  disabled={pendingAction !== null}
                  onClick={() => void handleUpgrade(plan)}
                >
                  {pendingAction === plan ? "Redirecting…" : `Upgrade to ${plan}`}
                </Button>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  );
}
