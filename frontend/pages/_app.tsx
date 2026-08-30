import type { AppProps } from "next/app";
import Head from "next/head";
import { useRouter } from "next/router";
import { useEffect } from "react";

import AuthGate from "../components/AuthGate";
import ApplicationShell from "../components/ApplicationShell";
import { AuthProvider, useAuth } from "../lib/auth";
import { getInternalRobotsContent, isPublicMetadataRoute } from "../lib/seo";
import { applyThemePreference, storeThemePreference } from "../lib/theme";
import "../styles/fonts.css";
import "../styles/tokens.css";
import "../styles/globals.css";

function ThemeController() {
  const { themePreference, resolvedTheme } = useAuth();

  useEffect(() => {
    applyThemePreference(themePreference, resolvedTheme);
    storeThemePreference(themePreference);
  }, [resolvedTheme, themePreference]);

  return null;
}

function AppChrome({ Component, pageProps }: Pick<AppProps, "Component" | "pageProps">) {
  return (
    <>
      <ThemeController />
      <AuthGate>
        <ApplicationShell>
          <Component {...pageProps} />
        </ApplicationShell>
      </AuthGate>
    </>
  );
}

export default function App({ Component, pageProps }: AppProps) {
  const router = useRouter();
  const publicMetadataRoute = isPublicMetadataRoute(router.pathname);

  return (
    <>
      <Head>
        <title>Adhyantra</title>
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        {!publicMetadataRoute ? <meta name="robots" content={getInternalRobotsContent()} /> : null}
      </Head>
      <AuthProvider>
        <AppChrome Component={Component} pageProps={pageProps} />
      </AuthProvider>
    </>
  );
}
