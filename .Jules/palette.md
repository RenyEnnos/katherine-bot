## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Accessible Hover Actions]
**Learning:** Actions revealed on hover (like "Copy") are problematic for touch and keyboard users. Using `group-hover:opacity-100` must be paired with `focus:opacity-100` (for keyboard) and defaulting to visible on touch devices (`opacity-100 md:opacity-0`).
**Action:** Always verify "hover-only" UI with keyboard navigation and consider mobile default visibility.
