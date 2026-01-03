## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Mobile Interaction States]
**Learning:** Relying solely on `group-hover:opacity-100` for revealing secondary actions (like a copy button) creates a poor experience on mobile devices, where hover states are inconsistent or non-existent.
**Action:** For secondary actions that are hidden by default on desktop, use responsive classes like `opacity-100 md:opacity-0` to ensure they are persistently visible on touch devices while remaining unobtrusive on larger screens.
