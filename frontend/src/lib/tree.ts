import type { OrgUnit } from "../api/types";

export interface TreeNode extends OrgUnit {
  children: TreeNode[];
  depth: number;
}

/**
 * Builds the tree from the flat list. Units whose parent is not visible
 * (an operator's own unit) become roots.
 */
export function buildTree(units: OrgUnit[]): TreeNode[] {
  const byId = new Map<string, TreeNode>();
  units.forEach((u) => byId.set(u.id, { ...u, children: [], depth: 0 }));
  const roots: TreeNode[] = [];
  byId.forEach((node) => {
    const parent = node.parent_id ? byId.get(node.parent_id) : undefined;
    if (parent) parent.children.push(node);
    else roots.push(node);
  });
  const sort = (nodes: TreeNode[], depth: number) => {
    nodes.sort((a, b) => a.name.localeCompare(b.name));
    nodes.forEach((n) => {
      n.depth = depth;
      sort(n.children, depth + 1);
    });
  };
  sort(roots, 0);
  return roots;
}

/** Depth-first list, for selects. */
export function flatten(nodes: TreeNode[]): TreeNode[] {
  return nodes.flatMap((n) => [n, ...flatten(n.children)]);
}

/** Ids from the root down to `id`, inclusive. */
export function ancestry(units: OrgUnit[], id: string | null): string[] {
  const byId = new Map(units.map((u) => [u.id, u]));
  const chain: string[] = [];
  let cur = id ? byId.get(id) : undefined;
  while (cur) {
    chain.unshift(cur.id);
    cur = cur.parent_id ? byId.get(cur.parent_id) : undefined;
  }
  return chain;
}

export function unitPath(units: OrgUnit[], id: string): string {
  const byId = new Map(units.map((u) => [u.id, u]));
  return ancestry(units, id)
    .map((i) => byId.get(i)?.name ?? "")
    .join(" / ");
}
