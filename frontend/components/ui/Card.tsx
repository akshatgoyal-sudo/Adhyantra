import type { HTMLAttributes } from "react"; import styles from "./ui.module.css";
export function Card({className="",...props}:HTMLAttributes<HTMLDivElement>){return <div className={`${styles.card} ${className}`} {...props}/>}
