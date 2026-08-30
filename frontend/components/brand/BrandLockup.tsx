import type { ComponentPropsWithoutRef } from "react";

import { BrandMark } from "./BrandMark";
import styles from "./BrandLockup.module.css";

type Props = ComponentPropsWithoutRef<"span"> & { compact?: boolean };

export function BrandLockup({ compact = false, className = "", ...props }: Props) {
  return (
    <span className={`${styles.lockup} ${compact ? styles.compact : ""} ${className}`} {...props}>
      <span className={styles.mark} aria-hidden="true"><BrandMark /></span>
      <span className={styles.wordmark}>Adhyantra</span>
    </span>
  );
}
