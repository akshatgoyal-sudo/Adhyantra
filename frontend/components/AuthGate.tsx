import { useRouter } from "next/router";
import { useEffect, type ReactNode } from "react";

import { useAuth } from "../lib/auth";
import ProductStatusCard from "./ProductStatusCard";

const PUBLIC_ROUTES = new Set(["/auth", "/pricing", "/exams/[exam]", "/404"]);

function loadingScreen(title: string, message: string) {
  return (
    <div
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "2rem",
      }}
    >
      <div style={{ width: "min(480px, 100%)" }}>
        <ProductStatusCard tone="loading" eyebrow="Adhyantra" title={title} message={message} />
      </div>
    </div>
  );
}

export default function AuthGate({ children }: { children: ReactNode }) {
  const router = useRouter();
  const { status } = useAuth();
  const isPublicRoute = PUBLIC_ROUTES.has(router.pathname);

  useEffect(() => {
    if (!router.isReady) {
      return;
    }

    if (status === "unauthenticated" && !isPublicRoute) {
      const nextPath = router.asPath && router.asPath !== "/auth" ? router.asPath : "/";
      void router.replace(`/auth?next=${encodeURIComponent(nextPath)}`);
      return;
    }

    if (status === "authenticated" && router.pathname === "/auth") {
      const nextTarget = typeof router.query.next === "string" && router.query.next.trim() ? router.query.next : "/";
      void router.replace(nextTarget);
    }
  }, [isPublicRoute, router, status]);

  if (status === "loading" && !isPublicRoute) {
    return loadingScreen("Checking your secure session", "Adhyantra is opening your study workspace and loading your saved preferences.");
  }

  if (status === "unauthenticated" && !isPublicRoute) {
    return loadingScreen("Protected workspace", "No active session was found for this product area. Redirecting you to email sign-in.");
  }

  if (status === "authenticated" && router.pathname === "/auth") {
    return loadingScreen("Session ready", "Your Adhyantra session is active. Opening your study workspace.");
  }

  return <>{children}</>;
}
