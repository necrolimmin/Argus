import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { type FormEvent, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Navigate } from "react-router-dom";

import { api } from "../api/client";
import { keys, useUnits } from "../api/queries";
import type { Role, User } from "../api/types";
import { Confirm, Modal } from "../components/Modal";
import { UnitSelect } from "../components/UnitSelect";
import { errorText } from "../lib/errors";
import { isAdmin, useAuth, useUi } from "../lib/store";
import { unitPath } from "../lib/tree";

export function UsersPage() {
  const { t } = useTranslation();
  const me = useAuth((s) => s.user);
  const qc = useQueryClient();
  const { data: units = [] } = useUnits();
  const { data: users = [] } = useQuery({ queryKey: keys.users, queryFn: api.users, enabled: isAdmin(me) });
  const [editing, setEditing] = useState<User | "new" | null>(null);
  const [deleting, setDeleting] = useState<User | null>(null);

  const remove = useMutation({
    mutationFn: (id: string) => api.deleteUser(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.users });
      setDeleting(null);
    },
  });

  if (!isAdmin(me)) return <Navigate to="/cameras" replace />;

  return (
    <div className="page">
      <div className="page-head">
        <h1>{t("users.title")}</h1>
        <span className="spacer" />
        <button className="btn btn-primary" onClick={() => setEditing("new")}>
          <Plus size={16} />
          {t("users.add")}
        </button>
      </div>
      <div className="card">
        <div className="table-wrap card-body" style={{ paddingTop: 8 }}>
          <table className="table">
            <thead>
              <tr>
                <th>{t("users.username")}</th>
                <th>{t("users.fullName")}</th>
                <th>{t("users.role")}</th>
                <th>{t("users.unit")}</th>
                <th>{t("org.status")}</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} onClick={() => setEditing(u)}>
                  <td>{u.username}</td>
                  <td>{u.full_name}</td>
                  <td>{t(`users.roles.${u.role}`)}</td>
                  <td className="muted">{u.org_unit_id ? unitPath(units, u.org_unit_id) : ""}</td>
                  <td>
                    <span className={`status${u.is_active ? "" : " off"}`}>{u.is_active ? t("common.yes") : t("common.no")}</span>
                  </td>
                  <td className="actions">
                    {u.id !== me?.id && (
                      <button
                        className="icon-btn sm"
                        onClick={(e) => {
                          e.stopPropagation();
                          setDeleting(u);
                        }}
                        aria-label={t("common.delete")}
                      >
                        <Trash2 size={15} />
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {editing && <UserModal user={editing === "new" ? undefined : editing} onClose={() => setEditing(null)} />}
      {deleting && (
        <Confirm
          text={t("users.deleteConfirm", { name: deleting.username })}
          confirmLabel={t("common.delete")}
          onConfirm={() => remove.mutate(deleting.id)}
          onClose={() => setDeleting(null)}
          busy={remove.isPending}
          error={remove.error ? errorText(t, remove.error) : undefined}
        />
      )}
    </div>
  );
}

function UserModal({ user, onClose }: { user?: User; onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const { data: units = [] } = useUnits();
  const [username, setUsername] = useState(user?.username ?? "");
  const [fullName, setFullName] = useState(user?.full_name ?? "");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<Role>(user?.role ?? "operator");
  const [unitId, setUnitId] = useState(user?.org_unit_id ?? "");
  const [active, setActive] = useState(user?.is_active ?? true);
  const [error, setError] = useState("");
  const hint = useMemo(() => t(`users.roleHint.${role}`), [t, role]);

  const save = useMutation({
    mutationFn: () => {
      const org_unit_id = role === "operator" ? unitId || null : null;
      if (user) {
        return api.updateUser(user.id, {
          full_name: fullName,
          role,
          org_unit_id,
          is_active: active,
          ...(password ? { password } : {}),
        });
      }
      return api.createUser({ username: username.trim(), full_name: fullName, password, role, org_unit_id });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.users });
      notify(t("users.saved"));
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
      title={user ? user.username : t("users.add")}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn btn-primary" type="submit" form="user-form" disabled={save.isPending}>
            {t("common.save")}
          </button>
        </>
      }
    >
      <form id="user-form" className="form-grid" onSubmit={submit}>
        <label className="field">
          <span>{t("users.username")}</span>
          <input
            className="input"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={!!user}
            required
            minLength={3}
            pattern="[A-Za-z0-9_.\-]+"
            autoComplete="off"
          />
        </label>
        <label className="field">
          <span>{t("users.fullName")}</span>
          <input className="input" value={fullName} onChange={(e) => setFullName(e.target.value)} maxLength={200} />
        </label>
        <label className="field wide">
          <span>{t("users.password")}</span>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required={!user}
            minLength={6}
            autoComplete="new-password"
          />
          {user && <span className="hint">{t("users.passwordKeep")}</span>}
        </label>
        <div className="field wide">
          <span>{t("users.role")}</span>
          <div className="segmented" role="group">
            {(["operator", "admin"] as Role[]).map((r) => (
              <button type="button" key={r} aria-pressed={role === r} onClick={() => setRole(r)}>
                {t(`users.roles.${r}`)}
              </button>
            ))}
          </div>
          <span className="hint">{hint}</span>
        </div>
        {role === "operator" && (
          <label className="field wide">
            <span>{t("users.unit")}</span>
            <UnitSelect units={units} value={unitId} onChange={setUnitId} required />
          </label>
        )}
        {user && (
          <label className="check wide">
            <input type="checkbox" checked={active} onChange={(e) => setActive(e.target.checked)} />
            <span>{t("users.active")}</span>
          </label>
        )}
        {error && <p className="form-error" role="alert">{error}</p>}
      </form>
    </Modal>
  );
}
