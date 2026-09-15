import type { Metadata } from "next";
import { Libre_Franklin, Courier_Prime } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

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
        <a href="#main" className="skip-link">
          Skip to content
        </a>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
