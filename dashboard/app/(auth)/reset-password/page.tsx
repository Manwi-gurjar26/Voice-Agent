"use client";

import { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ArrowRight, LockKeyhole } from "lucide-react";
import { formatApiError, resetPassword } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";

const resetPasswordSchema = z.object({
  password: z.string().min(1, "Password is required."),
});
type ResetPasswordFormValues = z.infer<typeof resetPasswordSchema>;

const FIELD_ICON = "text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2";

// useSearchParams() opts this into client-only rendering, which Next.js
// requires a Suspense boundary around for static prerendering to succeed
// (confirmed by the actual `next build` output, not assumed) — the default
// export below only adds that wrapper; ResetPasswordForm has the real page.
export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordForm />
    </Suspense>
  );
}

function ResetPasswordForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const token = searchParams.get("token");
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ResetPasswordFormValues>({ resolver: zodResolver(resetPasswordSchema) });

  async function onSubmit(values: ResetPasswordFormValues) {
    if (!token) return;
    setSubmitting(true);
    try {
      await resetPassword(token, values.password);
      toast.success("Password updated — log in with your new password.");
      router.replace("/login");
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (!token) {
    return (
      <Card className="glass-strong elev-3 sheen relative rounded-2xl py-6 ring-0">
        <CardHeader className="gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Invalid link</h1>
          <p className="text-muted-foreground text-sm">
            This password reset link is missing or malformed. Request a new one below.
          </p>
        </CardHeader>
        <CardFooter className="mt-2 flex flex-col gap-4 border-t-0 bg-transparent pt-0">
          <Button
            render={<Link href="/forgot-password" />}
            nativeButton={false}
            className="bg-brand-gradient elev-2 h-11 w-full border-0 text-white hover:opacity-95"
          >
            Request a new link
          </Button>
        </CardFooter>
      </Card>
    );
  }

  return (
    <Card className="glass-strong elev-3 sheen relative rounded-2xl py-6 ring-0">
      <CardHeader className="gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Set a new password</h1>
        <p className="text-muted-foreground text-sm">Choose a new password for your account.</p>
      </CardHeader>

      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="password">New password</Label>
            <div className="relative">
              <LockKeyhole className={FIELD_ICON} aria-hidden="true" />
              <Input
                id="password"
                type="password"
                autoComplete="new-password"
                placeholder="••••••••••••"
                className="h-11 pl-9"
                aria-invalid={errors.password ? true : undefined}
                {...register("password")}
              />
            </div>
            {errors.password && (
              <p className="text-destructive text-sm">{errors.password.message}</p>
            )}
            <p className="text-muted-foreground text-xs">
              At least 12 characters, mixing letters with numbers or symbols.
            </p>
          </div>
        </CardContent>

        <CardFooter className="mt-6 flex flex-col gap-4 border-t-0 bg-transparent pt-0">
          <Button
            type="submit"
            disabled={submitting}
            className="bg-brand-gradient elev-2 group h-11 w-full border-0 text-white hover:opacity-95"
          >
            {submitting ? "Saving…" : "Reset password"}
            {!submitting && (
              <ArrowRight
                className="size-4 transition-transform group-hover:translate-x-0.5"
                aria-hidden="true"
              />
            )}
          </Button>
        </CardFooter>
      </form>
    </Card>
  );
}
