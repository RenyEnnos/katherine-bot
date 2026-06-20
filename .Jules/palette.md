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
**Learning:** For simple UI toggles (e.g., replacing a button with a confirmation dialog), conditionally rendering elements with `autoFocus` is a robust and minimal pattern for managing focus. It avoids complex `useEffect` + `useRef` logic while ensuring keyboard users are not lost when the DOM structure changes.
**Action:** Use conditional rendering + `autoFocus` for inline confirmation states to preserve keyboard context.

## 2024-05-27 - [Focus Restoration Precision]
**Learning:** While `autoFocus` handles initial focus well, using it for *restoration* (e.g. going back to a trigger button) can cause "sticky" focus on re-renders if state isn't managed perfectly. A `useRef` + `useEffect` pattern offers more precise control for restoring focus without side effects.
**Action:** Prefer `useRef` and `useEffect` over state-controlled `autoFocus` when precise focus restoration is needed after closing a modal/dialog.

## 2024-05-28 - [Inline Confirmation Semantics]
**Learning:** When replacing a trigger button with inline confirmation controls, simply swapping elements can confuse screen readers. Wrapping the confirmation controls in a container with `role="group"` and `aria-label` provides necessary context that a modal would otherwise provide, without the overhead of a full dialog trap.
**Action:** Wrap inline confirmation actions in a semantic group with a clear label to maintain context for assistive technology.

## 2025-02-12 - [Explicit Focus & Disabled States]
**Learning:** Dynamic Tailwind class ternaries can sometimes inadvertently miss essential utility classes, especially focus rings. Also, inputs visually behave as enabled during loading states without explicit `disabled:` styles, causing confusion. In dark themes, focus rings require explicit offsets (e.g. `focus-visible:ring-offset-gray-800`).
**Action:** Always verify `disabled:opacity-50 disabled:cursor-not-allowed` on input elements, and ensure buttons maintain strong, offset `focus-visible` styling regardless of state logic.

## 2025-02-13 - [Transient State Announcements]
**Learning:** For transient accessibility state confirmations (like 'Copied!'), changing a button's `aria-label` dynamically isn't always announced by screen readers, and replacing the text might disrupt sighted users relying on tooltips.
**Action:** Use a permanently mounted sibling `span` with `aria-live="polite"` and `className="sr-only"` to announce transient states. Keep the button's `aria-label` static (e.g., "Copiar mensagem") and use `title` for visual tooltips. Ensure elements hidden by `opacity-0` have robust `focus-visible:` styles so keyboard navigation works and the element appears on focus.
