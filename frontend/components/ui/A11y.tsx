import type { HTMLAttributes,ReactNode } from "react";
export function VisuallyHidden({children}:{children:ReactNode}){return <span className="visually-hidden">{children}</span>}
export function LiveRegion({children,message,assertive=false,...props}:{children?:ReactNode;message?:ReactNode;assertive?:boolean}&HTMLAttributes<HTMLDivElement>){return <div className="live-region" role={assertive?"alert":"status"} aria-live={assertive?"assertive":"polite"} aria-atomic="true" {...props}>{children??message}</div>}
