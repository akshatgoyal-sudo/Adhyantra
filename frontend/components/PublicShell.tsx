import Link from "next/link";
import { useRouter } from "next/router";
import type { ReactNode } from "react";

import { BrandLockup } from "./brand/BrandLockup";
import styles from "./PublicShell.module.css";

const PUBLIC_LINKS = [
  { href: "/about", label: "About" },
  { href: "/pricing", label: "Plans" },
  { href: "/contact", label: "Contact" },
];

const AUTH_LINKS = [
  { href: "/privacy", label: "Privacy" },
  { href: "/terms", label: "Terms" },
  { href: "/contact", label: "Contact" },
];

export default function PublicShell({ children, compactFooter = false }: { children: ReactNode; compactFooter?: boolean }) {
  const router = useRouter();
  const isAuthEntry = router.pathname === "/auth";
  const headerLinks = isAuthEntry ? AUTH_LINKS : PUBLIC_LINKS;

  return (
    <>
      <header className={styles.header}>
        <div className={styles.bar}>
          <Link className={styles.brand} href="/auth" aria-label="Adhyantra home">
            <BrandLockup />
          </Link>
          <nav className={styles.nav} aria-label="Public navigation">
            {headerLinks.map((item) => (
              <Link
                key={item.href}
                className={styles.link}
                href={item.href}
                aria-current={router.pathname === item.href ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
            {!isAuthEntry ? <Link className={styles.signIn} href="/auth#sign-in">Sign in</Link> : null}
          </nav>
        </div>
      </header>
      {children}
      <footer className={`${styles.footer} ${compactFooter ? styles.footerCompact : ""}`}>
        <div className={styles.footerInner}>
          <div>
            <Link className={styles.footerBrand} href="/auth"><BrandLockup compact /></Link>
            <p>Focused preparation for UPSC, SSC and Banking learners.</p>
          </div>
          <nav className={styles.footerLinks} aria-label="Public information">
            {!isAuthEntry ? <><Link href="/exams/upsc">UPSC</Link><Link href="/exams/ssc">SSC</Link><Link href="/exams/banking">Banking</Link><Link href="/about">About</Link></> : null}
            <Link href="/contact">Contact</Link>
            <Link href="/privacy">Privacy</Link>
            <Link href="/terms">Terms</Link>
            <Link href="/refund-policy">Refund policy</Link>
          </nav>
        </div>
      </footer>
    </>
  );
}
