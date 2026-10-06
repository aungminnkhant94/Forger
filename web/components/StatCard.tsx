interface StatCardProps {
  label: string;
  value: number;
  color: 'green' | 'orange' | 'gray';
}

export function StatCard({ label, value, color }: StatCardProps) {
  return (
    <div className={`stat-card ${color}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
    </div>
  );
}