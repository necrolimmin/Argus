import { ChevronDown } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import type { OrgUnit } from "../api/types";
import { type TreeNode, unitPath } from "../lib/tree";
import { OrgTree } from "./OrgTree";
import { ListSkeleton } from "./States";

interface Props {
  units: OrgUnit[];
  loading?: boolean;
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  count?: "camera_count" | "employee_count";
  /** A first row that selects nothing, e.g. "All employees". */
  allLabel?: string;
  /** What the closed picker says when nothing is chosen and there is no allLabel. */
  placeholder?: string;
  /** inline: opens in place (a side column); popover: floats under the button (a toolbar). */
  variant?: "inline" | "popover";
  defaultOpen?: boolean;
  onAddChild?: (parent: TreeNode) => void;
  onRename?: (unit: TreeNode) => void;
  onDelete?: (unit: TreeNode) => void;
  /** Under the tree, e.g. "Add company" or the empty-structure note. */
  footer?: ReactNode;
}

/**
 * The structure as one line: "Structure / Company / Branch ▾". The tree opens
 * under it and choosing a unit closes it again. The same picker on Cameras
 * and on Staff (DESIGN.md §6).
 */
export function UnitPicker({
  units,
  loading,
  selectedId,
  onSelect,
  count,
  allLabel,
  placeholder,
  variant = "inline",
  defaultOpen = false,
  onAddChild,
  onRename,
  onDelete,
  footer,
}: Props) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(defaultOpen);
  const ref = useRef<HTMLDivElement>(null);
  const value = selectedId ? unitPath(units, selectedId) : (allLabel ?? placeholder ?? "");

  // A floating tree closes when the click lands elsewhere or on Escape.
  useEffect(() => {
    if (!open || variant !== "popover") return;
    const away = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open, variant]);

  const choose = (id: string | null) => {
    onSelect(id);
    setOpen(false);
  };

  return (
    <div className={`unit-pick ${variant}`} ref={ref}>
      <button className="unit-picker" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <span className="unit-picker-label">{t("cameras.structure")}</span>
        <span className="unit-picker-value">{value}</span>
        <ChevronDown size={16} aria-hidden className="unit-picker-caret" />
      </button>
      {open && (
        <div className="unit-tree">
          {loading && <ListSkeleton />}
          {allLabel && !loading && (
            <div className={`tree-row${selectedId === null ? " active" : ""}`}>
              <button className="tree-label tree-root" onClick={() => choose(null)}>
                <span className="tree-name">{allLabel}</span>
              </button>
            </div>
          )}
          <OrgTree
            units={units}
            selectedId={selectedId}
            onSelect={choose}
            count={count}
            onAddChild={onAddChild}
            onRename={onRename}
            onDelete={onDelete}
          />
          {footer && (
            // An action down here opens a dialog; the tree makes way for it.
            <div className="unit-tree-foot" onClick={() => setOpen(false)}>
              {footer}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
