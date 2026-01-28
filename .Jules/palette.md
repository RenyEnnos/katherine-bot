## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Mobile-First Action Visibility]
**Learning:** Auxiliary actions (like copy buttons) that rely on hover for visibility are inaccessible on touch devices. A robust pattern is `opacity-100 md:opacity-0 md:group-hover:opacity-100`, which makes actions always visible on mobile but keeps the desktop UI clean until interaction.
**Action:** Use this utility class combination for any secondary actions inside lists or cards.
