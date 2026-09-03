import { Head, Html, Main, NextScript } from "next/document";

import { THEME_BOOTSTRAP_SCRIPT } from "../lib/theme";

export default function Document() {
  return (
    <Html lang="en" suppressHydrationWarning>
      <Head>
        <meta name="color-scheme" content="light dark" />
        <link rel="icon" href="/icon.svg" type="image/svg+xml" />
        <link rel="preload" href="/fonts/instrument-sans-latin-variable.woff2" as="font" type="font/woff2" crossOrigin="anonymous" />
        <script dangerouslySetInnerHTML={{ __html: THEME_BOOTSTRAP_SCRIPT }} />
      </Head>
      <body>
        <Main />
        <NextScript />
      </body>
    </Html>
  );
}
