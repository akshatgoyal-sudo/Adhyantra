import type { SubjectItemResponse } from "../lib/api";

type SubjectSelectorProps = {
  id: string;
  label?: string;
  value: string;
  subjects: SubjectItemResponse[];
  onChange: (nextSubject: string) => void;
  dark?: boolean;
  minWidth?: string;
};

export default function SubjectSelector({
  id,
  label = "Subject",
  value,
  subjects,
  onChange,
  dark = false,
  minWidth = "220px",
}: SubjectSelectorProps) {
  return (
    <div style={{ minWidth }}>
      <label htmlFor={id} style={{ display: "block", marginBottom: "0.35rem", fontWeight: 700, color: dark ? "#ffffff" : "#0f172a" }}>
        {label}
      </label>
      <select
        id={id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        style={{
          width: "100%",
          padding: "0.85rem",
          borderRadius: "12px",
          border: dark ? "1px solid rgba(255,255,255,0.35)" : "1px solid #cbd5e1",
          background: dark ? "rgba(255,255,255,0.12)" : "#ffffff",
          color: dark ? "#ffffff" : "#0f172a",
          fontSize: "1rem",
        }}
      >
        {subjects.map((item) => (
          <option key={item.code} value={item.code} disabled={!item.available} style={{ color: "#0f172a" }}>
            {item.label}
            {item.available ? "" : " (coming soon)"}
          </option>
        ))}
      </select>
    </div>
  );
}
