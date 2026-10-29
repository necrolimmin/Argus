import type { LucideIcon } from "lucide-react";
import { MoreHorizontal } from "lucide-react";
import { type CSSProperties, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

export interface RowAction {
  icon: LucideIcon;
  label: string;
  onClick: () => void;
  danger?: boolean;
}

/**
 * A row's actions: icon buttons on a desktop, one "⋯" menu on a phone, where
 * a row is too narrow for them. CSS decides which of the two is shown.
 */
export function RowActions({ actions }: { actions: RowAction[] }) {
  const { t } = useTranslation();
  // The menu is placed against the screen, not the row: a scrolling table
  // would otherwise clip it.
  const [open, setOpen] = useState<CSSProperties | null>(null);
  const ref = useRef<HTMLDivElement>(null);
  const toggle = (button: HTMLElement) => {
    if (open) return setOpen(null);
    const r = button.getBoundingClientRect();
    setOpen({ position: "fixed", top: r.bottom + 4, right: Math.max(8, window.innerWidth - r.right) });
  };

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(null);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(null);
    // Clicking the button can scroll the table a little to bring it into
    // focus; only a scroll after that closes the menu.
    const openedAt = Date.now();
    const close = () => Date.now() - openedAt > 300 && setOpen(null);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    window.addEventListener("scroll", close, true);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
      window.removeEventListener("scroll", close, true);
    };
  }, [open]);

  return (
    <div className="row-actions" ref={ref} onClick={(e) => e.stopPropagation()}>
      <span className="row-actions-inline">
        {actions.map((a) => (
          <button key={a.label} className={`icon-btn sm${a.danger ? " danger" : ""}`} title={a.label} aria-label={a.label} onClick={a.onClick}>
            <a.icon size={15} />
          </button>
        ))}
      </span>
      <button
        className="icon-btn sm row-actions-more"
        aria-label={t("common.actions")}
        aria-haspopup="menu"
        aria-expanded={open !== null}
        onClick={(e) => toggle(e.currentTarget)}
      >
        <MoreHorizontal size={16} />
      </button>
      {open && (
        <div className="menu-pop row-actions-menu" role="menu" style={open}>
          {actions.map((a) => (
            <button
              key={a.label}
              role="menuitem"
              className={a.danger ? "danger" : undefined}
              onClick={() => {
                setOpen(null);
                a.onClick();
              }}
            >
              <a.icon size={16} aria-hidden />
              {a.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
