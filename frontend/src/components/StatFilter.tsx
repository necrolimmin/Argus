export interface Stat<K extends string> {
  key: K;
  label: string;
  count: number;
  /** A state dot before the label: online, offline, unknown. */
  dot?: "online" | "offline" | "unknown";
  /** Something to look at: drawn with a warning edge when the count is above zero. */
  attention?: boolean;
  title?: string;
}

interface Props<K extends string> {
  stats: Stat<K>[];
  value: K;
  onChange: (key: K) => void;
  label: string;
}

/**
 * The page's figures at a glance, which are also its filter: "6 devices,
 * 5 online, 1 offline". Pressing one shows only those rows.
 */
export function StatFilter<K extends string>({ stats, value, onChange, label }: Props<K>) {
  // The widest figure is the whole; the bar under each shows its share of it.
  const whole = Math.max(1, ...stats.map((s) => s.count));
  return (
    <div className="stat-filter" role="group" aria-label={label}>
      {stats.map((s) => (
        <button
          type="button"
          key={s.key}
          className={`stat${s.attention && s.count > 0 ? " attention" : ""}`}
          aria-pressed={value === s.key}
          title={s.title}
          onClick={() => onChange(s.key)}
        >
          <span className="stat-count num">{s.count}</span>
          <span className="stat-label">
            {s.dot && <i className={`dot ${s.dot}`} aria-hidden />}
            {s.label}
          </span>
          <span className={`stat-share${s.dot ? ` ${s.dot}` : ""}`} aria-hidden>
            <i style={{ width: `${(s.count / whole) * 100}%` }} />
          </span>
        </button>
      ))}
    </div>
  );
}
