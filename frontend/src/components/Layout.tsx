import { useQueryClient } from "@tanstack/react-query";
import {
  Building2,
  Cctv,
  CircleUserRound,
  KeyRound,
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
import { LANGUAGES, setLanguage } from "../i18n";
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

export function LanguageSwitch() {
  const { i18n } = useTranslation();
  return (
    <div className="lang-switch" role="group" aria-label="Language">
      {LANGUAGES.map((l) => (
        <button key={l.code} type="button" aria-pressed={i18n.language === l.code} onClick={() => setLanguage(l.code)} title={l.code}>
          {l.short}
        </button>
      ))}
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

function UserMenu() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { user, setUser } = useAuth();
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);

  const logout = () => {
    setToken(null);
    qc.clear();
    setUser(null);
  };

  return (
    <div className="menu" ref={ref}>
      <button className="icon-btn" onClick={() => setOpen((o) => !o)} aria-expanded={open} aria-label={user?.username}>
        <CircleUserRound size={20} />
      </button>
      {open && (
        <div className="menu-pop">
          <div className="who">
            {user?.full_name || user?.username}
            <small>{t(`users.roles.${user?.role ?? "operator"}`)}</small>
          </div>
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
        <Brand />
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
              <span>{t(label)}</span>
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-tools">
          <LanguageSwitch />
          <div className="sidebar-row">
            <ThemeToggle />
            <UserMenu />
            <button className="icon-btn nav-toggle" onClick={toggleNav} title={toggleLabel} aria-label={toggleLabel}>
              {navCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>
          </div>
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
