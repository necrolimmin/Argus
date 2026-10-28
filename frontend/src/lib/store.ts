import { create } from "zustand";

import type { User } from "../api/types";
import { load, save } from "./storage";
import { add, remove, type Slots, trim } from "./wall";

type Theme = "dark" | "light";
export type Layout = "auto" | 1 | 4 | 9 | 16;

interface AuthState {
  user: User | null;
  setUser: (user: User | null) => void;
}

export const useAuth = create<AuthState>((set) => ({
  user: null,
  setUser: (user) => set({ user }),
}));

export const isAdmin = (user: User | null) => user?.role === "admin";

interface UiState {
  theme: Theme;
  toggleTheme: () => void;
  navCollapsed: boolean;
  toggleNav: () => void;
  toast: { id: number; text: string; tone: "ok" | "error" } | null;
  notify: (text: string, tone?: "ok" | "error") => void;
}

const THEME_KEY = "argus.theme";
const NAV_KEY = "argus.navCollapsed";

function applyTheme(theme: Theme) {
  document.documentElement.dataset.theme = theme;
}

const initialTheme = load<Theme>(THEME_KEY, "dark");
applyTheme(initialTheme);

export const useUi = create<UiState>((set, get) => ({
  theme: initialTheme,
  toggleTheme: () => {
    const theme = get().theme === "dark" ? "light" : "dark";
    applyTheme(theme);
    save(THEME_KEY, theme);
    set({ theme });
  },
  navCollapsed: load<boolean>(NAV_KEY, false),
  toggleNav: () => {
    const navCollapsed = !get().navCollapsed;
    save(NAV_KEY, navCollapsed);
    set({ navCollapsed });
  },
  toast: null,
  notify: (text, tone = "ok") => {
    const id = Date.now();
    set({ toast: { id, text, tone } });
    setTimeout(() => {
      if (get().toast?.id === id) set({ toast: null });
    }, 4000);
  },
}));

/** What is on the Cameras screen; remembered per user between visits. */
interface WallState {
  unitId: string | null;
  /** Cells of the wall in order; see lib/wall.ts. */
  cameraIds: Slots;
  layout: Layout;
  page: number;
  hydrate: (userId: string) => void;
  setUnit: (id: string | null) => void;
  setSlots: (slots: Slots) => void;
  addCameras: (ids: string[]) => void;
  removeCameras: (ids: string[]) => void;
  toggleCamera: (id: string) => void;
  setLayout: (layout: Layout) => void;
  setPage: (page: number) => void;
}

let wallKey = "argus.wall";

export const useWall = create<WallState>((set, get) => {
  const persist = () => {
    const { unitId, cameraIds, layout } = get();
    save(wallKey, { unitId, cameraIds, layout });
  };
  const setSlots = (cameraIds: Slots) => {
    set({ cameraIds: trim(cameraIds) });
    persist();
  };
  return {
    unitId: null,
    cameraIds: [],
    layout: "auto",
    page: 0,
    hydrate: (userId) => {
      wallKey = `argus.wall.${userId}`;
      const saved = load<{ unitId: string | null; cameraIds: Slots; layout: Layout } | null>(wallKey, null);
      set({ unitId: saved?.unitId ?? null, cameraIds: saved?.cameraIds ?? [], layout: saved?.layout ?? "auto", page: 0 });
    },
    setUnit: (unitId) => {
      set({ unitId });
      persist();
    },
    setSlots,
    addCameras: (ids) => setSlots(add(get().cameraIds, ids)),
    removeCameras: (ids) => setSlots(remove(get().cameraIds, ids)),
    toggleCamera: (id) => {
      const slots = get().cameraIds;
      setSlots(slots.includes(id) ? remove(slots, [id]) : add(slots, [id]));
    },
    setLayout: (layout) => {
      set({ layout, page: 0 });
      persist();
    },
    setPage: (page) => set({ page }),
  };
});
