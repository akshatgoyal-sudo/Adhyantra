import Link from "next/link";
import { useEffect,useRef } from "react";
import { Card,LiveRegion } from "../ui";
import styles from "./AdminExperience.module.css";

export function AccessDenied({area="this area"}:{area?:string}){const heading=useRef<HTMLHeadingElement>(null);useEffect(()=>heading.current?.focus(),[]);return <main className={`${styles.page} ${styles.denied}`}><Card className={styles.deniedInner}><div className={styles.eyebrow}>Access denied · 403</div><h1 ref={heading} tabIndex={-1}>You don’t have access to this area.</h1><p className={styles.muted}>The current account does not have permission to open {area}. No administrative data was requested or displayed.</p><div className={styles.actions}><Link className="ui-link-button" href="/">Return to study workspace</Link><Link className="ui-link-button ui-link-button--secondary" href="/settings#account">Open account settings</Link></div><LiveRegion message="Access denied. This account does not have the required administrative permission." /></Card></main>}
