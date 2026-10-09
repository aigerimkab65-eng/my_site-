import { useEffect, useRef } from "react";

const FOCUSABLE =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Focus first control on open, restore focus on close, trap Tab inside the dialog.
 */
export function useModalA11y(open, containerRef, initialFocusRef) {
  const previousFocusRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    previousFocusRef.current = document.activeElement;

    const id = window.requestAnimationFrame(() => {
      const target = initialFocusRef?.current || containerRef?.current;
      target?.focus?.();
    });

    function onKey(event) {
      if (event.key !== "Tab") return;
      const root = containerRef?.current;
      if (!root) return;
      const nodes = Array.from(root.querySelectorAll(FOCUSABLE)).filter(
        (el) => !el.hasAttribute("disabled") && el.offsetParent !== null
      );
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKey);
    return () => {
      window.cancelAnimationFrame(id);
      document.removeEventListener("keydown", onKey);
      const prev = previousFocusRef.current;
      if (prev && typeof prev.focus === "function") {
        try {
          prev.focus();
        } catch (_) {}
      }
    };
  }, [open, containerRef, initialFocusRef]);
}
