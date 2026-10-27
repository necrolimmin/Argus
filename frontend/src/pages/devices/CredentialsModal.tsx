import { useMutation, useQueryClient } from "@tanstack/react-query";
import { KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { keys, useCredentials } from "../../api/queries";
import type { CredentialProfile } from "../../api/types";
import { Modal } from "../../components/Modal";
import { errorText } from "../../lib/errors";
import { useUi } from "../../lib/store";

/** Saved logins: list, add, edit, delete. */
export function CredentialsModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const { data: profiles = [], isSuccess } = useCredentials();
  const [editing, setEditing] = useState<CredentialProfile | "new" | null>(null);
  const [form, setForm] = useState({ name: "", username: "admin", password: "" });
  const [error, setError] = useState("");

  const open = (p: CredentialProfile | "new") => {
    setEditing(p);
    setError("");
    setForm(p === "new" ? { name: "", username: "admin", password: "" } : { name: p.name, username: p.username, password: "" });
  };

  const refresh = () => {
    qc.invalidateQueries({ queryKey: keys.credentials });
    qc.invalidateQueries({ queryKey: keys.devices });
  };

  const save = useMutation({
    mutationFn: () => api.saveCredential(editing === "new" ? null : editing!.id, form),
    onSuccess: () => {
      refresh();
      notify(t("devices.creds.saved"));
      setEditing(null);
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteCredential(id),
    onSuccess: refresh,
    onError: (e) => setError(errorText(t, e)),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  return (
    <Modal title={t("devices.creds.title")} onClose={onClose}>
      <p className="muted" style={{ marginTop: 0, fontSize: "var(--fs-sm)" }}>
        {t("devices.creds.hint")}
      </p>

      {editing ? (
        <form className="form-grid" onSubmit={submit}>
          <label className="field wide">
            <span>{t("devices.creds.name")}</span>
            <input className="input" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder={t("devices.creds.namePlaceholder")} required maxLength={200} />
          </label>
          <label className="field">
            <span>{t("devices.username")}</span>
            <input className="input" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoComplete="off" />
          </label>
          <label className="field">
            <span>{t("devices.password")}</span>
            <input className="input" type="password" value={form.password} autoComplete="new-password"
              onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder={editing === "new" ? "" : "••••••"} />
            {editing !== "new" && <span className="hint">{t("devices.passwordKeep")}</span>}
          </label>
          {error && <p className="form-error" role="alert">{error}</p>}
          <div className="wide" style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button type="button" className="btn btn-ghost" onClick={() => setEditing(null)}>
              {t("common.cancel")}
            </button>
            <button type="submit" className="btn btn-primary" disabled={save.isPending}>
              {t("common.save")}
            </button>
          </div>
        </form>
      ) : (
        <>
          {isSuccess && profiles.length === 0 && (
            <div className="empty" style={{ padding: "8px 0 16px" }}>
              <KeyRound size={30} strokeWidth={1.4} />
              <span>{t("devices.creds.empty")}</span>
            </div>
          )}
          <div className="cred-list">
            {profiles.map((p) => (
              <div key={p.id} className="cred-row">
                <div>
                  <div>{p.name}</div>
                  <div className="muted" style={{ fontSize: "var(--fs-sm)" }}>
                    {p.username}, {t("devices.creds.used", { count: p.device_count })}
                  </div>
                </div>
                <button className="icon-btn sm" onClick={() => open(p)} aria-label={t("common.edit")}>
                  <Pencil size={14} />
                </button>
                <button
                  className="icon-btn sm"
                  onClick={() => window.confirm(t("devices.creds.deleteConfirm", { name: p.name })) && remove.mutate(p.id)}
                  aria-label={t("common.delete")}
                >
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
          {error && <p className="form-error" role="alert">{error}</p>}
          <button className="btn btn-sm" style={{ marginTop: 12 }} onClick={() => open("new")}>
            <Plus size={15} />
            {t("devices.creds.add")}
          </button>
        </>
      )}
    </Modal>
  );
}
