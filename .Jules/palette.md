## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2025-01-09 - [Optimistic UI with Async Operations]
**Learning:** For actions like copying to clipboard, providing immediate visual feedback is crucial. However, failing to handle the Promise returned by async operations like `navigator.clipboard.writeText` can lead to misleading success states if the operation fails.
**Action:** Always chain `.then()` and `.catch()` for async UI interactions, even for simple browser APIs, to ensure the visual state reflects the true outcome.
