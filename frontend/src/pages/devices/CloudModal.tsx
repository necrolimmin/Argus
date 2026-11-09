import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AlertTriangle, Cloud, LogIn, Plus, Trash2, Video } from "lucide-react";
import { type FormEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { ApiError, api } from "../../api/client";
import { keys, useUnits } from "../../api/queries";
import type { CloudAccount, CloudDevice, CloudProvider } from "../../api/types";
import { Confirm, Modal } from "../../components/Modal";
import { ErrorState, Skeleton } from "../../components/States";
import { UnitSelect } from "../../components/UnitSelect";
import { codeText, errorText } from "../../lib/errors";
import { useUi } from "../../lib/store";

export function useCloudInfo(enabled = true) {
  return useQuery({ queryKey: ["cloud-info"], queryFn: api.cloudInfo, refetchInterval: 15_000, enabled });
}

const PROVIDERS: CloudProvider[] = ["hik", "ezviz"];

type View = { kind: "accounts" } | { kind: "login"; account?: CloudAccount } | { kind: "pick"; account: CloudAccount };

/**
 * Cameras from Hik-Connect and EZVIZ accounts. Argus logs into the account
 * like the owner's phone app does; the admin then picks which cameras or
 * recorder channels to show. Video comes through the vendor's cloud, so
 * nothing is set up on the camera or the router.
 */
export function CloudModal({ defaultUnitId, onClose }: { defaultUnitId: string | null; onClose: () => void }) {
  const { t } = useTranslation();
  const info = useCloudInfo();
  const accounts = info.data?.accounts;
  const [view, setView] = useState<View | null>(null);

  // No accounts yet: start with the login form.
  const current: View = view ?? (accounts && accounts.length === 0 ? { kind: "login" } : { kind: "accounts" });

  if (current.kind === "login")
    return (
      <LoginView
        account={current.account}
        onBack={accounts?.length ? () => setView({ kind: "accounts" }) : undefined}
        onClose={onClose}
        onDone={(a, fresh) => setView(fresh ? { kind: "pick", account: a } : { kind: "accounts" })}
      />
    );
  if (current.kind === "pick")
    return (
      <PickView
        account={current.account}
        defaultUnitId={defaultUnitId}
        onBack={() => setView({ kind: "accounts" })}
        onClose={onClose}
      />
    );

  return (
    <Modal
      title={t("devices.cloud.title")}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.close")}
          </button>
          <button className="btn btn-primary" onClick={() => setView({ kind: "login" })}>
            <Plus size={16} />
            {t("devices.cloud.addAccount")}
          </button>
        </>
      }
    >
      {info.isLoading && <Skeleton rows={3} />}
      {info.isError && <ErrorState onRetry={() => info.refetch()} />}
      {accounts && (
        <div className="stack">
          <p className="lead">{t("devices.cloud.lead")}</p>
          {!info.data?.bridge && accounts.length > 0 && <p className="notice">{t("devices.cloud.bridgeDown")}</p>}
          <ul className="cloud-accounts">
            {accounts.map((a) => (
              <AccountRow
                key={a.id}
                account={a}
                onPick={() => setView({ kind: "pick", account: a })}
                onLogin={() => setView({ kind: "login", account: a })}
              />
            ))}
          </ul>
        </div>
      )}
    </Modal>
  );
}

