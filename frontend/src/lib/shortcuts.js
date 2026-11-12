// Central registry of all keyboard shortcuts.
// Keep this the single source of truth for both the hook and the help overlay.

export const SHORTCUT_GROUPS = [
  {
    name: "Navigation",
    shortcuts: [
      { keys: "G A", description: "Go to Live Alerts" },
      { keys: "G M", description: "Go to Metrics" },
      { keys: "G G", description: "Go to Graph Explorer" },
      { keys: "G V", description: "Go to Model Versions" },
      { keys: "G D", description: "Go to Drift Monitor" },
    ],
  },
  {
    name: "Alerts",
    shortcuts: [
      { keys: "J", description: "Next row" },
      { keys: "K", description: "Previous row" },
      { keys: "E", description: "Open selected row" },
      { keys: "/", description: "Focus search" },
    ],
  },
  {
    name: "Global",
    shortcuts: [
      { keys: "⌘ K", description: "Open command palette" },
      { keys: "?", description: "Show keyboard help" },
      { keys: "Esc", description: "Close overlay" },
    ],
  },
];