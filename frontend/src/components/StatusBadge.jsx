export default function StatusBadge({ decision }) {
  const isBlock = decision === "BLOCK";
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-xs font-semibold ${
        isBlock
          ? "bg-red-500/20 text-red-300 border border-red-500/40"
          : "bg-green-500/20 text-green-300 border border-green-500/40"
      }`}
    >
      {decision}
    </span>
  );
}