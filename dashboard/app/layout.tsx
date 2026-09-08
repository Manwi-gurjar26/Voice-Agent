import type { Metadata } from "next";
import { Geist, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

/* JetBrains Mono rather than Geist Mono: every figure in the dashboard is
   set in it (stat readouts, token counts, chart axes, public keys, the embed
   snippet), and its wider aperture and slashed zero stay legible at the
   11–13px those land at. */
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Voice Agent — an agent that talks, on your own site",
    template: "%s · Voice Agent",
  },
  description:
    "One embeddable agent that answers in text or out loud, grounded in your own pages. Crawl your site, paste one script tag, ship.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    /* `dark` is hard-coded, not toggled. The palette in globals.css is
       dark-only by design, so leaving next-themes free to resolve `light`
       here would render an unstyled black-on-black page for a second before
       hydration corrected it.

       suppressHydrationWarning is still required even with the class fixed:
       next-themes writes `style="color-scheme: dark"` onto this element
       before React hydrates, which is an attribute the server never rendered.
       Without it every page logs a hydration mismatch. Scoped to <html> only,
       and it suppresses the warning for this element's attributes alone — not
       for any real mismatch inside the tree. */
    <html
      lang="en"
      suppressHydrationWarning
      className={`dark ${geistSans.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
