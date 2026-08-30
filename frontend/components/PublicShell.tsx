import Link from "next/link";
import { useRouter } from "next/router";
import type { ReactNode } from "react";

import styles from "./PublicShell.module.css";

const PUBLIC_LINKS = [
  { href: "/about", label: "About" },
  { href: "/pricing", label: "Plans" },
  { href: "/contact", label: "Contact" },
];

export default function PublicShell({ children }: { children: ReactNode }) {
  const router = useRouter();

  return (
    <>
      <header className={styles.header}>
        <div className={styles.bar}>
          <Link className={styles.brand} href="/auth" aria-label="Adhyantra home">
            <span className={styles.brandMark} aria-hidden="true">A</span>
            <span>Adhyantra</span>
          </Link>
          <nav className={styles.nav} aria-label="Public navigation">
            {PUBLIC_LINKS.map((item) => (
              <Link
                key={item.href}
                className={styles.link}
                href={item.href}
                aria-current={router.pathname === item.href ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
            <Link className={styles.signIn} href="/auth#sign-in">Sign in</Link>
          </nav>
        </div>
      </header>
      {children}
      <footer className={styles.footer}>
        <div className={styles.footerInner}>
          <div>
            <Link className={styles.footerBrand} href="/auth">Adhyantra</Link>
            <p>Focused preparation for UPSC, SSC and Banking learners.</p>
          </div>
          <nav className={styles.footerLinks} aria-label="Public information">
            <Link href="/exams/upsc">UPSC</Link>
            <Link href="/exams/ssc">SSC</Link>
            <Link href="/exams/banking">Banking</Link>
            <Link href="/about">About</Link>
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
