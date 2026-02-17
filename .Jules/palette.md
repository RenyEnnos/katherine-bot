## 2024-05-23 - [Critical Learnings Log]
(This file was found empty or with single entry during inspection, ensuring history is preserved)

## 2024-05-22 - [Avatar Accessibility]
**Learning:** Purely visual components like Avatars often get overlooked for accessibility. While "decorative", they provide context (who is speaking). Adding `role="img"` and `aria-label` to the container and hiding the internal icon (`aria-hidden="true"`) is a robust pattern to ensure screen readers announce "User" or "Bot" instead of ignoring it or reading the icon filename/SVG title.
**Action:** Always check "decorative" icons that convey meaning (like speaker identity) and add appropriate ARIA labels.

## 2024-05-24 - [Auxiliary Message Actions]
**Learning:** Placing auxiliary actions (like copy) inside the message bubble can clutter the text. Placing them outside in a vertical flex container (`flex-col`) handles variable content widths gracefully and prevents overlap, while `group-hover` + `focus:opacity-100` keeps the UI clean but accessible.
**Action:** Use vertical stacking for auxiliary actions attached to variable-width content blocks.

## 2024-05-25 - [Responsive Visibility Overlap]
**Learning:** Using only `opacity` for responsive visibility (e.g., `md:opacity-0`) can lead to duplicate interactive elements if hover states (`group-hover:opacity-100`) override the opacity on larger screens. Elements intended to be hidden on desktop may reappear on hover alongside their desktop counterparts.
**Action:** Pair `hidden` / `block` utilities with opacity transitions when elements should be completely removed from the layout/accessibility tree on specific breakpoints, or ensure hover states are scoped to the correct breakpoint (e.g., `md:group-hover:opacity-100` vs `group-hover:opacity-100`).

## 2024-05-26 - [Focus Management in Conditional UI]
**Learning:** When conditional rendering swaps interactive elements (like a delete button becoming a confirmation dialog), focus management is crucial. Without `autoFocus` on the new element and a strategy to restore focus to the trigger (or its replacement) upon cancellation, keyboard users get lost.
**Action:** Pair conditional UI swaps with `autoFocus` on the entering element and a state/ref mechanism to restore focus to the returning trigger.
