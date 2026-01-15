## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Visual Feedback for Invisible Actions]
**Learning:** Actions like "Copy to Clipboard" are invisible. Users need immediate visual confirmation (like a checkmark) to trust the action succeeded, especially when the system response (clipboard update) isn't visible in the UI.
**Action:** Always pair invisible actions (copy, save, sync) with a temporary visual state change (icon swap, toast).
