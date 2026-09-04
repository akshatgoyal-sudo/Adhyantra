import { useId, type SVGProps } from "react";

import styles from "./BrandWordmark.module.css";

type Props = SVGProps<SVGSVGElement> & {
  compact?: boolean;
  decorative?: boolean;
};

// Hand-constructed from the approved integrated artwork. Letter contours are
// independent of installed fonts; the opening sweep joins the left shoulder of d.
export function BrandWordmark({ compact = false, decorative = true, className = "", ...props }: Props) {
  const instanceId = useId().replace(/:/g, "");
  const gradientId = `adhyantra-wordmark-${instanceId}`;
  const titleId = `${gradientId}-title`;

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 1300 250"
      width="172"
      height="33.08"
      className={`${styles.wordmark} ${compact ? styles.compact : ""} ${className}`}
      role={decorative ? undefined : "img"}
      aria-hidden={decorative ? true : undefined}
      aria-labelledby={decorative ? undefined : titleId}
      focusable="false"
      fill={`url(#${gradientId})`}
      {...props}
    >
      {!decorative ? <title id={titleId}>Adhyantra</title> : null}
      <defs>
        <linearGradient id={gradientId} x1="0" y1="190" x2="1300" y2="20" gradientUnits="userSpaceOnUse">
          <stop className={styles.inkStop} />
          <stop className={styles.tealStop} offset="1" />
        </linearGradient>
      </defs>
      <path d="M29 136 84 13h31l44 96c-9 5-19 8-29 10L98 50l-28 69c-16 3-29 9-41 17Z" />
      <path d="m151 158 27-14 22 44h-35Z" />
      <path d="M1 197 22 156c20-29 44-34 73-29 36 7 65-1 87-24 14-15 36-29 66-37l-31 21c-15 13-21 26-28 40-15 27-44 32-74 26-32-6-53-4-66 22l-11 22Z" />
      <path fillRule="evenodd" d="M321 0h30v188h-30v-17c-12 13-29 19-47 19-38 0-66-28-66-66 0-37 28-66 67-66 18 0 34 6 46 17V0Zm-42 82c-24 0-42 18-42 42s18 42 42 42c25 0 44-18 44-42s-19-42-44-42Z" />
      <path d="M376 0h30v75c13-12 29-18 48-18 34 0 54 22 54 57v35c0 15 9 22 25 20l11 24c-42 10-66-9-66-43v-34c0-22-12-34-33-34-23 0-39 16-39 40v66h-30Z" />
      <path d="M512 59h33l46 97 41-97h33l-65 151c-12 29-26 41-62 38v-26c17 1 27-5 33-20l3-8Z" />
      <path fillRule="evenodd" d="M774 59h30v129h-30v-17c-12 13-29 19-47 19-39 0-67-28-67-66 0-37 28-67 67-67 18 0 35 7 47 19V59Zm-43 23c-25 0-43 18-43 42s18 42 43 42c24 0 43-18 43-42s-19-42-43-42Z" />
      <path d="M823 188v-73c0-37 26-59 69-59s70 22 70 59v73h-30v-71c0-23-14-35-40-35-25 0-39 12-39 35v71Z" />
      <path d="M988 23h29v36h39v24h-39v58c0 24 12 29 41 22v25c-48 11-70-7-70-46V83h-21V59h21Z" />
      <path d="M1074 59h29v17c12-14 27-20 47-19v29c-31-2-47 13-47 44v58h-29Z" />
      <path fillRule="evenodd" d="M1268 59h30v129h-30v-17c-12 13-29 19-47 19-39 0-67-28-67-66 0-37 28-67 67-67 18 0 35 7 47 19V59Zm-43 23c-25 0-43 18-43 42s18 42 43 42c24 0 43-18 43-42s-19-42-43-42Z" />
    </svg>
  );
}
