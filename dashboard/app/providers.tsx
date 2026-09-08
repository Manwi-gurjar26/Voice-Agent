"use client";

import { ThemeProvider } from "next-themes";
import { AuthProvider } from "@/lib/auth-context";
import { Toaster } from "@/components/ui/sonner";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    /* forcedTheme, not defaultTheme: the palette is dark-only, so this exists
       purely so the components that read useTheme() (sonner's Toaster) get a
       correct answer instead of resolving `system` and rendering light toasts
       on a black page. Nothing in the UI can change it. */
    <ThemeProvider attribute="class" forcedTheme="dark" enableSystem={false}>
      <AuthProvider>
        {children}
        <Toaster />
      </AuthProvider>
    </ThemeProvider>
  );
}
