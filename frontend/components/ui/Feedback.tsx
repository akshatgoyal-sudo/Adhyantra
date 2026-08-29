import type { CSSProperties,ReactNode } from "react"; import styles from "./ui.module.css";
export function Skeleton({width="100%",height=16}:{width?:CSSProperties["width"];height?:CSSProperties["height"]}){return <span className={styles.skeleton} style={{width,height}} aria-hidden="true"/>}
function State({title,message,action,kind}:{title:string;message:string;action?:ReactNode;kind:"empty"|"error"}){return <section className={styles.state} role={kind==="error"?"alert":"status"}><h2>{title}</h2><p>{message}</p>{action}</section>}
export function EmptyState(props:{title:string;message:string;action?:ReactNode}){return <State {...props} kind="empty"/>} export function ErrorState(props:{title:string;message:string;action?:ReactNode}){return <State {...props} kind="error"/>}
