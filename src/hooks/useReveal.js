import { useEffect, useRef, useState } from "react";

/** Observe a single element and add is-visible when it enters the viewport. */
export function useReveal(initiallyVisible = false) {
  const ref = useRef(null);
  const [visible, setVisible] = useState(initiallyVisible);

  useEffect(() => {
    if (initiallyVisible) return undefined;
    const el = ref.current;
    if (!el) return undefined;

    if (!("IntersectionObserver" in window)) {
      setVisible(true);
      return undefined;
    }

    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setVisible(true);
            io.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12, rootMargin: "0px 0px -8% 0px" }
    );

    io.observe(el);
    return () => io.disconnect();
  }, [initiallyVisible]);

  return { ref, visible };
}
