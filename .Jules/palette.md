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

## 2024-05-29 - [Dynamic Disabled State Communication]
**Learning:** Simply disabling a button (like 'Send') can leave users confused as to *why* it is disabled. Updating the `aria-label` and `title` to explain the reason (e.g., "Digite uma mensagem para enviar" vs "Enviando mensagem...") provides critical context to both screen reader users and sighted users (via tooltips), reducing frustration.
**Action:** When a main action button is conditionally disabled, provide a dynamic aria-label/title that explains the condition required to enable it, rather than a static label.
