"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import Link from "next/link";
import { Bot, CreditCard, LayoutGrid, LogOut, MessagesSquare } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { Button } from "@/components/ui/button";
import { Backdrop } from "@/components/visuals/backdrop";
import { LogoMark, VoiceWave, Wordmark } from "@/components/visuals/brand";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/overview", label: "Overview", Icon: LayoutGrid },
  { href: "/agents", label: "Agents", Icon: Bot },
  { href: "/playground", label: "Playground", Icon: MessagesSquare },
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
              "group relative flex items-center gap-2.5 rounded-md px-2.5 py-1.5 text-[13px] transition-colors",
              active
                ? "bg-secondary text-foreground font-medium"
                : "text-fg-dim hover:bg-secondary/60 hover:text-foreground",
            )}
          >
            {active && (
              <span
                aria-hidden="true"
                className="bg-primary absolute top-1/2 -left-2.5 h-4 w-0.5 -translate-y-1/2 rounded-r-full"
              />
            )}
            <Icon
              className={cn("size-4 transition-colors", active && "text-primary")}
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
        <LogoMark size={36} className="animate-float" />
        <p className="text-fg-faint flex items-center gap-2 text-xs">
          <VoiceWave className="text-primary h-3" /> Loading your workspace…
        </p>
      </div>
    );
  }

  return (
    <div className="relative flex flex-1">
      {/* No bloom behind the dashboard: even a faint magenta wash tints the
          chart fills, and these screens are read, not admired. */}
      <Backdrop bloom={false} />

      <aside className="glass sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r lg:flex">
        <div className="flex h-14 items-center px-5">
          <Link href="/overview" className="inline-flex">
            <Wordmark />
          </Link>
        </div>

        <nav className="flex flex-1 flex-col gap-0.5 px-5 pt-3" aria-label="Main">
          <NavLinks pathname={pathname} />
        </nav>

        <div className="flex flex-col gap-3 border-t p-4">
          {tenant && (
            <div className="border-rule flex items-center justify-between rounded-md border px-2.5 py-2">
              <span className="min-w-0 truncate text-xs">{tenant.name}</span>
              <span className="mono-fig text-primary shrink-0 text-[10px] tracking-wider uppercase">
                {tenant.plan}
              </span>
            </div>
          )}

          <div className="flex items-center gap-2.5 px-0.5">
            <span
              aria-hidden="true"
              className="border-rule-strong text-primary mono-fig grid size-7 shrink-0 place-items-center rounded-md border text-[10px] font-bold"
            >
              {initialsFrom(user?.email)}
            </span>
            <span className="text-fg-faint min-w-0 flex-1 truncate text-[11px]">
              {user?.email}
            </span>
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => void logout()}
              aria-label="Log out"
              className="text-fg-faint hover:text-foreground shrink-0"
            >
              <LogOut className="size-3.5" aria-hidden="true" />
            </Button>
          </div>
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="glass sticky top-0 z-30 border-b lg:hidden">
          <div className="flex h-14 items-center justify-between gap-3 px-4">
            <Link href="/overview" className="inline-flex">
              <Wordmark />
            </Link>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => void logout()}
              aria-label="Log out"
              className="text-fg-dim"
            >
              <LogOut className="size-4" aria-hidden="true" />
            </Button>
          </div>
          <nav className="flex gap-1 overflow-x-auto px-4 pb-2.5" aria-label="Main">
            <NavLinks pathname={pathname} />
          </nav>
        </header>

        <main className="mx-auto w-full max-w-[1280px] flex-1 px-5 py-8 sm:px-8 lg:py-10">
          {children}
        </main>
      </div>
    </div>
  );
}
