import { useMutation } from "@tanstack/react-query";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { Modal } from "../components/Modal";
import { errorText } from "../lib/errors";
import { useUi } from "../lib/store";

export function PasswordModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const notify = useUi((s) => s.notify);
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState("");

  const change = useMutation({
    mutationFn: () => api.changePassword(current, next),
    onSuccess: () => {
      notify(t("password.changed"));
      onClose();
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    change.mutate();
  };

  return (
    <Modal
      title={t("password.title")}
      onClose={onClose}
      narrow
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn btn-primary" type="submit" form="password-form" disabled={change.isPending}>
            {t("common.save")}
          </button>
        </>
      }
    >
      <form id="password-form" className="form-grid" onSubmit={submit}>
        <label className="field wide">
          <span>{t("password.current")}</span>
          <input className="input" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} required />
        </label>
        <label className="field wide">
          <span>{t("password.next")}</span>
          <input className="input" type="password" autoComplete="new-password" minLength={6} value={next} onChange={(e) => setNext(e.target.value)} required />
        </label>
        {error && <p className="form-error" role="alert">{error}</p>}
      </form>
    </Modal>
  );
}
