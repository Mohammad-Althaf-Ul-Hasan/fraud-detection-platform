import { NavLink } from "react-router-dom";

const items = [
  { to: "/alerts",  label: "Live Alerts" },
  { to: "/metrics", label: "Metrics" },
  { to: "/graph",   label: "Graph View" },
];

export default function NavBar() {
  return (
    <nav className="bg-slate-900 border-b border-slate-700 px-6 py-3 flex items-center gap-6">
      <div className="font-bold text-lg text-white">🛡️ Fraud Detection</div>
      <div className="flex gap-1">
        {items.map(({ to, label }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `px-3 py-1.5 rounded text-sm font-medium transition-colors ${
                isActive
                  ? "bg-blue-600 text-white"
                  : "text-slate-300 hover:bg-slate-800"
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </div>
    </nav>
  );
}