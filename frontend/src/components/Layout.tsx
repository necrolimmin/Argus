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
import { isAdmin, isViewer, useAuth, useUi } from "../lib/store";
import { PasswordModal } from "../pages/PasswordModal";

/**
 * The Argus mark: the four corners of a camera viewfinder framing the lens.
 * The corners are the motif of the whole interface (camera tiles show them
 * on hover); the lens is the one amber spot.
 */
export function Logo({ size = 24 }: { size?: number }) {
  return (
    <svg className="logo" width={size} height={size} viewBox="0 0 24 24" fill="none" aria-hidden>
      <path className="logo-frame" d="M2 8V3.5C2 2.67 2.67 2 3.5 2H8M16 2h4.5c.83 0 1.5.67 1.5 1.5V8M22 16v4.5c0 .83-.67 1.5-1.5 1.5H16M8 22H3.5C2.67 22 2 21.33 2 20.5V16" strokeWidth="2.2" strokeLinecap="round" />
      <circle className="logo-lens" cx="12" cy="12" r="4.6" />
      <circle className="logo-glint" cx="13.6" cy="10.4" r="1.25" />
    </svg>
  );
}

export function Brand() {
  return (
    <div className="brand">
      <Logo />
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

/**
 * The station clock: the time large, seconds on a thin track that fills over
 * the minute like a recorder's progress bar, and the date. Operators match
 * event times against it.
 */
function StationClock() {
  const { i18n } = useTranslation();
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const tick = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(tick);
  }, []);
  const locale = intlLocale();
  const hm = now.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", hour12: false });
  const sec = now.getSeconds();
  const date = now.toLocaleDateString(locale, { weekday: "long", day: "numeric", month: "long" });
  return (
    <div className="station-clock" key={i18n.language} role="timer" aria-label={`${hm}, ${date}`}>
      <time className="clock-time" dateTime={now.toISOString()}>
        {hm}
        <span className="clock-seconds">{String(sec).padStart(2, "0")}</span>
      </time>
      <span className="clock-track" aria-hidden>
        {/* A new bar each minute, so it starts empty instead of sliding back. */}
        <i key={now.getMinutes()} style={{ width: `${((sec + 1) / 60) * 100}%` }} />
      </span>
      <span className="clock-date">{date}</span>
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

// The menu in three groups, so a newcomer sees what is for watching, what
// is for setting things up, and what is the system itself.
const GROUPS = [
  { label: "nav.groupWatch", tabs: [{ to: "/cameras", icon: Cctv, label: "nav.cameras", hint: "nav.hintCameras", adminOnly: false }] },
  {
    label: "nav.groupManage",
    tabs: [
      // Addresses and logins of cameras: administrators only.
      { to: "/devices", icon: Router, label: "nav.devices", hint: "nav.hintDevices", adminOnly: true },
      { to: "/org", icon: Building2, label: "nav.orgShort", hint: "nav.hintOrg", adminOnly: false },
    ],
  },
  { label: "nav.groupSystem", tabs: [{ to: "/integrations", icon: PlugZap, label: "nav.api", hint: "nav.hintApi", adminOnly: false }] },
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
  const user = useAuth((s) => s.user);
  const admin = isAdmin(user);
  const viewer = isViewer(user);
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
          {GROUPS.map((group) => {
            // A viewer has the camera wall and nothing else.
            const tabs = group.tabs.filter((tab) => (admin || !tab.adminOnly) && (!viewer || tab.to === "/cameras"));
            if (!tabs.length) return null;
            return (
              <div key={group.label} className="nav-group" role="group" aria-label={t(group.label)}>
                <span className="nav-group-label">{t(group.label)}</span>
                {tabs.map(({ to, icon: Icon, label, hint }) => (
                  <NavLink key={to} to={to} title={navCollapsed ? t(label) : undefined}>
                    <Icon size={18} aria-hidden />
                    <span className="nav-text">
                      <span className="nav-label">{t(label)}</span>
                      <span className="nav-hint">{t(hint)}</span>
                    </span>
                  </NavLink>
                ))}
              </div>
            );
          })}
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