function AccountRow({ account: a, onPick, onLogin }: { account: CloudAccount; onPick: () => void; onLogin: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const [confirm, setConfirm] = useState(false);
  const remove = useMutation({
    mutationFn: () => api.cloudDelete(a.id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["cloud-info"] });
      qc.invalidateQueries({ queryKey: keys.devices });
      notify(t("devices.cloud.removed"));
      setConfirm(false);
    },
  });
  // What is wrong with the account, in words, or "" when it works.
  const trouble = a.error ? codeText(t, a.error) : "";
  return (
    <li className={`cloud-account${trouble ? " has-trouble" : ""}`}>
      <span className={`cloud-badge ${a.provider}`}>{t(`devices.cloud.providers.${a.provider}`)}</span>
      <div className="cloud-account-main">
        <strong>{a.name || a.login}</strong>
        <span className="muted">
          {a.name ? `${a.login} · ` : ""}
          {t("devices.cloud.cameraCount", { count: a.cameras })}
        </span>
        {trouble && (
          <span className="cloud-trouble">
            <AlertTriangle size={14} />
            {trouble}
          </span>
        )}
        {a.problems.length > 0 && (
          <ul className="cloud-problems">
            {a.problems.slice(0, 4).map((p) => (
              <li key={p.camera_id}>
                <AlertTriangle size={14} />
                <span>
                  <b>{p.camera_name}</b> — {t(`devices.cloud.states.${p.state}`, { defaultValue: p.state })}
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="cloud-account-actions">
        {trouble ? (
          <button className="btn btn-primary btn-sm" onClick={onLogin}>
            <LogIn size={14} />
            {t("devices.cloud.relogin")}
          </button>
        ) : (
          <button className="btn btn-ghost btn-sm" onClick={onPick}>
            <Video size={14} />
            {t("devices.cloud.pick")}
          </button>
        )}
        <button
          className="icon-btn sm"
          title={t("devices.cloud.remove")}
          aria-label={t("devices.cloud.remove")}
          onClick={() => setConfirm(true)}
        >
          <Trash2 size={14} />
        </button>
      </div>
      {confirm && (
        <Confirm
          text={t("devices.cloud.removeConfirm", { name: a.name || a.login, count: a.cameras })}
          confirmLabel={t("common.delete")}
          onConfirm={() => remove.mutate()}
          onClose={() => setConfirm(false)}
          busy={remove.isPending}
          error={remove.error ? errorText(t, remove.error) : undefined}
        />
      )}
    </li>
  );
}

/** New account, or logging an existing one in again (new password, code, after a lock). */
function LoginView({
  account,
  onBack,
  onClose,
  onDone,
}: {
  account?: CloudAccount;
  onBack?: () => void;
  onClose: () => void;
  onDone: (a: CloudAccount, fresh: boolean) => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const [provider, setProvider] = useState<CloudProvider>(account?.provider ?? "hik");
  const [login, setLogin] = useState(account?.login ?? "");
  const [password, setPassword] = useState("");
  const [name, setName] = useState(account?.name ?? "");
  const [code, setCode] = useState("");
  const [needsCode, setNeedsCode] = useState(false);
  const [error, setError] = useState("");

  const send = useMutation({
    mutationFn: () =>
      account
        ? api.cloudUpdate(account.id, { name: name.trim(), password, code: code.trim() })
        : api.cloudAdd({ provider, login: login.trim(), password, name: name.trim(), code: code.trim() }),
    onSuccess: (a) => {
      qc.invalidateQueries({ queryKey: ["cloud-info"] });
      onDone(a, !account);
    },
    onError: (e) => {
      if (e instanceof ApiError && e.code === "cloud_needs_code") {
        setNeedsCode(true);
        setError("");
        return;
      }
      setError(errorText(t, e));
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    send.mutate();
  };

  return (
    <Modal
      title={account ? t("devices.cloud.reloginTitle") : t("devices.cloud.loginTitle")}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onBack ?? onClose}>
            {onBack ? t("common.back") : t("common.cancel")}
          </button>
          <button className="btn btn-primary" type="submit" form="cloud-login" disabled={send.isPending}>
            {send.isPending ? <span className="spinner" aria-hidden /> : <LogIn size={16} />}
            {t("devices.cloud.signIn")}
          </button>
        </>
      }
    >
      <form id="cloud-login" className="stack" onSubmit={submit}>
        {!account && (
          <>
            <p className="lead">{t("devices.cloud.loginLead")}</p>
            <div className="field">
              <span>{t("devices.cloud.provider")}</span>
              <div className="segmented" role="group">
                {PROVIDERS.map((p) => (
                  <button type="button" key={p} aria-pressed={provider === p} onClick={() => setProvider(p)}>
                    {t(`devices.cloud.providers.${p}`)}
                  </button>
                ))}
              </div>
            </div>
          </>
        )}
        <label className="field">
          <span>{t("devices.cloud.login")}</span>
          <input
            className="input"
            value={login}
            onChange={(e) => setLogin(e.target.value)}
            required
            maxLength={200}
            autoComplete="off"
            disabled={!!account}
            placeholder={t("devices.cloud.loginPlaceholder")}
          />
        </label>
        <label className="field">
          <span>{t("devices.cloud.password")}</span>
          <input
            className="input"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required={!account}
            maxLength={200}
            autoComplete="new-password"
            placeholder={account ? t("devices.cloud.passwordKeep") : undefined}
          />
        </label>
        {needsCode && (
          <label className="field">
            <span>{t("devices.cloud.code")}</span>
            <input
              className="input num"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              required
              maxLength={12}
              inputMode="numeric"
              autoFocus
            />
            <span className="hint">{t("devices.cloud.codeHint")}</span>
          </label>
        )}
        <label className="field">
          <span>{t("devices.cloud.name")}</span>
          <input
            className="input"
            value={name}
            onChange={(e) => setName(e.target.value)}
            maxLength={200}
            placeholder={t("devices.cloud.namePlaceholder")}
          />
        </label>
        {!account && <p className="cloud-privacy">{t("devices.cloud.privacy")}</p>}
        {error && (
          <p className="form-error" role="alert">
            {error}
          </p>
        )}
      </form>
    </Modal>
  );
}

/** The account's devices: tick the cameras or recorder channels to show in Argus. */
function PickView({
  account,
  defaultUnitId,
  onBack,
  onClose,
}: {
  account: CloudAccount;
  defaultUnitId: string | null;
  onBack: () => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const { data: units = [] } = useUnits();
  const list = useQuery({ queryKey: ["cloud-devices", account.id], queryFn: () => api.cloudDevices(account.id) });
  const [unitId, setUnitId] = useState(defaultUnitId ?? "");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  const key = (serial: string, ch: number) => `${serial}:${ch}`;
  const devices = list.data ?? [];
  // Everything not yet in Argus starts ticked (the usual wish is "all of them"),
  // except devices with video encryption on, which would not play.
  const fresh = useMemo(
    () =>
      devices
        .filter((d) => !d.encrypted)
        .flatMap((d) => d.channels.filter((c) => !c.camera_id).map((c) => key(d.serial, c.channel))),
    [devices],
  );
  useEffect(() => {
    if (list.data) setPicked(new Set(fresh));
  }, [list.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const toggle = (k: string) =>
    setPicked((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const toggleDevice = (d: CloudDevice, on: boolean) =>
    setPicked((s) => {
      const n = new Set(s);
      for (const c of d.channels) {
        if (c.camera_id) continue;
        if (on) n.add(key(d.serial, c.channel));
        else n.delete(key(d.serial, c.channel));
      }
      return n;
    });

  const add = useMutation({
    mutationFn: () => {
      const items = devices
        .map((d) => ({ serial: d.serial, channels: d.channels.filter((c) => picked.has(key(d.serial, c.channel))).map((c) => c.channel) }))
        .filter((i) => i.channels.length);
      return api.cloudAddCameras(account.id, { org_unit_id: unitId, items });
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: keys.devices });
      qc.invalidateQueries({ queryKey: ["cloud-info"] });
      notify(t("devices.cloud.added", { count: picked.size }));
      onClose();
    },
    onError: (e) => setError(errorText(t, e)),
  });

  return (
    <Modal
      title={account.name || account.login}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onBack}>
            {t("common.back")}
          </button>
          <button
            className="btn btn-primary"
            onClick={() => add.mutate()}
            disabled={add.isPending || picked.size === 0 || !unitId}
          >
            <Plus size={16} />
            {t("devices.cloud.addPicked", { count: picked.size })}
          </button>
        </>
      }
    >
      {list.isLoading && (
        <div className="stack">
          <p className="lead">
            <Cloud size={16} /> {t("devices.cloud.loading")}
          </p>
          <Skeleton rows={4} />
        </div>
      )}
      {list.isError && <p className="form-error">{errorText(t, list.error)}</p>}
      {list.data && devices.length === 0 && <p className="lead">{t("devices.cloud.noDevices")}</p>}
      {devices.length > 0 && (
        <div className="stack">
          <label className="field">
            <span>{t("devices.cloud.unit")}</span>
            <UnitSelect units={units} value={unitId} onChange={setUnitId} required />
          </label>
          <ul className="cloud-devices scroll-box">
            {devices.map((d) => {
              const open = d.channels.filter((c) => !c.camera_id);
              const all = open.length > 0 && open.every((c) => picked.has(key(d.serial, c.channel)));
              const recorder = d.channels.length > 1;
              return (
                <li key={d.serial} className="cloud-device">
                  <label className="check cloud-device-head">
                    <input
                      type="checkbox"
                      checked={open.length === 0 || all}
                      disabled={open.length === 0}
                      onChange={(e) => toggleDevice(d, e.target.checked)}
                    />
                    <span className="cloud-device-name">
                      <b>{d.name}</b>
                      <span className="muted num">
                        {[d.model, d.serial].filter(Boolean).join(" · ")}
                      </span>
                    </span>
                    <span className={`status-dot ${d.online ? "online" : "offline"}`}>
                      {t(`devices.status.${d.online ? "online" : "offline"}`)}
                    </span>
                  </label>
                  {d.encrypted && (
                    <p className="cloud-warn">
                      <AlertTriangle size={14} />
                      {t("devices.cloud.encrypted")}
                    </p>
                  )}
                  {recorder && (
                    <ul className="cloud-channels">
                      {d.channels.map((c) => (
                        <li key={c.channel}>
                          <label className="check">
                            <input
                              type="checkbox"
                              checked={!!c.camera_id || picked.has(key(d.serial, c.channel))}
                              disabled={!!c.camera_id}
                              onChange={() => toggle(key(d.serial, c.channel))}
                            />
                            <span>
                              <span className="num muted">{c.channel}</span> {c.name || `CH${c.channel}`}
                            </span>
                            {c.camera_id && <span className="muted">{t("devices.cloud.already")}</span>}
                          </label>
                        </li>
                      ))}
                    </ul>
                  )}
                  {!recorder && d.channels[0]?.camera_id && <span className="muted cloud-already">{t("devices.cloud.already")}</span>}
                </li>
              );
            })}
          </ul>
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
        </div>
      )}
    </Modal>
  );
}
