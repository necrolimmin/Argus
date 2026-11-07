import type { LucideIcon } from "lucide-react";
import { ChevronDown } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";

export interface MenuItem {
  icon: LucideIcon;
  label: string;
  /** One line under the label: what this choice does. */
  hint?: string;
  onClick: () => void;
}

interface Props {
  label: ReactNode;
  items: MenuItem[];
  className?: string;
}

/**
 * One button that opens a short list of ways to do the same thing, e.g.
 * "Add ▾": by IP, find on the network, from a file. Keeps a toolbar to one
 * clear action instead of a row of look-alike buttons.
 */
export function MenuButton({ label, items, className = "btn btn-primary" }: Props) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  return (
    <div className="menu-button" ref={ref}>
      <button type="button" className={className} aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {label}
        <ChevronDown size={15} aria-hidden className="menu-button-caret" />
      </button>
      {open && (
        <div className="menu-pop menu-button-pop" role="menu">
          {items.map((item) => (
            <button
              type="button"
              key={item.label}
              role="menuitem"
              onClick={() => {
                setOpen(false);
                item.onClick();
              }}
            >
              <item.icon size={18} aria-hidden />
              <span className="menu-item-text">
                <span>{item.label}</span>
                {item.hint && <small>{item.hint}</small>}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
