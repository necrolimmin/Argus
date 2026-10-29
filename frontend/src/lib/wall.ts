/**
 * The video wall as a list of slots. A slot holds a camera id or nothing, so a
 * camera can sit in any cell of a fixed grid, with gaps before it. Slot i is
 * cell i % perPage on page i / perPage.
 */

export type Slots = (string | null)[];

/** Most cameras on one page in automatic mode; more go to further pages. */
export const AUTO_MAX = 16;

export function trim(slots: Slots): Slots {
  let end = slots.length;
  while (end > 0 && slots[end - 1] === null) end--;
  return slots.slice(0, end);
}

export const compact = (slots: Slots): string[] => slots.filter((s): s is string => s !== null);

/** Columns and rows for `n` cameras: wider than tall, as screens are. */
export function autoGrid(n: number): { cols: number; rows: number } {
  const count = Math.min(Math.max(n, 1), AUTO_MAX);
  const cols = Math.ceil(Math.sqrt(count));
  return { cols, rows: Math.ceil(count / cols) };
}

/** Puts new cameras into the first free cells, then after the last one. */
export function add(slots: Slots, ids: string[]): Slots {
  const next = [...slots];
  for (const id of ids) {
    if (next.includes(id)) continue;
    const free = next.indexOf(null);
    if (free === -1) next.push(id);
    else next[free] = id;
  }
  return next;
}

/** Empties the cameras' cells; the others stay where they are. */
export const remove = (slots: Slots, ids: string[]): Slots =>
  trim(slots.map((s) => (s !== null && ids.includes(s) ? null : s)));

/** Swaps two cells; either may be empty. */
export function swap(slots: Slots, from: number, to: number): Slots {
  const next = [...slots];
  while (next.length <= Math.max(from, to)) next.push(null);
  [next[from], next[to]] = [next[to], next[from]];
  return trim(next);
}

/**
 * Drops a camera from the list onto a cell. Already on the wall: it swaps
 * with whatever is there. New: it takes the cell, and the camera it pushes
 * out moves to the first free cell.
 */
export function place(slots: Slots, id: string, to: number): Slots {
  const at = slots.indexOf(id);
  if (at !== -1) return swap(slots, at, to);
  const next = [...slots];
  while (next.length <= to) next.push(null);
  const displaced = next[to];
  next[to] = id;
  return trim(displaced ? add(next, [displaced]) : next);
}

export interface Bento {
  cols: number;
  rows: number;
  /** Cells the first (featured) camera spans; 1×1 when there is none. */
  feature: { cols: number; rows: number };
}

// Bento layouts for the automatic grid: the first camera is the big one and
// the rest fill the cells around it with nothing left over where possible.
// Every cell is 16:9 and the featured camera spans a square block of cells
// (2×2 or 3×3), so it stays 16:9 too: no black bands around its picture.
const BENTO: Record<number, Bento> = {
  // Up to four cameras the wall is an even grid; a big cell starts at five.
  1: { cols: 1, rows: 1, feature: { cols: 1, rows: 1 } },
  2: { cols: 2, rows: 1, feature: { cols: 1, rows: 1 } },
  3: { cols: 2, rows: 2, feature: { cols: 1, rows: 1 } },
  4: { cols: 2, rows: 2, feature: { cols: 1, rows: 1 } },
  5: { cols: 4, rows: 2, feature: { cols: 2, rows: 2 } },
  6: { cols: 3, rows: 3, feature: { cols: 2, rows: 2 } },
  7: { cols: 4, rows: 4, feature: { cols: 3, rows: 3 } },
  8: { cols: 4, rows: 3, feature: { cols: 2, rows: 2 } },
  9: { cols: 4, rows: 3, feature: { cols: 2, rows: 2 } },
  10: { cols: 4, rows: 4, feature: { cols: 2, rows: 2 } },
  11: { cols: 4, rows: 4, feature: { cols: 2, rows: 2 } },
  12: { cols: 4, rows: 4, feature: { cols: 2, rows: 2 } },
  13: { cols: 4, rows: 4, feature: { cols: 2, rows: 2 } },
};

/** Past 13 cameras the cells are too small to feature one: a plain grid. */
export function bento(n: number): Bento {
  const count = Math.min(Math.max(n, 1), AUTO_MAX);
  if (BENTO[count]) return BENTO[count];
  const { cols, rows } = autoGrid(count);
  return { cols, rows, feature: { cols: 1, rows: 1 } };
}

/** How many cameras a bento layout holds. */
export const bentoCells = (b: Bento) => b.cols * b.rows - b.feature.cols * b.feature.rows + 1;
