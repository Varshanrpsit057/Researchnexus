import type { NextConfig } from "next";

/**
 * Production builds are self-contained (`output: "standalone"`: the server
 * and only the files it needs, for the container image) and send security
 * headers with every page. Development (`next dev`) is untouched: hot reload
 * needs eval and its own websocket, which the policy below would block.
 */

// The API's origin when it isn't this site's (NEXT_PUBLIC_API_BASE_URL set to
// another address, e.g. http://localhost:8000 locally); empty in a deployment
// that serves the API under /api on the app's own address.
function apiOrigin(): string {
  const base = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
  try {
    return base ? new URL(base).origin : "";
  } catch {
    return "";
  }
}

const contentSecurityPolicy = [
  "default-src 'self'",
  // Next's own inline bootstrapping scripts need 'unsafe-inline' without a per-request nonce
  "script-src 'self' 'unsafe-inline'",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin()}`.trim(),
  // the neural-network background renders in a worker bundled with the app
  "worker-src 'self' blob:",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: contentSecurityPolicy },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  // ignored by browsers over plain http (a local container), kept over https
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async headers() {
    if (process.env.NODE_ENV !== "production") return [];
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
