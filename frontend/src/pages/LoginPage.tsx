import { Eye, EyeOff, UserRound } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, setToken } from "../api/client";
import { ArgusCameras } from "../components/ArgusCameras";
import { Brand, LanguageSwitch, ThemeToggle } from "../components/Layout";
import { errorText } from "../lib/errors";
import { useAuth } from "../lib/store";

export function LoginPage() {
  const { t } = useTranslation();
  const setUser = useAuth((s) => s.setUser);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [shown, setShown] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.login(username.trim(), password);
      setToken(res.access_token);
      setUser(res.user);
    } catch (err) {
      setError(errorText(t, err));
    } finally {
      setBusy(false);
    }
  };

  const reveal = shown ? t("login.hidePassword") : t("login.showPassword");

  return (
    <div className="login">
      {/* A wall of cameras that turn to the pointer; the door is a pane of glass in front of it. */}
      <ArgusCameras />
      <form className="login-card" onSubmit={submit}>
        <Brand />
        <div className="login-head">
          <h1>{t("login.title")}</h1>
          <p>{t("login.tagline")}</p>
        </div>
        <label className="login-field">
          <span className="visually-hidden">{t("login.username")}</span>
          <input
            className="input"
            autoComplete="username"
            placeholder={t("login.username")}
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            required
            autoFocus
          />
          <UserRound size={18} aria-hidden className="login-field-icon" />
        </label>
        <div className="login-field">
          <label className="visually-hidden" htmlFor="login-password">
            {t("login.password")}
          </label>
          <input
            id="login-password"
            className="input"
            type={shown ? "text" : "password"}
            autoComplete="current-password"
            placeholder={t("login.password")}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
          <button type="button" className="login-reveal" onClick={() => setShown((s) => !s)} aria-label={reveal} title={reveal} aria-pressed={shown}>
            {shown ? <Eye size={18} /> : <EyeOff size={18} />}
          </button>
        </div>
        {error && (
          <p className="form-error m-0" role="alert">
            {error}
          </p>
        )}
        <button className="btn btn-primary" type="submit" disabled={busy} aria-busy={busy}>
          {t("login.submit")}
        </button>
        <div className="login-tools">
          <LanguageSwitch />
          <ThemeToggle />
        </div>
      </form>
    </div>
  );
}
