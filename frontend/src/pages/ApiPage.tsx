import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Clock, ExternalLink, FileBarChart, FileSpreadsheet, KeyRound, Pencil, Plus, Trash2 } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../api/client";
import { keys } from "../api/queries";
import type { ApiKey, ApiKeyCreated } from "../api/types";
import { CameraAccess } from "../components/CameraAccess";
import { CopyLine } from "../components/CopyButton";
import { Confirm, Modal } from "../components/Modal";
import { RowActions } from "../components/RowActions";
import { EmptyState, ErrorState, Skeleton } from "../components/States";
import { intlLocale } from "../i18n";
import { errorText } from "../lib/errors";
import { isAdmin, useAuth, useUi } from "../lib/store";

// Stage three (attendance, reports) is not built yet: listed as inactive
// items, with no buttons and no numbers that would pretend it works.
const UPCOMING = [
  { icon: Clock, title: "api.timesheet", text: "api.timesheetText" },
  { icon: FileBarChart, title: "api.reports", text: "api.reportsText" },
  { icon: FileSpreadsheet, title: "api.excel", text: "api.excelText" },
] as const;

function when(iso: string) {
  // The server keeps UTC; SQLite (a developer machine) drops the zone mark.
  const utc = /[zZ]$|[+-][0-9]{2}:?[0-9]{2}$/.test(iso) ? iso : `${iso}Z`;
  return new Date(utc).toLocaleString(intlLocale(), { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

/**
 * Keys for other systems: an administrator ticks cameras, gets a key, and
 * the other project shows those cameras through Argus.
 */
export function ApiPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const admin = isAdmin(useAuth((s) => s.user));
  const list = useQuery({ queryKey: keys.apiKeys, queryFn: api.apiKeys, enabled: admin });
  const [editing, setEditing] = useState<ApiKey | "new" | null>(null);
  const [created, setCreated] = useState<ApiKeyCreated | null>(null);
  const [revoking, setRevoking] = useState<ApiKey | null>(null);
  const items = list.data ?? [];
  const headers = [t("api.keyName"), t("api.key"), t("api.cameras"), t("api.created"), t("api.lastUsed")];

  const revoke = useMutation({
    mutationFn: (id: string) => api.deleteApiKey(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.apiKeys });
      setRevoking(null);
    },
  });

  return (
    <div className="page">
      <div className="page-head">
        <div className="page-title">
          <h1>{t("api.title")}</h1>
          <p className="page-lead">{t("api.keysLead")}</p>
        </div>
        <span className="spacer" />
        {admin && (
          <button className="btn btn-primary" onClick={() => setEditing("new")}>
            <Plus size={16} />
            {t("api.newKey")}
          </button>
        )}
      </div>

      <div className="api-page">
        {admin ? (
          <section className="card" aria-label={t("api.keys")}>
            {list.isPending ? (
              <Skeleton rows={2} columns={[140, 110, 60, 110, 110]} headers={headers} />
            ) : list.isError && list.data === undefined ? (
              <ErrorState title={t("api.loadFailed")} lastOk={list.dataUpdatedAt} onRetry={() => list.refetch()} retrying={list.isFetching} />
            ) : items.length === 0 ? (
              <EmptyState
                icon={KeyRound}
                title={t("api.empty")}
                text={t("api.emptyText")}
                action={
                  <button className="btn btn-sm" onClick={() => setEditing("new")}>
                    <Plus size={14} aria-hidden />
                    {t("api.newKey")}
                  </button>
                }
              />
            ) : (
              <div className="table-wrap">
                <table className="table keys-table">
                  <thead>
                    <tr>
                      {headers.map((h) => (
                        <th key={h}>{h}</th>
                      ))}
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((k) => (
                      <tr key={k.id} onClick={() => setEditing(k)}>
                        <td className="key-name" title={k.name}>
                          {k.name}
                        </td>
                        <td className="num muted">{k.prefix}…</td>
                        <td className="num">{k.camera_ids.length}</td>
                        <td className="num muted">{when(k.created_at)}</td>
                        <td className={k.last_used_at ? "num" : "muted"}>{k.last_used_at ? when(k.last_used_at) : t("api.neverUsed")}</td>
                        <td className="actions">
                          <RowActions
                            actions={[
                              { icon: Pencil, label: t("common.edit"), onClick: () => setEditing(k) },
                              { icon: Trash2, label: t("api.revoke"), danger: true, onClick: () => setRevoking(k) },
                            ]}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>
        ) : (
          <p className="notice">{t("api.adminOnly")}</p>
        )}

        <Guide />

        <section className="card upcoming" aria-labelledby="upcoming-title">
          <h2 id="upcoming-title" className="upcoming-title">
            {t("api.upcoming")}
          </h2>
          <ul className="upcoming-list">
            {UPCOMING.map(({ icon: Icon, title, text }) => (
              <li key={title} className="upcoming-item" aria-disabled="true">
                <Icon size={18} aria-hidden className="upcoming-icon" />
                <div className="upcoming-text">
                  <span className="upcoming-name">{t(title)}</span>
                  <span className="upcoming-desc">{t(text)}</span>
                </div>
                <span className="badge">{t("api.inProgress")}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      {editing && (
        <KeyModal
          apiKey={editing === "new" ? undefined : editing}
          onClose={() => setEditing(null)}
          onCreated={(k) => {
            setEditing(null);
            setCreated(k);
          }}
        />
      )}
      {created && <CreatedModal apiKey={created} onClose={() => setCreated(null)} />}
      {revoking && (
        <Confirm
          text={t("api.revokeConfirm", { name: revoking.name })}
          confirmLabel={t("api.revoke")}
          onConfirm={() => revoke.mutate(revoking.id)}
          onClose={() => setRevoking(null)}
          busy={revoke.isPending}
          error={revoke.error ? errorText(t, revoke.error) : undefined}
        />
      )}
    </div>
  );
}

/** The four requests another system needs, with this server's address filled in. */
function Guide() {
  const { t } = useTranslation();
  const origin = window.location.origin;
  const key = t("api.keyWord");
  return (
    <section className="card api-guide" aria-labelledby="guide-title">
      <h2 id="guide-title">{t("api.guide")}</h2>
      <ol className="guide-steps">
        <li>
          <p>{t("api.step1")}</p>
          <CopyLine text={origin} />
        </li>
        <li>
          <p>{t("api.step2")}</p>
          <CopyLine text={`curl -H "X-Api-Key: ${key}" ${origin}/api/ext/cameras`} />
        </li>
        <li>
          <p>{t("api.step3")}</p>
          <CopyLine text={`<iframe src="${origin}/embed/ID?key=${key}" allow="autoplay; fullscreen"></iframe>`} />
        </li>
        <li>
          <p>{t("api.step4")}</p>
          <CopyLine text={`${origin}/api/ext/cameras/ID/snapshot?key=${key}`} />
        </li>
      </ol>
      <div className="guide-safe">
        <h3>{t("api.safeTitle")}</h3>
        <p>{t("api.safeText")}</p>
        <CopyLine text={`curl -X POST -H "X-Api-Key: ${key}" "${origin}/api/ext/cameras/ID/link?seconds=3600"`} />
      </div>
      <p className="guide-foot">
        {t("api.hidden")}{" "}
        <a href="/api/docs#/external" target="_blank" rel="noreferrer">
          {t("api.docs")}
          <ExternalLink size={13} aria-hidden />
        </a>
      </p>
    </section>
  );
}

function KeyModal({ apiKey, onClose, onCreated }: { apiKey?: ApiKey; onClose: () => void; onCreated: (k: ApiKeyCreated) => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const [name, setName] = useState(apiKey?.name ?? "");
  const [cameraIds, setCameraIds] = useState<string[]>(apiKey?.camera_ids ?? []);
  const [error, setError] = useState("");

  const save = useMutation({
    mutationFn: async () => {
      const body = { name: name.trim(), camera_ids: cameraIds };
      if (apiKey) {
        await api.updateApiKey(apiKey.id, body);
        return null;
      }
      return api.createApiKey(body);
    },
    onSuccess: (made) => {
      qc.invalidateQueries({ queryKey: keys.apiKeys });
      if (made) return onCreated(made);
      notify(t("api.saved"));
      onClose();
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    save.mutate();
  };

  return (
    <Modal
      title={apiKey ? t("api.editTitle", { name: apiKey.name }) : t("api.newKey")}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn btn-primary" type="submit" form="key-form" disabled={save.isPending}>
            {apiKey ? t("common.save") : t("api.newKey")}
          </button>
        </>
      }
    >
      <form id="key-form" className="stack" onSubmit={submit}>
        <label className="field">
          <span>{t("api.keyName")}</span>
          <input className="input" value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoComplete="off" />
          <span className="hint">{apiKey ? t("api.editHint") : t("api.keyNameHint")}</span>
        </label>
        <div className="field">
          <span>{t("api.camerasFor")}</span>
          <CameraAccess value={cameraIds} onChange={setCameraIds} emptyHint={t("api.camerasNone")} />
        </div>
        {error && <p className="form-error m-0">{error}</p>}
      </form>
    </Modal>
  );
}

/** The key, once. After this dialog only its first characters are known. */
function CreatedModal({ apiKey, onClose }: { apiKey: ApiKeyCreated; onClose: () => void }) {
  const { t } = useTranslation();
  return (
    <Modal
      title={t("api.createdTitle")}
      onClose={onClose}
      footer={
        <button className="btn btn-primary" onClick={onClose}>
          {t("api.done")}
        </button>
      }
    >
      <div className="stack">
        <p className="notice">{t("api.createdNote")}</p>
        <div className="field">
          <span>{t("api.server")}</span>
          <CopyLine text={window.location.origin} />
        </div>
        <div className="field">
          <span>{t("api.key")}</span>
          <CopyLine text={apiKey.key} />
        </div>
      </div>
    </Modal>
  );
}
