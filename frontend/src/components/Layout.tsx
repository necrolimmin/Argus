import { useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  Check,
  ChevronsUpDown,
  Cctv,
  CircleUserRound,
  KeyRound,
  Languages,
  LogOut,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PlugZap,
  Router,
  Sun,
  Users,
} from "lucide-react";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";

import { setToken } from "../api/client";
import { intlLocale, LANGUAGES, setLanguage } from "../i18n";
import { isAdmin, useAuth, useUi } from "../lib/store";
import { PasswordModal } from "../pages/PasswordModal";

export function Brand() {
  return (
    <div className="brand">
      {/* Argus, the watchman of a hundred eyes: one eye, its iris and pupil. */}
      <svg className="brand-mark" viewBox="0 0 24 24" fill="none" aria-hidden>
        <path d="M1.75 12C5 6.25 19 6.25 22.25 12 19 17.75 5 17.75 1.75 12Z" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" />
        <circle cx="12" cy="12" r="3.9" stroke="currentColor" strokeWidth="1.75" />
        <circle cx="12" cy="12" r="1.5" fill="currentColor" />
      </svg>
      <span>Argus</span>
    </div>
  );
}

/** Close a popup on a click elsewhere or on Escape. */
function useDismiss(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  const closeRef = useRef(close);
  closeRef.current = close;
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && closeRef.current();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && closeRef.current();
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);
  return ref;
}

/**
 * One small button with the current language; the four languages, each in
 * its own name, open in a menu above it.
 */
export function LanguageSwitch() {
  const { i18n } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const current = LANGUAGES.find((l) => l.code === i18n.language) ?? LANGUAGES[0];
  return (
    <div className="lang-menu" ref={ref}>
      <button
        type="button"
        className="btn btn-ghost btn-sm lang-button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={i18n.t("langName")}
        title={i18n.t("langName")}
        onClick={() => setOpen((o) => !o)}
      >
        <Languages size={16} aria-hidden />
        <span>{current.short}</span>
      </button>
      {open && (
        <div className="menu-pop lang-pop" role="menu">
          {LANGUAGES.map((l) => (
            <button
              type="button"
              key={l.code}
              role="menuitemradio"
              aria-checked={l.code === current.code}
              onClick={() => {
                setLanguage(l.code);
                setOpen(false);
              }}
            >
              <span className="lang-name">{i18n.t("langName", { lng: l.code })}</span>
              {l.code === current.code && <Check size={16} aria-hidden />}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export function ThemeToggle() {
  const { t } = useTranslation();
  const { theme, toggleTheme } = useUi();
  const label = theme === "dark" ? t("nav.themeLight") : t("nav.themeDark");
  return (
    <button type="button" className="icon-btn" onClick={toggleTheme} title={label} aria-label={label}>
      {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
    </button>
  );
}

function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((w) => w[0].toUpperCase())
    .join("");
}

// Hour marks all round; figures only at the quarters, as on a wall clock.
const MARKS = Array.from({ length: 12 }, (_, i) => i);
const QUARTERS = [
  { n: 12, x: 100, y: 46 },
  { n: 3, x: 154, y: 100 },
  { n: 6, x: 100, y: 154 },
  { n: 9, x: 46, y: 100 },
];

interface HandProps {
  deg: number;
  length: number;
  tail: number;
  width: number;
  className: string;
}

/** A hand from a little behind the centre out to `length`, at `deg` clockwise from the top. */
function Hand({ deg, length, tail, width, className }: HandProps) {
  return (
    <line
      className={className}
      x1="100"
      y1={100 + tail}
      x2="100"
      y2={100 - length}
      strokeWidth={width}
      transform={`rotate(${deg} 100 100)`}
    />
  );
}

/**
 * The station clock: a wall-clock dial in the site's own colours, figures at
 * the quarters, three hands; the second hand is the brand amber. The exact time and the date sit beside it
 * for matching against event times.
 */
function StationClock() {
  const { i18n } = useTranslation();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(tick);
  }, []);
  const locale = intlLocale();
  const h = now.getHours() % 12;
  const m = now.getMinutes();
  const sec = now.getSeconds();
  const time = now.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false });
  const date = now.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "long" });
  return (
    <div className="station-clock" key={i18n.language}>
      <svg className="clock-dial" viewBox="0 0 200 200" role="img" aria-label={`${time}, ${date}`}>
        <circle className="clock-face" cx="100" cy="100" r="95" />
        {MARKS.map((k) => (
          <line
            key={k}
            className={k % 3 === 0 ? "clock-mark quarter" : "clock-mark"}
            x1="100"
            y1="13"
            x2="100"
            y2={k % 3 === 0 ? 27 : 24}
            transform={`rotate(${k * 30} 100 100)`}
          />
        ))}
        {QUARTERS.map((q) => (
          <text key={q.n} className="clock-figure" x={q.x} y={q.y}>
            {q.n}
          </text>
        ))}
        <Hand className="clock-hand hour" deg={(h + m / 60) * 30} length={52} tail={0} width={9} />
        <Hand className="clock-hand minute" deg={(m + sec / 60) * 6} length={76} tail={0} width={6} />
        <Hand className="clock-hand second" deg={sec * 6} length={80} tail={0} width={3} />
        <circle className="clock-cap" cx="100" cy="100" r="9" />
      </svg>
      <div className="clock-caption">
        <time className="clock-time" dateTime={now.toISOString()}>
          {time}
        </time>
        <span className="clock-date">{date}</span>
      </div>
    </div>
  );
}

function UserMenu() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { user, setUser } = useAuth();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState(false);
  const ref = useDismiss(open, () => setOpen(false));
  const name = user?.full_name || user?.username || "";
  const role = t(`users.roles.${user?.role ?? "operator"}`);

  const logout = () => {
    setToken(null);
    qc.clear();
    setUser(null);
  };

  return (
    <div className="menu" ref={ref}>
      <button
        type="button"
        className="user-card"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-haspopup="menu"
        title={name}
      >
        <span className="user-avatar" aria-hidden>
          {initials(name) || <CircleUserRound size={18} />}
        </span>
        <span className="user-text">
          <span className="user-name">{name}</span>
          <span className="user-role">{role}</span>
        </span>
        <ChevronsUpDown size={14} aria-hidden className="user-caret" />
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          {isAdmin(user) && (
            <Link to="/users" onClick={() => setOpen(false)}>
              <Users size={16} />
              {t("nav.users")}
            </Link>
          )}
          <button
            onClick={() => {
              setOpen(false);
              setPassword(true);
            }}
          >
            <KeyRound size={16} />
            {t("nav.password")}
          </button>
          <button onClick={logout}>
            <LogOut size={16} />
            {t("nav.logout")}
          </button>
        </div>
      )}
      {password && <PasswordModal onClose={() => setPassword(false)} />}
    </div>
  );
}

