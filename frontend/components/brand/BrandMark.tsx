import { useId, type SVGProps } from "react";

type BrandMarkProps = SVGProps<SVGSVGElement> & {
  decorative?: boolean;
  title?: string;
};

export function BrandMark({ decorative = true, title = "Adhyantra", ...props }: BrandMarkProps) {
  const generatedId = useId();
  const titleId = decorative ? undefined : `adhyantra-brand-mark-${generatedId.replace(/:/g, "")}`;
  return (
    <svg
      viewBox="0 0 40 36"
      fill="currentColor"
      role={decorative ? undefined : "img"}
      aria-hidden={decorative ? "true" : undefined}
      aria-labelledby={titleId}
      focusable="false"
      {...props}
    >
      {titleId ? <title id={titleId}>{title}</title> : null}
      <path d="M1.8 34 16.6 2h4.1L9.8 34h-8Z" />
      <path d="M22.5 2.1 38.2 34h-8.1L18.8 8.4l3.7-6.3Z" />
      <path d="M5.2 25.8c4.8-5.4 8.9-1.8 13.8-4.8 3.2-2 5.7-5.2 8-8.5-2.2 5.4-5.3 10-9.5 12.1-4.5 2.3-7.8-.4-10.5 5.2l-1.8-4Z" />
    </svg>
  );
}
