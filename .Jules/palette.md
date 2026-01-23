## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Auxiliary Actions Visibility]
**Learning:** For auxiliary actions (like 'Copy') that shouldn't clutter the UI, using `opacity-0` on desktop with `group-hover:opacity-100` is clean, but MUST be paired with `focus:opacity-100` for keyboard users and `opacity-100` by default on touch devices (where hover doesn't exist).
**Action:** Use `opacity-100 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100` for secondary action buttons.
