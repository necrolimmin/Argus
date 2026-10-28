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
