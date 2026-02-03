## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2026-02-03 - [Chat Actions Accessibility]
**Learning:** When adding auxiliary actions (like "Copy") to message bubbles, grouping them in a vertical flex container below the bubble ensures they are associated with the message without breaking the visual flow or overlapping content on small screens.
**Action:** Use `flex-col` for message/action grouping and ensure actions are keyboard accessible with `aria-label`.
