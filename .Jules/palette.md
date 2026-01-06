## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Micro-Interaction Visibility]
**Learning:** Actions that appear on hover (like "Copy Message") are great for reducing clutter on desktop but are inaccessible on touch devices. A robust pattern is `opacity-100 md:opacity-0 group-hover:opacity-100 focus-within:opacity-100`. This ensures the action is always visible on mobile, appears on hover on desktop, and becomes visible when a keyboard user focuses it.
**Action:** Use conditional opacity with `md:` and `focus-within:` variants for all hover-revealed actions.
