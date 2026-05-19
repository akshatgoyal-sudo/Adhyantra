import Link from "next/link";

type TopicCardProps = {
  href: string;
  title: string;
  description: string;
};

export default function TopicCard({ href, title, description }: TopicCardProps) {
  return (
    <Link
      href={href}
      style={{
        display: "block",
        padding: "1.25rem",
        borderRadius: "18px",
        border: "1px solid rgba(15, 23, 42, 0.12)",
        background: "linear-gradient(180deg, #ffffff 0%, #f8fafc 100%)",
        color: "#0f172a",
        textDecoration: "none",
        boxShadow: "0 16px 40px rgba(15, 23, 42, 0.08)",
      }}
    >
      <div style={{ fontSize: "1.1rem", fontWeight: 700, marginBottom: "0.5rem" }}>{title}</div>
      <div style={{ color: "#475569", lineHeight: 1.6 }}>{description}</div>
    </Link>
  );
}
