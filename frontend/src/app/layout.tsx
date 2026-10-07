import type { Metadata } from "next";
import { Libre_Franklin, Courier_Prime } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";
import BackgroundHost from "@/components/effects/BackgroundHost";

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
      data-theme="dark"
      className={`${libreFranklin.variable} ${courierPrime.variable}`}
      suppressHydrationWarning
    >
      {/* every page sits in the one dark world: the ground is navy even
          before the background layer paints, and past it on overscroll */}
      <body className="min-h-dvh bg-[#04060f] text-[#f3f6ff] antialiased">
        {/* The one, globally-mounted background (BackgroundHost: the neural
            network, GhostFibers or a still ground, by device and setting):
            living in the root layout (not a page) means it survives every route
            navigation without remounting or restarting its animation loop.
            Negative z-index so it always paints behind normal document
            flow, whatever a given page's own stacking looks like -- an
            Operate-mode page's own opaque surface hides it completely
            (harmless), while a cinematic page (landing, sign-in, home)
            paints no opaque background of its own and lets this layer's
            dark ground and constellation show through. */}
        <div className="pointer-events-none fixed inset-0 -z-10" style={{ background: "#04060f" }}>
          <BackgroundHost />
        </div>
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
