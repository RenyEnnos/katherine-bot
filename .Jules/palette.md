## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Mobile-First Hover Actions]
**Learning:** Action buttons (like Copy) inside items need to be accessible on touch devices where "hover" doesn't exist. Hiding them completely (\`opacity-0\`) makes them inaccessible.
**Action:** Use \`opacity-100 md:opacity-0 md:group-hover:opacity-100 focus:opacity-100\` pattern. This keeps actions visible by default on mobile/touch, but cleaner (hover-only) on desktop, while ensuring keyboard focus makes them visible.
