## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Mobile-First Hover Actions]
**Learning:** For auxiliary actions like "Copy" in chat bubbles, pure hover states (`opacity-0 group-hover:opacity-100`) fail on mobile touch devices. A robust pattern is `opacity-100 md:opacity-0 md:group-hover:opacity-100`. This ensures controls are always visible on touch devices (where hover doesn't exist) while maintaining a clean, clutter-free UI on desktop.
**Action:** When hiding secondary actions behind hover, always include a media query override to make them visible by default on mobile.
