import { Eye, EyeOff, RefreshCw, UserRound } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
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
  // The picture of digits; null until the server says whether it asks for one.
  const [captcha, setCaptcha] = useState<{ id: string; image: string } | null>(null);
  const [digits, setDigits] = useState("");

  const newCaptcha = useCallback(async () => {
    setDigits("");
    try {
      const c = await api.captcha();
      setCaptcha(c.enabled ? { id: c.id, image: c.image } : null);
    } catch (err) {
      setCaptcha(null);
      setError(errorText(t, err));
    }
  }, [t]);

  useEffect(() => {
    void newCaptcha();
  }, [newCaptcha]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const res = await api.login(username.trim(), password, captcha ? { id: captcha.id, answer: digits } : undefined);
      setToken(res.access_token);
      setUser(res.user);
    } catch (err) {
      setError(errorText(t, err));
      // A picture is good for one try, right or wrong.
      void newCaptcha();
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
        {captcha && (
          <div className="login-captcha">
            <img src={`data:image/svg+xml;utf8,${encodeURIComponent(captcha.image)}`} alt="" />
            <button type="button" className="login-captcha-new" onClick={() => void newCaptcha()} aria-label={t("login.captchaNew")} title={t("login.captchaNew")}>
              <RefreshCw size={17} />
            </button>
            <label className="login-field">
              <span className="visually-hidden">{t("login.captcha")}</span>
              <input
                className="input"
                inputMode="numeric"
                autoComplete="off"
                maxLength={8}
                placeholder={t("login.captcha")}
                value={digits}
                onChange={(e) => setDigits(e.target.value.replace(/D/g, ""))}
                required
              />
            </label>
          </div>
        )}
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
