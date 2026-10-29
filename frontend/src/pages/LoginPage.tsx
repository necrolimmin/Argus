import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, setToken } from "../api/client";
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
        <button className="btn btn-primary" type="submit" disabled={busy}>
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
