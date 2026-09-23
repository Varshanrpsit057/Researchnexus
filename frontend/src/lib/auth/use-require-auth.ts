"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "./auth-context";

/** The auth guard every cinematic authenticated page (home, seed paper, and
 * beyond) needs, since none of them render inside the real AppShell (which
 * carries its own copy of this same check) -- one shared hook instead of
 * re-deriving the redirect-with-`next` logic per page. Returns whether the
 * page should render its real content yet. */
export function useRequireAuth(): { ready: boolean } {
  const { isAuthenticated, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      router.replace(`/sign-in?next=${encodeURIComponent(pathname)}`);
    }
  }, [isLoading, isAuthenticated, pathname, router]);

  return { ready: isLoading || isAuthenticated };
}
