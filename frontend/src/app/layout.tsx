import type { Metadata } from "next";
import { Libre_Franklin, Courier_Prime } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import Constellation from "@/components/effects/Constellation";

const libreFranklin = Libre_Franklin({
  variable: "--font-sans",
  subsets: ["latin"],
  display: "swap",
});

const courierPrime = Courier_Prime({
  variable: "--font-mono",
  subsets: ["latin"],
  weight: ["400", "700"],
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "ResearchNexus",
    template: "%s · ResearchNexus",
  },
  description:
    "Evidence-grounded literature review: discovery, typed research trail, and structured gap-finding from a single seed paper.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${libreFranklin.variable} ${courierPrime.variable}`}
      suppressHydrationWarning
    >
      <body className="min-h-dvh bg-surface text-ink antialiased">
        {/* The one, globally-mounted constellation instance: living in the
            root layout (not a page) means it survives every route
            navigation without remounting or restarting its animation loop.
            Negative z-index so it always paints behind normal document
            flow, whatever a given page's own stacking looks like -- an
            Operate-mode page's own opaque surface hides it completely
            (harmless), while a cinematic page (landing, sign-in, home)
            paints no opaque background of its own and lets this layer's
            dark ground and constellation show through. */}
        <div className="pointer-events-none fixed inset-0 -z-10" style={{ background: "#04060f" }}>
          <Constellation className="h-full w-full" />
        </div>
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
