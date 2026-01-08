## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Micro-Interaction Visibility]
**Learning:** Adding auxiliary actions (like a "Copy" button) to message bubbles requires careful balancing of visibility and clutter. Initially, hiding them completely (`opacity-0`) keeps the UI clean, but can make the feature undiscoverable on mobile.
**Action:** Use `group-hover:opacity-100` for desktop mouse users, but ensure `focus-visible` or `focus-within` styles reveal the button for keyboard users. For mobile, consider keeping it always visible or ensuring the tap target is large enough. In this implementation, we used `opacity-100` for touch devices (implied by default) and `md:opacity-0` + `md:group-hover:opacity-100` for desktop.
