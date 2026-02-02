## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Message Action Accessibility]
**Learning:** When adding actions (like Copy) to message bubbles, placing them *below* the message content in a dedicated area avoids contrast issues and text obstruction that occur with absolute positioning inside the bubble.
**Action:** Use a flex-col wrapper for the message content and place action buttons (with clear aria-labels and status feedback) below the bubble.
