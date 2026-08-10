"use client";

import { useState } from "react";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight, Mail } from "lucide-react";
import { forgotPassword, formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";

const forgotPasswordSchema = z.object({
  email: z.string().email("Enter a valid email address."),
});
type ForgotPasswordFormValues = z.infer<typeof forgotPasswordSchema>;

const FIELD_ICON = "text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2";

export default function ForgotPasswordPage() {
  const [submitting, setSubmitting] = useState(false);
  const [sent, setSent] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<ForgotPasswordFormValues>({ resolver: zodResolver(forgotPasswordSchema) });

  async function onSubmit(values: ForgotPasswordFormValues) {
    setSubmitting(true);
    try {
      await forgotPassword(values.email);
      // Always the same outcome regardless of whether the address exists —
      // the backend's response is identical either way (see
      // backend/app/services/auth.py's request_password_reset), so this
      // page must not create a different one on top of it.
      setSent(true);
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  if (sent) {
    return (
      <Card className="glass-strong elev-3 sheen relative rounded-2xl py-6 ring-0">
        <CardHeader className="gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Check your email</h1>
          <p className="text-muted-foreground text-sm">
            If an account exists for that address, we&apos;ve sent a link to reset your
            password.
          </p>
        </CardHeader>
        <CardFooter className="mt-2 flex flex-col gap-4 border-t-0 bg-transparent pt-0">
          <Link
            href="/login"
            className="text-foreground flex items-center gap-1.5 text-sm font-medium underline-offset-4 hover:underline"
          >
            <ArrowLeft className="size-3.5" aria-hidden="true" />
            Back to login
          </Link>
        </CardFooter>
      </Card>
    );
  }

  return (
    <Card className="glass-strong elev-3 sheen relative rounded-2xl py-6 ring-0">
      <CardHeader className="gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Forgot your password?</h1>
        <p className="text-muted-foreground text-sm">
          Enter your email and we&apos;ll send you a reset link.
        </p>
      </CardHeader>

      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="email">Email</Label>
            <div className="relative">
              <Mail className={FIELD_ICON} aria-hidden="true" />
              <Input
                id="email"
                type="email"
                autoComplete="email"
                placeholder="you@company.com"
                className="h-11 pl-9"
                aria-invalid={errors.email ? true : undefined}
                {...register("email")}
              />
            </div>
            {errors.email && <p className="text-destructive text-sm">{errors.email.message}</p>}
          </div>
        </CardContent>

        <CardFooter className="mt-6 flex flex-col gap-4 border-t-0 bg-transparent pt-0">
          <Button
            type="submit"
            disabled={submitting}
            className="bg-brand-gradient elev-2 group h-11 w-full border-0 text-white hover:opacity-95"
          >
            {submitting ? "Sending…" : "Send reset link"}
            {!submitting && (
              <ArrowRight
                className="size-4 transition-transform group-hover:translate-x-0.5"
                aria-hidden="true"
              />
            )}
          </Button>
          <Link
            href="/login"
            className="text-muted-foreground flex items-center gap-1.5 text-sm underline-offset-4 hover:underline"
          >
            <ArrowLeft className="size-3.5" aria-hidden="true" />
            Back to login
          </Link>
        </CardFooter>
      </form>
    </Card>
  );
}
