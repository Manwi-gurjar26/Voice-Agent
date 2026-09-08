"use client";

import Link from "next/link";
import {
  ArrowRight,
  BookOpenText,
  Check,
  Gauge,
  Globe,
  Mic,
  Quote,
  ShieldCheck,
  Timer,
  Zap,
} from "lucide-react";
import { Backdrop } from "@/components/visuals/backdrop";
import { VoiceOrb } from "@/components/visuals/voice-orb";
import { VoiceWave } from "@/components/visuals/brand";
import { DemoChat } from "@/components/marketing/demo-chat";
import { cn } from "@/lib/utils";

/* The container measure and the 56px header offset are the two numbers every
   section on this page agrees on; naming them keeps that agreement explicit
   instead of repeated as a literal fourteen times. */
const SHELL = "mx-auto w-full max-w-[1280px] px-5 sm:px-8";

const EMBED_SNIPPET = `<script src="https://cdn.example.com/widget.js"
        data-agent-key="agt_pub_7f3c…"
        async></script>`;

/** What the marquee scrolls. Real questions rather than customer logos: this
 * product has no logo wall yet, and inventing one would be a lie. What it
 * does have is a clear answer to "what would people actually ask it". */
const QUESTIONS = [
  "what's your refund window?",
  "do you integrate with Shopify?",
  "is there a student discount?",
  "how long does onboarding take?",
  "can I export my data?",
  "do you ship to Germany?",
  "what happens when I hit my limit?",
  "is my data used for training?",
];

const STEPS = [
  {
    n: "01",
    title: "Point it at your site",
    body: "Give it a URL and it crawls the pages you already publish — docs, pricing, policies, FAQs. Or paste text and upload files directly.",
    Icon: Globe,
  },
  {
    n: "02",
    title: "Set its voice and its limits",
    body: "Name it, write the system prompt, pick a speaking voice, and lock it to the domains you allow. Every answer stays inside what you gave it.",
    Icon: Mic,
  },
  {
    n: "03",
    title: "Paste one script tag",
    body: "No build step, no framework, no SDK. The widget mounts inside a shadow root, so your CSS and its CSS never meet.",
    Icon: Zap,
  },
];

const FEATURES = [
  {
    Icon: BookOpenText,
    title: "Answers with receipts",
    body: "Retrieval runs before every reply, and the reply carries the page it came from. When the knowledge base has nothing, it says so instead of inventing.",
  },
  {
    Icon: Mic,
    title: "One agent, two channels",
    body: "Typed and spoken share the same prompt, the same knowledge, and the same thread — a visitor can start talking and finish typing.",
  },
  {
    Icon: ShieldCheck,
    title: "Locked to your domains",
    body: "Each agent carries an origin allowlist checked on every request, plus a per-visitor rate limit. A copied script tag on another site does nothing.",
  },
  {
    Icon: Timer,
    title: "Streams from the first token",
    body: "Replies arrive as they are generated over SSE, so the visitor sees an answer forming instead of a spinner.",
  },
  {
    Icon: Gauge,
    title: "Metered, not surprising",
    body: "A live message count against your plan's allowance, per agent and per day, with the token spend behind it.",
  },
  {
    Icon: Globe,
    title: "Weighs almost nothing",
    body: "The widget is a small async script that mounts after your page is interactive. Your Core Web Vitals do not move.",
  },
];

/** Mirrors PLAN_QUOTAS in backend/app/services/billing.py. Prices are
 * deliberately absent — they live in the merchant's Dodo dashboard and differ
 * per environment, so a number here would risk being the wrong one. */
const PLANS = [
  { name: "Free", quota: "1,000", pitch: "Enough to put one agent on one site and see what it does.", cta: "Start free" },
  { name: "Starter", quota: "10,000", pitch: "A single site with steady traffic.", cta: "Start free" },
  { name: "Pro", quota: "50,000", pitch: "Busy sites, or several of them at once.", cta: "Start free", featured: true },
  { name: "Enterprise", quota: "500,000", pitch: "High-volume deployments.", cta: "Start free" },
];

