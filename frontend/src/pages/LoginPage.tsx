import { Cctv, ScanFace, ShieldCheck } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, setToken } from "../api/client";
import { ArgusEyes } from "../components/ArgusEyes";
import { Brand, LanguageSwitch, ThemeToggle } from "../components/Layout";
import { errorText } from "../lib/errors";
import { useAuth } from "../lib/store";

export function LoginPage() {
  const { t } = useTranslation();
  const setUser = useAuth((s) => s.setUser);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
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

  return (
    <div className="login">
      {/* What Argus is, for someone who opens it for the first time: the
          watchman's eyes above, the name and what it does below. */}
      <aside className="login-stage">
        <ArgusEyes />
        <div className="login-intro">
          <p className="login-word" aria-hidden>
            Argus
          </p>
          <p className="login-tagline">{t("login.tagline")}</p>
          <p className="login-myth">{t("login.myth")}</p>
          <ul className="login-points">
            <li>
              <Cctv size={18} aria-hidden />
              {t("login.point1")}
            </li>
            <li>
              <ScanFace size={18} aria-hidden />
              {t("login.point2")}
            </li>
            <li>
              <ShieldCheck size={18} aria-hidden />
              {t("login.point3")}
            </li>
          </ul>
        </div>
      </aside>
      <div className="login-side">
        <form className="login-card" onSubmit={submit}>
          <Brand />
          <h1>{t("login.title")}</h1>
          <label className="field">
            <span>{t("login.username")}</span>
            <input className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required autoFocus />
          </label>
          <label className="field">
            <span>{t("login.password")}</span>
            <input className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
          </label>
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
    </div>
  );
}
