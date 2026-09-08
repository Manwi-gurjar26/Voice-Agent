"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth-context";
import { Wordmark } from "@/components/visuals/brand";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "#how", label: "How it works" },
  { href: "#voice", label: "Voice" },
  { href: "#demo", label: "Demo" },
  { href: "#pricing", label: "Pricing" },
];

/** The marketing shell: a 56px sticky bar that only grows a hairline and a
 * blur once the page has actually scrolled, and a ruled footer. Both are
 * deliberately the full 1280px measure while the page content inside is
 * narrower — the chrome frames the content rather than aligning to it. */
export default function MarketingLayout({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const signedIn = status === "authenticated";

  return (
    <div className="flex min-h-dvh flex-col">
      <header
        className={cn(
          "fixed inset-x-0 top-0 z-50 transition-colors duration-300",
          scrolled && "glass border-b",
        )}
      >
        <div className="mx-auto flex h-14 max-w-[1280px] items-center justify-between px-5 sm:px-8">
          <Link href="/" aria-label="Voice Agent, home">
            <Wordmark />
          </Link>

          <nav className="hidden items-center gap-6 md:flex" aria-label="Sections">
            {NAV.map(({ href, label }) => (
              <a
                key={href}
                href={href}
                className="link text-fg-dim hover:text-foreground text-[13px] transition-colors"
              >
                {label}
              </a>
            ))}
          </nav>

          <div className="flex items-center gap-1.5">
            {signedIn ? (
              <Link
                href="/overview"
                className="bg-primary text-primary-foreground hover:bg-primary/85 rounded-md px-3 py-1.5 text-[13px] font-semibold transition-colors"
              >
                Dashboard
              </Link>
            ) : (
              <>
                <Link
                  href="/login"
                  className="text-fg-dim hover:text-foreground rounded-md px-3 py-1.5 text-[13px] transition-colors"
                >
                  Log in
                </Link>
                <Link
                  href="/signup"
                  className="bg-primary text-primary-foreground hover:bg-primary/85 rounded-md px-3 py-1.5 text-[13px] font-semibold transition-colors"
                >
                  Start free
                </Link>
              </>
            )}
          </div>
        </div>
      </header>

      <main id="main" className="flex-1">
        {children}
      </main>

      <footer className="border-t">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center justify-between gap-x-6 gap-y-4 px-5 py-8 sm:px-8">
          <Wordmark />
          <p className="text-fg-faint text-xs">
            Chat and voice agents, embedded with one script tag.
          </p>
          <nav className="flex items-center gap-5" aria-label="Footer">
            <Link href="/login" className="link text-fg-dim text-xs">
              Log in
            </Link>
            <Link href="/signup" className="link text-fg-dim text-xs">
              Create account
            </Link>
          </nav>
        </div>
      </footer>
    </div>
  );
}
