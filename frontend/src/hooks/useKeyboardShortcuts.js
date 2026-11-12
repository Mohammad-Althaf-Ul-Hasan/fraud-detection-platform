import { useEffect } from "react";

/**
 * Global keyboard shortcut dispatcher.
 * Handles single keys ("j", "?") and two-key sequences ("g a").
 * Ignores typing in form fields and OS-level modifiers.
 * Cmd/Ctrl+K is reserved for the command palette (handled separately).
 */
export function useKeyboardShortcuts(map) {
  useEffect(() => {
    let pendingPrefix = null;
    let prefixTimer = null;

    // Precompute the set of valid prefixes (e.g. "g" from "g a")
    const prefixes = new Set();
    for (const combo of Object.keys(map)) {
      if (combo.includes(" ")) prefixes.add(combo.split(" ")[0]);
    }

    function clearPrefix() {
      pendingPrefix = null;
      if (prefixTimer) {
        clearTimeout(prefixTimer);
        prefixTimer = null;
      }
    }

    function isTyping(e) {
      const t = e.target;
      return (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      );
    }

    function handle(e) {
      if (isTyping(e)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;

      const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;

      if (pendingPrefix) {
        const combo = `${pendingPrefix} ${key}`;
        const fn = map[combo];
        clearPrefix();
        if (fn) {
          e.preventDefault();
          fn();
        }
        return;
      }

      if (prefixes.has(key)) {
        pendingPrefix = key;
        prefixTimer = setTimeout(clearPrefix, 1500);
        return;
      }

      const fn = map[key];
      if (fn) {
        e.preventDefault();
        fn();
      }
    }

    document.addEventListener("keydown", handle);
    return () => {
      document.removeEventListener("keydown", handle);
      clearPrefix();
    };
  }, [map]);
}