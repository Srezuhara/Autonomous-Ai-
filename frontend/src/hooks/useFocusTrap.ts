import { useEffect, useRef } from 'react';

/**
 * useFocusTrap — keyboard containment for overlays.
 *
 * Shared by the rebuild modal and the mobile navigation drawer, neither of
 * which had any of this: opening either one left focus behind on the page
 * underneath, Tab walked straight out into content the user could not see, and
 * Escape did nothing.
 *
 * While `active`:
 *   - focus moves to the first focusable element inside the container
 *   - Tab and Shift+Tab cycle within it
 *   - Escape calls `onClose`
 * On deactivation, focus returns to whatever had it before.
 *
 * `onClose` is held in a ref so a caller passing an inline arrow does not tear
 * down and rebuild the listener on every render.
 */
const FOCUSABLE = [
  'a[href]', 'button:not([disabled])', 'textarea:not([disabled])',
  'input:not([disabled])', 'select:not([disabled])', '[tabindex]:not([tabindex="-1"])',
].join(',');

export function useFocusTrap<T extends HTMLElement>(active: boolean, onClose: () => void) {
  const containerRef = useRef<T>(null);
  const onCloseRef   = useRef(onClose);

  // Written in an effect rather than during render: a ref mutation in the
  // render body is not safe under concurrent rendering, and the keydown
  // listener below only ever reads it after commit.
  useEffect(() => { onCloseRef.current = onClose; }, [onClose]);

  useEffect(() => {
    if (!active) return;

    const container = containerRef.current;
    if (!container) return;

    const previouslyFocused = document.activeElement as HTMLElement | null;

    const focusables = () =>
      Array.from(container.querySelectorAll<HTMLElement>(FOCUSABLE))
        .filter(el => el.offsetParent !== null || el === document.activeElement);

    // Focus the first control rather than the container itself, so a screen
    // reader lands on something actionable.
    const first = focusables()[0];
    (first ?? container).focus({ preventScroll: true });

    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        e.stopPropagation();
        onCloseRef.current();
        return;
      }
      if (e.key !== 'Tab') return;

      const items = focusables();
      if (items.length === 0) {
        e.preventDefault();
        return;
      }

      const firstItem = items[0];
      const lastItem  = items[items.length - 1];
      const current   = document.activeElement;

      if (e.shiftKey && (current === firstItem || !container.contains(current))) {
        e.preventDefault();
        lastItem.focus();
      } else if (!e.shiftKey && current === lastItem) {
        e.preventDefault();
        firstItem.focus();
      }
    };

    document.addEventListener('keydown', onKeyDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown, true);
      // Only restore if the old element is still in the document — the overlay
      // may have closed because the user navigated away.
      if (previouslyFocused && document.contains(previouslyFocused)) {
        previouslyFocused.focus({ preventScroll: true });
      }
    };
  }, [active]);

  return containerRef;
}
