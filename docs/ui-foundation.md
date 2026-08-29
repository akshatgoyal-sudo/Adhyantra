# Adhyantra UI foundation

Phase 1 establishes the “focused civic intelligence” foundation without redesigning feature pages.

## Theme contract

The root element always has a resolved `data-theme="light"` or `data-theme="dark"`, plus the saved `data-theme-preference`. The preference remains `light`, `dark`, or `system` in `adhyantra.themePreference` and in authenticated settings. A static, account-free script in `_document.tsx` resolves the theme before paint; it is deliberately stable for a future CSP hash or nonce.

All new UI uses semantic custom properties from `styles/tokens.css`. `legacy-theme-compat.css` is a temporary bridge for old inline colors. Phases 2–5 should remove matching inline colors as each page is redesigned; Phase 6 should delete the bridge and the disabled Phase 0 stylesheet retained in `_app.tsx`.

## Shared components

`components/ui` contains native, typed primitives: buttons, cards, badges, status feedback, fields, page headers, loading/empty/error feedback, visually hidden content, and live regions. They use no runtime styling library and inherit focus, disabled, motion, and theme behavior globally.

The authenticated shell provides a non-wrapping desktop header and a mobile top bar plus safe-area-aware Home, Tutor, Test, Progress, and More navigation. Public information pages use the public header/footer shell. Feature-page redesigns remain out of scope for this phase.
