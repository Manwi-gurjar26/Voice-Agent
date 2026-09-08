"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { BookOpenText, Mic, Zap } from "lucide-react";
import { useAuth } from "@/lib/auth-context";
import { Backdrop } from "@/components/visuals/backdrop";
import { VoiceOrb } from "@/components/visuals/voice-orb";
import { Wordmark } from "@/components/visuals/brand";

const HIGHLIGHTS = [
  {
    Icon: Mic,
    title: "Voice and text, one agent",
    body: "Visitors can type or talk. Same knowledge, same answers.",
  },
  {
    Icon: BookOpenText,
    title: "Grounded in your own site",
    body: "Point it at your URL and it learns the pages you actually publish.",
  },
  {
    Icon: Zap,
    title: "One script tag to embed",
    body: "Paste a single line. No build step, no framework, no SDK.",
  },
];

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (status === "authenticated") router.replace("/overview");
  }, [status, router]);

  if (status === "authenticated") return null;

  return (
    <div className="relative flex flex-1">
      <Backdrop />

      {/* Showcase. Hidden below lg — on a phone it would push the form,
          which is the entire point of the page, below the fold. */}
      <aside className="relative hidden w-[46%] max-w-2xl flex-col justify-between overflow-hidden border-r p-10 lg:flex xl:p-14">
        <Link href="/" className="w-fit">
          <Wordmark />
        </Link>

        <div className="relative flex flex-col items-center gap-10 py-6">
          <VoiceOrb size={280} className="animate-float" />
          <div className="max-w-md text-center">
            <h2 className="display text-3xl font-bold text-balance xl:text-4xl">
              An AI agent that actually
              <span className="text-gradient"> knows your business</span>
            </h2>
            <p className="text-fg-dim mt-4 text-sm leading-relaxed text-pretty">
              Crawl your site, embed one line of code, and let visitors ask anything — by typing
              or out loud.
            </p>
          </div>
        </div>

        <ul className="flex flex-col gap-4">
          {HIGHLIGHTS.map(({ Icon, title, body }) => (
            <li key={title} className="flex items-start gap-3.5">
              <span className="border-rule text-primary mt-0.5 grid size-8 shrink-0 place-items-center rounded-md border">
                <Icon className="size-4" aria-hidden="true" />
              </span>
              <span>
                <span className="block text-[13px] font-medium">{title}</span>
                <span className="text-fg-dim block text-[13px]">{body}</span>
              </span>
            </li>
          ))}
        </ul>
      </aside>

      <main className="relative flex flex-1 items-center justify-center p-6">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Link href="/" className="w-fit">
              <Wordmark />
            </Link>
          </div>
          <div className="animate-reveal">{children}</div>
        </div>
      </main>
    </div>
  );
}
