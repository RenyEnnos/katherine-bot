## 2024-05-22 - Missing ARIA Labels on Textareas
**Learning:** Textareas used as main chat inputs often rely on placeholders which are not accessible labels. Explicit `aria-label` or visible `<label>` is required.
**Action:** Always check `ChatInput` components for proper labeling beyond just placeholders.
