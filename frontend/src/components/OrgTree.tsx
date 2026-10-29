import { ChevronRight, Pencil, Plus, Trash2 } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { LEVELS, type OrgUnit } from "../api/types";
import { ancestry, buildTree, type TreeNode } from "../lib/tree";

interface Props {
  units: OrgUnit[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  /** What the small number on the right counts. */
  count?: "camera_count" | "employee_count";
  /** Admin editing actions; omitted on read-only trees. */
  onAddChild?: (parent: TreeNode) => void;
  onRename?: (unit: TreeNode) => void;
  onDelete?: (unit: TreeNode) => void;
}

export function OrgTree({ units, selectedId, onSelect, count, onAddChild, onRename, onDelete }: Props) {
  const tree = useMemo(() => buildTree(units), [units]);
  const [open, setOpen] = useState<Set<string>>(new Set());
  const [primed, setPrimed] = useState(false);

  // Companies start expanded so their branches are visible right away.
  useEffect(() => {
    if (primed || !tree.length) return;
    setOpen((prev) => new Set([...prev, ...tree.map((n) => n.id)]));
    setPrimed(true);
  }, [tree, primed]);

  // Keep the selected unit visible.
  useEffect(() => {
    const chain = ancestry(units, selectedId).slice(0, -1);
    if (chain.some((id) => !open.has(id))) setOpen((prev) => new Set([...prev, ...chain]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedId, units]);

  const toggle = (id: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <Branch
      nodes={tree}
      open={open}
      toggle={toggle}
      selectedId={selectedId}
      onSelect={onSelect}
      count={count}
      onAddChild={onAddChild}
      onRename={onRename}
      onDelete={onDelete}
      root
    />
  );
}

interface BranchProps extends Omit<Props, "units"> {
  nodes: TreeNode[];
  open: Set<string>;
  toggle: (id: string) => void;
  root?: boolean;
}

function Branch({ nodes, open, toggle, root, ...p }: BranchProps) {
  const { t } = useTranslation();
  return (
    <ul className="tree" role={root ? "tree" : "group"}>
      {nodes.map((n) => {
        const expanded = open.has(n.id);
        const last = LEVELS.indexOf(n.level) === LEVELS.length - 1;
        const childLevel = LEVELS[LEVELS.indexOf(n.level) + 1];
        return (
          <li key={n.id} role="treeitem" aria-expanded={n.children.length ? expanded : undefined} aria-selected={p.selectedId === n.id}>
            <div className={`tree-row${p.selectedId === n.id ? " active" : ""}`}>
              <button
                className="tree-caret"
                onClick={() => toggle(n.id)}
                disabled={!n.children.length}
                aria-expanded={expanded}
                aria-label={n.name}
                tabIndex={-1}
              >
                <ChevronRight size={15} />
              </button>
              <button className="tree-label" onClick={() => p.onSelect(n.id)} title={n.name}>
                <span className="tree-name">{n.name}</span>
                <span className="tree-level">{t(`levels.${n.level}`)}</span>
                {p.count && <span className="tree-count">{n[p.count]}</span>}
              </button>
              {p.onAddChild && (
                <span className="tree-actions">
                  {!last && (
                    <button className="icon-btn sm" onClick={() => p.onAddChild!(n)} title={t(`addChild.${childLevel}`)} aria-label={t(`addChild.${childLevel}`)}>
                      <Plus size={15} />
                    </button>
                  )}
                  <button className="icon-btn sm" onClick={() => p.onRename!(n)} title={t("org.rename")} aria-label={t("org.rename")}>
                    <Pencil size={14} />
                  </button>
                  <button className="icon-btn sm danger" onClick={() => p.onDelete!(n)} title={t("common.delete")} aria-label={t("common.delete")}>
                    <Trash2 size={14} />
                  </button>
                </span>
              )}
            </div>
            {expanded && n.children.length > 0 && <Branch nodes={n.children} open={open} toggle={toggle} {...p} />}
          </li>
        );
      })}
    </ul>
  );
}
