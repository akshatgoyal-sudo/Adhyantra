import type { SVGProps } from "react";

type BrandMarkProps = SVGProps<SVGSVGElement> & {
  decorative?: boolean;
  title?: string;
};

export function BrandMark({ decorative = true, title = "Adhyantra study thread", ...props }: BrandMarkProps) {
  const titleId = decorative ? undefined : "adhyantra-brand-mark-title";
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      role={decorative ? undefined : "img"}
      aria-hidden={decorative ? "true" : undefined}
      aria-labelledby={titleId}
      focusable="false"
      {...props}
    >
      {titleId ? <title id={titleId}>{title}</title> : null}
      <path d="M6.5 22.5c2.4-8 6.6-13 12.6-15.1 3.6-1.2 6.4.5 6.4 3.2 0 3.1-3.5 5.1-8.2 5.1H11" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <path d="M10.5 15.7c.2 5.8 3.1 9.1 7.7 9.1 3.6 0 6-1.9 7.3-4.4" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="6.4" cy="22.7" r="2.6" fill="currentColor" />
      <circle cx="10.6" cy="15.7" r="2.1" fill="currentColor" />
      <circle cx="25.4" cy="20.4" r="2.6" fill="currentColor" />
    </svg>
  );
}
