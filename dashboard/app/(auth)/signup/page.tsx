"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import { ArrowRight, Building2, LockKeyhole, Mail, User } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { formatApiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardFooter, CardHeader } from "@/components/ui/card";

// Deliberately minimal: the real password policy (minimum length, mixed
// character classes) lives in backend/app/schemas/auth.py and is surfaced
// via its own validation error rather than duplicated here and risking drift.
const signupSchema = z.object({
  email: z.string().email("Enter a valid email address."),
  password: z.string().min(1, "Password is required."),
  full_name: z.string().optional(),
  company_name: z.string().min(1, "Workspace name is required."),
});
type SignupFormValues = z.infer<typeof signupSchema>;

const FIELD_ICON = "text-muted-foreground pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2";

export default function SignupPage() {
  const { signup } = useAuth();
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<SignupFormValues>({ resolver: zodResolver(signupSchema) });

  async function onSubmit(values: SignupFormValues) {
    setSubmitting(true);
    try {
      await signup({
        ...values,
        full_name: values.full_name?.trim() ? values.full_name.trim() : null,
      });
      router.replace("/agents");
    } catch (err) {
      toast.error(formatApiError(err));
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Card className="glass-strong elev-3 sheen relative rounded-2xl py-6 ring-0">
      <CardHeader className="gap-2">
        <h1 className="text-2xl font-semibold tracking-tight">Create your workspace</h1>
        <p className="text-muted-foreground text-sm">
          Free to start — no card required.
        </p>
      </CardHeader>

      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-2">
            <Label htmlFor="company_name">Workspace name</Label>
            <div className="relative">
              <Building2 className={FIELD_ICON} aria-hidden="true" />
              <Input
                id="company_name"
                autoComplete="organization"
                placeholder="Acme Inc"
                className="h-11 pl-9"
                aria-invalid={errors.company_name ? true : undefined}
                {...register("company_name")}
              />
            </div>
            {errors.company_name && (
              <p className="text-destructive text-sm">{errors.company_name.message}</p>
            )}
          </div>

          <div className="flex flex-col gap-2">
            <Label htmlFor="full_name">Your name (optional)</Label>
            <div className="relative">
              <User className={FIELD_ICON} aria-hidden="true" />
              <Input
                id="full_name"
                autoComplete="name"
                placeholder="Ada Lovelace"
                className="h-11 pl-9"
                {...register("full_name")}
              />
            </div>
          </div>

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

          <div className="flex flex-col gap-2">
            <Label htmlFor="password">Password</Label>
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
            {submitting ? "Creating workspace…" : "Create workspace"}
            {!submitting && (
              <ArrowRight
                className="size-4 transition-transform group-hover:translate-x-0.5"
                aria-hidden="true"
              />
            )}
          </Button>
          <p className="text-muted-foreground text-sm">
            Already have an account?{" "}
            <Link href="/login" className="text-foreground font-medium underline-offset-4 hover:underline">
              Log in
            </Link>
          </p>
        </CardFooter>
      </form>
    </Card>
  );
}
