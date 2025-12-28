# Palette's Journal

## 2024-05-23 - Accessibility in Visualization Components
**Learning:** Visual status indicators (like emotion panels) often get missed by screen readers if they only use visual cues (colors/bars).
**Action:** Always ensure visualization components use `role="progressbar"` or appropriate ARIA roles, and include `aria-label` or `aria-valuetext` to describe the current state to non-sighted users.

## 2024-05-23 - Icon-Only Buttons
**Learning:** Icon-only buttons are a common accessibility trap. They need explicit `aria-label`s.
**Action:** Audit all icon buttons and ensure they have descriptive labels.
