import type { HTMLAttributes } from "react"; import styles from "./ui.module.css";
export function Badge({tone="primary",className="",...props}:HTMLAttributes<HTMLSpanElement>&{tone?:"primary"|"accent"|"neutral"}){const c=tone==="accent"?styles.badgeAccent:tone==="neutral"?styles.badgeNeutral:"";return <span className={`${styles.badge} ${c} ${className}`} {...props}/>}
