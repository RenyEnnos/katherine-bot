## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2026-01-21 - [Assistant Message Actions]
**Learning:** For AI assistant interfaces, users frequently need to copy the output. Providing a dedicated "Copy" action that is visually unobtrusive (e.g., lower opacity until hover/focus) balances cleanliness with utility. Grouping these actions near the message bubble (e.g., below it) works well.
**Action:** When designing chat interfaces, always include copy functionality for assistant messages, ensuring it is keyboard accessible even if hidden by default.