const TABS = [
  { to: "/cameras", icon: Cctv, label: "nav.cameras", adminOnly: false },
  // Addresses and logins of cameras: administrators only.
  { to: "/devices", icon: Router, label: "nav.devices", adminOnly: true },
  { to: "/org", icon: Building2, label: "nav.orgShort", adminOnly: false },
  { to: "/integrations", icon: PlugZap, label: "nav.api", adminOnly: false },
] as const;

/**
 * One pill behind the active nav item that glides to the next one when the
 * tab changes, instead of each item lighting up on its own.
 */
function useNavPill(deps: unknown[]) {
  const navRef = useRef<HTMLElement>(null);
  const [pill, setPill] = useState<{ x: number; y: number; w: number; h: number } | null>(null);
  useLayoutEffect(() => {
    const place = () => {
      const active = navRef.current?.querySelector<HTMLElement>("a.active");
      setPill(active ? { x: active.offsetLeft, y: active.offsetTop, w: active.offsetWidth, h: active.offsetHeight } : null);
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);
  return { navRef, pill };
}

export function Layout() {
  const { t, i18n } = useTranslation();
  const toast = useUi((s) => s.toast);
  const { navCollapsed, toggleNav } = useUi();
  const admin = isAdmin(useAuth((s) => s.user));
  const toggleLabel = navCollapsed ? t("nav.expand") : t("nav.collapse");
  const { pathname } = useLocation();
  const { navRef, pill } = useNavPill([pathname, navCollapsed, admin, i18n.language]);
  return (
    <div className={`app${navCollapsed ? " nav-collapsed" : ""}`}>
      <aside className="sidebar">
        <div className="sidebar-head">
          <Brand />
          <StationClock />
        </div>
        <nav className="nav" ref={navRef}>
          {pill && (
            <span
              className="nav-pill"
              aria-hidden
              style={{ width: pill.w, height: pill.h, transform: `translate(${pill.x}px, ${pill.y}px)` }}
            />
          )}
          {TABS.filter((tab) => admin || !tab.adminOnly).map(({ to, icon: Icon, label }) => (
            <NavLink key={to} to={to} title={navCollapsed ? t(label) : undefined}>
              <Icon size={18} aria-hidden />
              <span className="nav-label">{t(label)}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-tools">
          <div className="sidebar-row">
            <LanguageSwitch />
            <ThemeToggle />
            <span className="spacer" />
            <button type="button" className="icon-btn nav-toggle" onClick={toggleNav} title={toggleLabel} aria-label={toggleLabel}>
              {navCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>
          </div>
          <UserMenu />
        </div>
      </aside>
      <main className="main">
        <Outlet />
      </main>
      {toast && (
        <div className={`toast${toast.tone === "error" ? " error" : ""}`} role="status" key={toast.id}>
          {toast.text}
        </div>
      )}
    </div>
  );
}
