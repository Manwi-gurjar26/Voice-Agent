"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { Bot, CreditCard, LogOut } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { ThemeToggle } from "@/components/ui/theme-toggle";
import { Aurora } from "@/components/visuals/aurora";
import { LogoMark, VoiceWave, Wordmark } from "@/components/visuals/brand";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/agents", label: "Agents", Icon: Bot },
  { href: "/billing", label: "Billing", Icon: CreditCard },
];

function initialsFrom(email: string | undefined): string {
  if (!email) return "?";
  const [local] = email.split("@");
  const parts = local.split(/[._-]+/).filter(Boolean);
  return (parts.length > 1 ? parts[0][0] + parts[1][0] : local.slice(0, 2)).toUpperCase();
}

function NavLinks({ pathname, onNavigate }: { pathname: string; onNavigate?: () => void }) {
  return (
    <>
      {NAV.map(({ href, label, Icon }) => {
        // startsWith, not ===, so /agents/{id} keeps "Agents" lit.
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={href}
            href={href}
            onClick={onNavigate}
            aria-current={active ? "page" : undefined}
            className={cn(
              "group relative flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-primary/10 text-foreground"
                : "text-muted-foreground hover:bg-muted/60 hover:text-foreground",
            )}
          >
            {active && (
              <span
                aria-hidden="true"
                className="bg-brand-gradient absolute top-1/2 -left-3 h-5 w-1 -translate-y-1/2 rounded-r-full"
              />
            )}
            <Icon
              className={cn("size-4.5 transition-colors", active && "text-primary")}
              aria-hidden="true"
            />
            {label}
          </Link>
        );
      })}
    </>
  );
}

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { status, user, tenant, logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "unauthenticated") router.replace("/login");
  }, [status, router]);

  // This guard is client-side only — tokens live in localStorage, not a
  // cookie, so there is nothing for Next.js middleware/proxy to read on the
  // server. An unauthenticated visitor briefly sees this loading state
  // before being redirected, rather than the protected page's content.
  if (status !== "authenticated") {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <LogoMark size={40} className="animate-float" />
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          <VoiceWave className="text-primary h-3" /> Loading your workspace…
        </p>
      </div>
    );
  }

  return (
    <div className="relative flex flex-1">
      <Aurora />

      <aside className="glass sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r lg:flex">
        <div className="px-6 py-5">
          <Link href="/agents" className="inline-flex">
            <Wordmark />
          </Link>
        </div>

        <nav className="flex flex-1 flex-col gap-1 px-6" aria-label="Main">
          <NavLinks pathname={pathname} />
        </nav>

        <div className="flex flex-col gap-3 border-t p-4">
          {tenant && (
            <div className="bg-muted/50 flex items-center justify-between rounded-xl px-3 py-2">
              <span className="min-w-0 truncate text-xs font-medium">{tenant.name}</span>
              <span className="bg-primary/10 text-primary shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold tracking-wide uppercase">
                {tenant.plan}
              </span>
            </div>
          )}

          <div className="flex items-center gap-2.5 px-1">
            <span
              aria-hidden="true"
              className="bg-brand-gradient grid size-8 shrink-0 place-items-center rounded-full text-[11px] font-bold text-white"
            >
              {initialsFrom(user?.email)}
            </span>
            <span className="text-muted-foreground min-w-0 flex-1 truncate text-xs">
              {user?.email}
            </span>
          </div>

          <div className="flex items-center justify-between gap-2">
            <ThemeToggle />
            <Button variant="ghost" size="sm" onClick={() => void logout()} className="gap-1.5">
              <LogOut className="size-3.5" aria-hidden="true" />
              Log out
            </Button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="glass sticky top-0 z-30 border-b lg:hidden">
          <div className="flex items-center justify-between gap-3 px-4 py-3">
            <Link href="/agents" className="inline-flex">
              <Wordmark />
            </Link>
            <div className="flex items-center gap-2">
              <ThemeToggle />
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void logout()}
                aria-label="Log out"
              >
                <LogOut className="size-4" aria-hidden="true" />
              </Button>
            </div>
          </div>
          <nav className="flex gap-1 px-4 pb-3" aria-label="Main">
            <NavLinks pathname={pathname} />
          </nav>
        </header>

        <main className="mx-auto w-full max-w-6xl flex-1 px-5 py-8 sm:px-8 lg:py-10">
          {children}
        </main>
      </div>
    </div>
  );
}