function Eyebrow({ children, sunray = false }: { children: React.ReactNode; sunray?: boolean }) {
  return <p className={cn("eyebrow w-fit", sunray && "sunray")}>{children}</p>;
}

export default function LandingPage() {
  return (
    <>
      <Backdrop />

      {/* ------------------------------------------------------------------
          Hero. Left-weighted rather than centred: a centred hero forces every
          line to be short, and the one thing that has to land here is a
          sentence, not a slogan.
      ------------------------------------------------------------------ */}
      <section className={cn(SHELL, "relative pt-28 pb-16 lg:pt-36 lg:pb-24")}>
        <div className="grid items-center gap-12 lg:grid-cols-[minmax(0,1fr)_auto] lg:gap-16">
          <div className="max-w-2xl">
            <Eyebrow sunray>Chat + voice · one script tag</Eyebrow>

            <h1 className="display mt-5 text-[clamp(2.6rem,1.6rem+3.6vw,4.6rem)] leading-[0.98] font-bold">
              An agent that answers
              <br />
              for you — out loud.
            </h1>

            <p className="prose-measure text-fg-dim mt-6 text-[15px] sm:text-base">
              Point it at your own pages, and it answers your visitors in text or in speech,
              grounded in what you actually published. It cites the page it used, refuses what it
              does not know, and mounts on your site with a single line of HTML.
            </p>

            <div className="mt-8 flex flex-wrap items-center gap-3">
              <Link
                href="/signup"
                className="bg-primary text-primary-foreground hover:bg-primary/85 group inline-flex items-center gap-2 rounded-md px-4 py-2.5 text-sm font-semibold transition-colors"
              >
                Build your agent
                <ArrowRight
                  className="size-4 transition-transform group-hover:translate-x-0.5"
                  aria-hidden="true"
                />
              </Link>
              <a
                href="#demo"
                className="border-rule-strong hover:bg-secondary inline-flex items-center gap-2 rounded-md border px-4 py-2.5 text-sm font-medium transition-colors"
              >
                <VoiceWave className="text-primary h-3" bars={4} />
                See it answer
              </a>
            </div>

            {/* The actual snippet, not a picture of one — the promise of the
                headline is that this is all there is. */}
            <div className="border-rule-strong mt-10 max-w-xl overflow-hidden rounded-lg border">
              <div className="text-fg-faint flex items-center gap-2 border-b px-3 py-2">
                <span className="flex gap-1.5" aria-hidden="true">
                  <span className="bg-fg-faint/40 size-2 rounded-full" />
                  <span className="bg-fg-faint/40 size-2 rounded-full" />
                  <span className="bg-fg-faint/40 size-2 rounded-full" />
                </span>
                <span className="mono-fig text-[10px]">index.html</span>
              </div>
              <pre className="terminal text-fg-dim overflow-x-auto px-3.5 py-3">
                <code>{EMBED_SNIPPET}</code>
              </pre>
            </div>
          </div>

          <div className="hidden justify-center lg:flex">
            <VoiceOrb size={320} className="animate-float" />
          </div>
        </div>
      </section>

      {/* Marquee of real questions. */}
      <section className="overflow-hidden border-y py-4" aria-hidden="true">
        <div className="marquee">
          <div className="marquee-track flex w-max items-center">
            {[0, 1].map((copy) => (
              <div key={copy} className="flex shrink-0 items-center">
                {QUESTIONS.map((q) => (
                  <span
                    key={`${copy}-${q}`}
                    className="mono-fig text-fg-faint flex items-center gap-6 px-6 text-xs whitespace-nowrap"
                  >
                    <Quote className="size-3 opacity-50" />
                    {q}
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ------------------------------------------------------------------
          How it works — a ruled three-column grid, not three floating cards.
          The rules are the layout; on a black ground they read as structure
          where a card's border reads as a box.
      ------------------------------------------------------------------ */}
      <section id="how" className={cn(SHELL, "scroll-mt-20 py-20 lg:py-28")}>
        <Eyebrow>How it works</Eyebrow>
        <h2 className="display mt-4 max-w-2xl text-[clamp(1.9rem,1.3rem+2vw,3rem)] leading-[1.05] font-bold">
          Three steps, and it is answering.
        </h2>

        <div className="mt-12 grid border-t md:grid-cols-3">
          {STEPS.map(({ n, title, body, Icon }) => (
            <div
              key={n}
              className="group relative flex flex-col gap-4 border-b px-0 py-8 md:border-r md:px-7 md:last:border-r-0 md:first:pl-0"
            >
              <div className="flex items-center gap-3">
                <span className="mono-fig text-primary text-xs">{n}</span>
                <span className="bg-rule h-px flex-1" aria-hidden="true" />
                <Icon className="text-fg-faint size-4" aria-hidden="true" />
              </div>
              <h3 className="text-base font-semibold">{title}</h3>
              <p className="text-fg-dim text-sm leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------------
          Voice — the half of the product a screenshot cannot show, so it gets
          its own section with the orb rather than a sixth feature cell.
      ------------------------------------------------------------------ */}
      <section id="voice" className="scroll-mt-20 border-y">
        <div className={cn(SHELL, "grid items-center gap-12 py-20 lg:grid-cols-2 lg:py-28")}>
          <div className="order-2 flex justify-center lg:order-1">
            <VoiceOrb size={300} />
          </div>
          <div className="order-1 lg:order-2">
            <Eyebrow>Voice</Eyebrow>
            <h2 className="display mt-4 text-[clamp(1.9rem,1.3rem+2vw,3rem)] leading-[1.05] font-bold">
              Some visitors would rather just ask.
            </h2>
            <p className="prose-measure text-fg-dim mt-5 text-sm sm:text-[15px]">
              Tap the mic and talk. It transcribes, retrieves against your knowledge base, answers,
              and speaks the answer back — holding one voice and one language for the whole
              conversation, and detecting speech relative to the room rather than a fixed loudness,
              so it works in a café as well as an office.
            </p>
            <ul className="mt-7 flex flex-col gap-3">
              {[
                "Speech in, speech out, on the same thread as typed messages.",
                "The same retrieval and the same citations as the text channel.",
                "If speech synthesis fails, the reply still arrives — as text.",
              ].map((line) => (
                <li key={line} className="text-fg-dim flex items-start gap-2.5 text-sm">
                  <Check className="text-primary mt-0.5 size-4 shrink-0" aria-hidden="true" />
                  {line}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Feature grid. */}
      <section className={cn(SHELL, "py-20 lg:py-28")}>
        <Eyebrow>What you get</Eyebrow>
        <h2 className="display mt-4 max-w-2xl text-[clamp(1.9rem,1.3rem+2vw,3rem)] leading-[1.05] font-bold">
          Everything the demo implies, actually built.
        </h2>

        <div className="mt-12 grid border-t sm:grid-cols-2 lg:grid-cols-3">
          {FEATURES.map(({ Icon, title, body }) => (
            <div
              key={title}
              className={cn(
                "flex flex-col gap-3 border-b py-8 sm:px-7 sm:odd:pl-0 lg:px-7",
                // Vertical rules between columns, dropped on the last item in
                // each row so the grid does not end with a stray hairline.
                "sm:border-r sm:even:border-r-0 lg:even:border-r lg:[&:nth-child(3n)]:border-r-0 lg:first:pl-0",
              )}
            >
              <Icon className="text-primary size-4.5" aria-hidden="true" />
              <h3 className="text-[15px] font-semibold">{title}</h3>
              <p className="text-fg-dim text-sm leading-relaxed">{body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------------
          Demo.
      ------------------------------------------------------------------ */}
      <section id="demo" className="scroll-mt-20 border-y">
        <div className={cn(SHELL, "grid items-center gap-12 py-20 lg:grid-cols-2 lg:py-28")}>
          <div>
            <Eyebrow>Demo</Eyebrow>
            <h2 className="display mt-4 text-[clamp(1.9rem,1.3rem+2vw,3rem)] leading-[1.05] font-bold">
              This is what your visitor sees.
            </h2>
            <p className="prose-measure text-fg-dim mt-5 text-sm sm:text-[15px]">
              A replay of a real thread, in the real widget chrome — including the citation line
              under an answer that came out of the knowledge base. Switch it to voice to see the
              spoken mode.
            </p>
            <p className="text-fg-faint mt-4 text-xs">
              Scripted, so the page costs nothing to load. To talk to{" "}
              <span className="text-fg-dim">your own</span> agent — including one still in draft —
              open the Playground once you have signed in.
            </p>
            <div className="mt-7 flex flex-wrap gap-3">
              <Link
                href="/signup"
                className="bg-primary text-primary-foreground hover:bg-primary/85 inline-flex items-center gap-2 rounded-md px-4 py-2.5 text-sm font-semibold transition-colors"
              >
                Try it on your own content
                <ArrowRight className="size-4" aria-hidden="true" />
              </Link>
              <Link
                href="/playground"
                className="border-rule-strong hover:bg-secondary inline-flex items-center gap-2 rounded-md border px-4 py-2.5 text-sm font-medium transition-colors"
              >
                Open Playground
              </Link>
            </div>
          </div>

          <DemoChat />
        </div>
      </section>

      {/* ------------------------------------------------------------------
          Pricing. Message allowances only — every tier has the same features,
          so a feature matrix with identical columns would be theatre.
      ------------------------------------------------------------------ */}
      <section id="pricing" className={cn(SHELL, "scroll-mt-20 py-20 lg:py-28")}>
        <Eyebrow>Pricing</Eyebrow>
        <h2 className="display mt-4 max-w-2xl text-[clamp(1.9rem,1.3rem+2vw,3rem)] leading-[1.05] font-bold">
          One product. You pick the volume.
        </h2>
        <p className="prose-measure text-fg-dim mt-5 text-sm">
          Chat, voice, crawling and citations are in every tier — the only thing that changes is the
          monthly message allowance. Start on Free; upgrade from the dashboard when you outgrow it.
        </p>

        <div className="mt-12 grid gap-px sm:grid-cols-2 lg:grid-cols-4">
          {PLANS.map(({ name, quota, pitch, cta, featured }) => (
            <div
              key={name}
              className={cn(
                "relative flex flex-col gap-4 border p-6",
                featured ? "border-primary/40 bg-primary/[0.04]" : "border-rule",
              )}
            >
              {featured && (
                <span className="bg-primary text-primary-foreground absolute -top-px right-4 rounded-b px-2 py-0.5 text-[10px] font-bold tracking-wide uppercase">
                  Popular
                </span>
              )}
              <h3 className="text-sm font-semibold">{name}</h3>
              <p>
                <span className="mono-fig text-3xl font-semibold tracking-tight">{quota}</span>
                <span className="text-fg-faint block text-xs">messages / month</span>
              </p>
              <p className="text-fg-dim flex-1 text-xs leading-relaxed">{pitch}</p>
              <Link
                href="/signup"
                className={cn(
                  "mt-2 rounded-md px-3 py-2 text-center text-[13px] font-semibold transition-colors",
                  featured
                    ? "bg-primary text-primary-foreground hover:bg-primary/85"
                    : "border-rule-strong hover:bg-secondary border",
                )}
              >
                {cta}
              </Link>
            </div>
          ))}
        </div>
      </section>

      {/* Closing CTA. */}
      <section className="border-t">
        <div className={cn(SHELL, "flex flex-col items-start gap-6 py-20 lg:py-28")}>
          <h2 className="display max-w-3xl text-[clamp(2rem,1.4rem+2.4vw,3.4rem)] leading-[1.02] font-bold">
            Your pages already have the answers.
            <span className="text-fg-faint"> Give them a voice.</span>
          </h2>
          <Link
            href="/signup"
            className="bg-primary text-primary-foreground hover:bg-primary/85 group inline-flex items-center gap-2 rounded-md px-5 py-3 text-sm font-semibold transition-colors"
          >
            Create your first agent
            <ArrowRight
              className="size-4 transition-transform group-hover:translate-x-0.5"
              aria-hidden="true"
            />
          </Link>
          <p className="text-fg-faint text-xs">
            Free tier, no card. 1,000 messages a month to see whether it earns its place.
          </p>
        </div>
      </section>
    </>
  );
}
