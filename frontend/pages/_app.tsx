import type { AppProps } from "next/app";
import Head from "next/head";
import { useRouter } from "next/router";
import { useEffect } from "react";

import AuthGate from "../components/AuthGate";
import ApplicationShell from "../components/ApplicationShell";
import { AuthProvider, useAuth } from "../lib/auth";
import { getInternalRobotsContent, isPublicMetadataRoute } from "../lib/seo";
import { applyThemePreference, storeThemePreference } from "../lib/theme";
import "../styles/tokens.css";
import "../styles/globals.css";
import "../styles/legacy-theme-compat.css";

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
        <meta
          name="viewport"
          content="width=device-width, initial-scale=1"
        />
        {!publicMetadataRoute ? (
          <meta
            name="robots"
            content={getInternalRobotsContent()}
          />
        ) : null}
      </Head>
      <style jsx global>{`
        /* Disabled Phase 0 stylesheet retained temporarily for diff clarity.
           Active legacy compatibility lives in legacy-theme-compat.css. */
        @media not all {
        :root {
          color-scheme: light;
          --app-bg:
            radial-gradient(circle at top left, rgba(14, 165, 233, 0.16), transparent 28%),
            linear-gradient(180deg, #f8fafc 0%, #e2e8f0 100%);
          --app-text: #0f172a;
          --panel-bg: rgba(255, 255, 255, 0.92);
          --panel-border: rgba(148, 163, 184, 0.3);
          --surface-subtle: rgba(248, 250, 252, 0.92);
          --muted-text: #475569;
          --session-bg: rgba(248, 250, 252, 0.86);
          --session-border: rgba(148, 163, 184, 0.28);
          --session-link: #0f172a;
          --session-secondary-bg: #e2e8f0;
          --session-secondary-text: #0f172a;
          --session-primary-bg: #0f172a;
          --session-primary-text: #ffffff;
          --shell-chip-bg: rgba(226, 232, 240, 0.94);
          --shell-chip-text: #1e293b;
          --shell-badge-bg: #ccfbf1;
          --shell-badge-text: #0f766e;
          --shell-note-bg: rgba(14, 165, 233, 0.08);
          --shell-note-border: rgba(14, 165, 233, 0.2);
          --status-loading-bg: rgba(239, 246, 255, 0.94);
          --status-loading-border: #bfdbfe;
          --status-loading-text: #1d4ed8;
          --status-loading-icon-bg: rgba(191, 219, 254, 0.9);
          --status-info-bg: rgba(236, 254, 255, 0.94);
          --status-info-border: #a5f3fc;
          --status-info-text: #155e75;
          --status-info-icon-bg: rgba(165, 243, 252, 0.9);
          --status-success-bg: rgba(236, 253, 245, 0.94);
          --status-success-border: #a7f3d0;
          --status-success-text: #166534;
          --status-success-icon-bg: rgba(167, 243, 208, 0.9);
          --status-error-bg: rgba(254, 242, 242, 0.94);
          --status-error-border: #fecaca;
          --status-error-text: #991b1b;
          --status-error-icon-bg: rgba(254, 202, 202, 0.92);
          --status-empty-bg: rgba(248, 250, 252, 0.94);
          --status-empty-border: #cbd5e1;
          --status-empty-text: #475569;
          --status-empty-icon-bg: rgba(226, 232, 240, 0.94);
          --field-bg: rgba(255, 255, 255, 0.96);
          --field-border: #cbd5e1;
          --field-text: #0f172a;
          --field-placeholder: #64748b;
          --soft-card-bg: #f8fafc;
          --soft-card-border: #e2e8f0;
        }

        :root[data-theme="dark"] {
          color-scheme: dark;
          --app-bg:
            radial-gradient(circle at top left, rgba(56, 189, 248, 0.14), transparent 24%),
            linear-gradient(180deg, #020617 0%, #0f172a 100%);
          --app-text: #e2e8f0;
          --panel-bg: rgba(15, 23, 42, 0.9);
          --panel-border: rgba(71, 85, 105, 0.68);
          --surface-subtle: rgba(15, 23, 42, 0.84);
          --muted-text: #94a3b8;
          --session-bg: rgba(2, 6, 23, 0.88);
          --session-border: rgba(71, 85, 105, 0.68);
          --session-link: #f8fafc;
          --session-secondary-bg: #1e293b;
          --session-secondary-text: #e2e8f0;
          --session-primary-bg: #e2e8f0;
          --session-primary-text: #020617;
          --shell-chip-bg: rgba(30, 41, 59, 0.95);
          --shell-chip-text: #cbd5e1;
          --shell-badge-bg: rgba(15, 118, 110, 0.26);
          --shell-badge-text: #99f6e4;
          --shell-note-bg: rgba(30, 64, 175, 0.16);
          --shell-note-border: rgba(96, 165, 250, 0.22);
          --status-loading-bg: rgba(30, 64, 175, 0.14);
          --status-loading-border: rgba(96, 165, 250, 0.32);
          --status-loading-text: #bfdbfe;
          --status-loading-icon-bg: rgba(59, 130, 246, 0.2);
          --status-info-bg: rgba(8, 145, 178, 0.14);
          --status-info-border: rgba(103, 232, 249, 0.3);
          --status-info-text: #a5f3fc;
          --status-info-icon-bg: rgba(14, 165, 233, 0.2);
          --status-success-bg: rgba(22, 163, 74, 0.14);
          --status-success-border: rgba(74, 222, 128, 0.3);
          --status-success-text: #bbf7d0;
          --status-success-icon-bg: rgba(34, 197, 94, 0.18);
          --status-error-bg: rgba(127, 29, 29, 0.18);
          --status-error-border: rgba(248, 113, 113, 0.3);
          --status-error-text: #fecaca;
          --status-error-icon-bg: rgba(239, 68, 68, 0.18);
          --status-empty-bg: rgba(15, 23, 42, 0.84);
          --status-empty-border: rgba(100, 116, 139, 0.4);
          --status-empty-text: #cbd5e1;
          --status-empty-icon-bg: rgba(51, 65, 85, 0.85);
          --field-bg: rgba(15, 23, 42, 0.88);
          --field-border: rgba(100, 116, 139, 0.72);
          --field-text: #e2e8f0;
          --field-placeholder: #94a3b8;
          --soft-card-bg: rgba(15, 23, 42, 0.82);
          --soft-card-border: rgba(71, 85, 105, 0.68);
        }

        html {
          scroll-behavior: smooth;
        }

        * {
          box-sizing: border-box;
        }

        body {
          margin: 0;
          font-family: "Segoe UI", "Helvetica Neue", sans-serif;
          background: var(--app-bg);
          color: var(--app-text);
          min-height: 100vh;
          transition: background 180ms ease, color 180ms ease;
        }

        a {
          color: inherit;
        }

        button,
        input,
        textarea,
        select {
          font: inherit;
          transition:
            background 140ms ease,
            border-color 140ms ease,
            color 140ms ease,
            box-shadow 140ms ease,
            transform 140ms ease;
        }

        input,
        textarea,
        select {
          background: var(--field-bg);
          border-color: var(--field-border);
          color: var(--field-text);
        }

        input::placeholder,
        textarea::placeholder {
          color: var(--field-placeholder);
        }

        :root[data-theme="dark"] [style*="background: #ffffff"],
        :root[data-theme="dark"] [style*="background: #fff"],
        :root[data-theme="dark"] [style*="background: rgb(255, 255, 255)"] {
          background: var(--panel-bg) !important;
        }

        :root[data-theme="dark"] [style*="background: #f8fafc"],
        :root[data-theme="dark"] [style*="background: rgb(248, 250, 252)"] {
          background: var(--soft-card-bg) !important;
        }

        :root[data-theme="dark"] [style*="background: #fee2e2"],
        :root[data-theme="dark"] [style*="background: rgb(254, 226, 226)"] {
          background: var(--status-error-bg) !important;
        }

        :root[data-theme="dark"] [style*="background: #dcfce7"],
        :root[data-theme="dark"] [style*="background: rgb(220, 252, 231)"] {
          background: var(--status-success-bg) !important;
        }

        :root[data-theme="dark"] [style*="border: 1px solid #e2e8f0"],
        :root[data-theme="dark"] [style*="border: 1px solid rgb(226, 232, 240)"] {
          border-color: var(--soft-card-border) !important;
        }

        :root[data-theme="dark"] [style*="border: 1px solid #cbd5e1"],
        :root[data-theme="dark"] [style*="border: 1px solid rgb(203, 213, 225)"] {
          border-color: var(--field-border) !important;
        }

        :root[data-theme="dark"] [style*="color: #0f172a"],
        :root[data-theme="dark"] [style*="color: rgb(15, 23, 42)"] {
          color: var(--app-text) !important;
        }

        :root[data-theme="dark"] [style*="color: #475569"],
        :root[data-theme="dark"] [style*="color: rgb(71, 85, 105)"] {
          color: var(--muted-text) !important;
        }
        }
      `}</style>
      <AuthProvider>
        <AppChrome Component={Component} pageProps={pageProps} />
      </AuthProvider>
    </>
  );
}
