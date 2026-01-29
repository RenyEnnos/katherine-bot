## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-23 - [Accessible Hover Actions]
**Learning:** When hiding actions until hover (e.g., "Copy" button in chat), purely using `opacity-0 group-hover:opacity-100` makes them inaccessible to keyboard users. Pairing `group-hover:opacity-100` with `focus:opacity-100` ensures that when a user tabs to the button, it becomes visible, satisfying both aesthetic minimalism and accessibility requirements.
**Action:** Always pair `hover` visibility classes with `focus` or `focus-within` equivalents for interactive elements.
