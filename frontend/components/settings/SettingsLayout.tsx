import { useEffect, useState, type ReactNode } from "react";

import { SelectField } from "../ui";
import type { SettingsSectionId } from "./settings-types";
import styles from "./SettingsExperience.module.css";

export const SETTINGS_SECTIONS: ReadonlyArray<{ id: SettingsSectionId; label: string }> = [
  { id: "profile", label: "Profile" },
  { id: "preferences", label: "Study preferences" },
  { id: "appearance", label: "Appearance" },
  { id: "notifications", label: "Notifications" },
  { id: "account", label: "Account and plan" },
];

function isSectionId(value: string): value is SettingsSectionId {
  return SETTINGS_SECTIONS.some((section) => section.id === value);
}

export function SettingsLayout({ children }: { children: ReactNode }) {
  const [activeSection, setActiveSection] = useState<SettingsSectionId>("profile");

  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (isSectionId(hash)) {
      setActiveSection(hash);
    }
    const observers = SETTINGS_SECTIONS.map(({ id }) => {
      const node = document.getElementById(id);
      if (!node) return null;
      const observer = new IntersectionObserver(
        ([entry]) => {
          if (entry.isIntersecting) setActiveSection(id);
        },
        { rootMargin: "-20% 0px -65%", threshold: 0 },
      );
      observer.observe(node);
      return observer;
    });
    return () => observers.forEach((observer) => observer?.disconnect());
  }, []);

  function goToSection(id: SettingsSectionId) {
    setActiveSection(id);
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    window.history.replaceState(null, "", `#${id}`);
  }

  return (
    <div className={styles.layout}>
      <aside className={styles.sidebar} aria-label="Settings sections">
        <nav className={styles.nav}>
          {SETTINGS_SECTIONS.map((section) => (
            <a
              key={section.id}
              className={styles.navLink}
              href={`#${section.id}`}
              aria-current={activeSection === section.id ? "location" : undefined}
              onClick={() => setActiveSection(section.id)}
            >
              {section.label}
            </a>
          ))}
        </nav>
        <div className={styles.mobileNav}>
          <SelectField
            label="Settings section"
            value={activeSection}
            onChange={(event) => goToSection(event.target.value as SettingsSectionId)}
          >
            {SETTINGS_SECTIONS.map((section) => <option key={section.id} value={section.id}>{section.label}</option>)}
          </SelectField>
        </div>
      </aside>
      <div className={styles.content}>{children}</div>
    </div>
  );
}

export function SettingsSection({ id, title, description, children }: { id: SettingsSectionId; title: string; description: string; children: ReactNode }) {
  return (
    <section id={id} className={styles.section} aria-labelledby={`${id}-title`}>
      <header className={styles.sectionHeader}>
        <h2 id={`${id}-title`}>{title}</h2>
        <p>{description}</p>
      </header>
      {children}
    </section>
  );
}
