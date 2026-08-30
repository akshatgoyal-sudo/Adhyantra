import Link from "next/link";
import { useRouter } from "next/router";
import type { ReactNode } from "react";
import type { AdminAccessResponse } from "../../lib/api";
import styles from "./AdminExperience.module.css";

export function AdminShell({access,children}:{access:AdminAccessResponse;children:ReactNode}){
  const router=useRouter();
  const canContent=access.is_admin&&access.privileges.includes("content_read");
  const canOps=access.is_admin&&access.privileges.includes("content_qa");
  return <div className={styles.page}><div className={styles.shell}>
    <aside className={styles.side} aria-label="Administration context"><div><div className={styles.eyebrow}>Internal workspace</div><div className={styles.brand}>Administration</div><p>{access.role.replace(/_/g," ")}</p></div>
      <nav className={styles.nav} aria-label="Administration navigation">{canContent?<Link href="/admin/content" aria-current={router.pathname==="/admin/content"?"page":undefined}>Content</Link>:null}{canOps?<Link href="/admin/ops" aria-current={router.pathname==="/admin/ops"?"page":undefined}>Operations</Link>:null}<Link href="/">Study workspace</Link></nav>
    </aside><div className={styles.main}>{children}</div></div></div>;
}
