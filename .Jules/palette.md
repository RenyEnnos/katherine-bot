## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Clipboard Action Feedback]
**Learning:** Actions like "Copy to Clipboard" are invisible without explicit feedback. Users might click multiple times if they don't see a change. Swapping the icon (Copy -> Check) provides immediate, understandable confirmation without needing a complex toast notification system for simple actions.
**Action:** For micro-actions, prefer inline state changes (icon swap) over global notifications when possible to reduce cognitive load.
