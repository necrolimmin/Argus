import type { LucideIcon } from "lucide-react";
import { RotateCw, TriangleAlert } from "lucide-react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

import { intlLocale } from "../i18n";

/*
 * Loading, error and empty look different on purpose (DESIGN.md §6): an
 * operator must tell "still loading" from "broken" at a glance.
 */

interface SkeletonProps {
  /** Rows to draw; keep it near the real page size so nothing jumps. */
  rows?: number;
  /** Bar widths per column, in px. */
  columns?: number[];
  /** Header labels, shown at once while the values load. */
  headers?: string[];
}

/** A table whose values are flat grey bars at their real size. No shimmer. */
export function Skeleton({ rows = 6, columns = [80, 140, 180, 100, 72], headers }: SkeletonProps) {
  const { t } = useTranslation();
  return (
    <div className="skeleton" role="status" aria-live="polite">
      <span className="visually-hidden">{t("common.loading")}</span>
      <table className="table" aria-hidden>
        {headers && (
          <thead>
            <tr>
              {headers.map((h) => (
                <th key={h}>{h}</th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {Array.from({ length: rows }, (_, r) => (
            <tr key={r}>
              {columns.map((w, c) => (
                // Widths vary a little by row so the block reads as data, not a stripe.
                <td key={c}>
                  <span className="skeleton-bar" style={{ width: Math.round(w * (1 - ((r + c) % 3) * 0.12)) }} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

interface ErrorStateProps {
  /** What failed, in the screen's words: "Не удалось загрузить устройства". */
  title?: string;
  /** When the data was last good (react-query's dataUpdatedAt); 0 or undefined if never. */
  lastOk?: number | Date | null;
  onRetry?: () => void;
  retrying?: boolean;
}

export function ErrorState({ title, lastOk, onRetry, retrying }: ErrorStateProps) {
  const { t } = useTranslation();
  const at = lastOk ? new Date(lastOk) : null;
  return (
    <div className="state state-error" role="alert">
      <div className="state-title">
        <TriangleAlert size={18} aria-hidden />
        <span>{title ?? t("states.loadFailed")}</span>
      </div>
      <p className="state-text">
        {at ? (
          <>
            {t("states.lastOk")}{" "}
            <span className="num">{at.toLocaleTimeString(intlLocale(), { hour: "2-digit", minute: "2-digit", second: "2-digit" })}</span>
          </>
        ) : (
          t("states.neverOk")
        )}
      </p>
      {onRetry && (
        <button className="btn btn-sm" onClick={onRetry} disabled={retrying}>
          <RotateCw size={14} aria-hidden />
          {t("common.retry")}
        </button>
      )}
    </div>
  );
}

interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  text?: ReactNode;
  /** The next step: usually the screen's primary button, or "reset filters". */
  action?: ReactNode;
}

export function EmptyState({ icon: Icon, title, text, action }: EmptyStateProps) {
  return (
    <div className="state">
      <div className="state-title">
        {Icon && <Icon size={18} aria-hidden className="state-icon" />}
        <span>{title}</span>
      </div>
      {text && <p className="state-text">{text}</p>}
      {action}
    </div>
  );
}
