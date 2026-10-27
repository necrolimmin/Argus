import { useMutation, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, Radar, TriangleAlert } from "lucide-react";
import { type FormEvent, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { keys, useUnits } from "../../api/queries";
import type { BulkResult, Found, Vendor } from "../../api/types";
import { CredentialPicker, type CredentialValue } from "../../components/CredentialPicker";
import { Modal } from "../../components/Modal";
import { UnitSelect } from "../../components/UnitSelect";
import { codeText, errorText } from "../../lib/errors";
import { VENDORS, vendorFromScan } from "../../lib/vendors";

interface Props {
  defaultUnitId: string | null;
  onAddOne: (found: Found, vendor: Vendor) => void;
  onClose: () => void;
}

export function ScanModal({ defaultUnitId, onAddOne, onClose }: Props) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const { data: units = [] } = useUnits();
  const [ranges, setRanges] = useState("");
  const [found, setFound] = useState<Found[] | null>(null);
  const [vendors, setVendors] = useState<Record<string, Vendor>>({});
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [step, setStep] = useState<"scan" | "bulk" | "done">("scan");
  const [cred, setCred] = useState<CredentialValue>({ credential_id: null, username: "admin", password: "" });
  const [unitId, setUnitId] = useState(defaultUnitId ?? "");
  const [results, setResults] = useState<BulkResult[]>([]);
  const [error, setError] = useState("");

  const merge = (list: Found[]) => {
    setFound((prev) => {
      const byIp = new Map((prev ?? []).map((f) => [f.ip, f]));
      for (const f of list) byIp.set(f.ip, { ...byIp.get(f.ip), ...f });
      return [...byIp.values()].sort((a, b) =>
        a.ip.localeCompare(b.ip, undefined, { numeric: true }),
      );
    });
    setVendors((v) => ({ ...Object.fromEntries(list.map((f) => [f.ip, vendorFromScan(f.vendor)])), ...v }));
  };

  const run = useMutation({
    mutationFn: (kind: "auto" | "range") =>
      kind === "auto"
        ? api.scanDiscover()
        : // Sent as typed; the server understands spaces, dashes and lists.
          api.scanRange([ranges]),
    onSuccess: (list) => {
      setError("");
      merge(list);
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const selectable = (f: Found) => !f.device_id && f.activated !== false;
  const toggle = (ip: string) =>
    setSelected((s) => {
      const next = new Set(s);
      if (next.has(ip)) next.delete(ip);
      else next.add(ip);
      return next;
    });

  const bulk = useMutation({
    mutationFn: () =>
      api.bulkCreate({
        targets: (found ?? [])
          .filter((f) => selected.has(f.ip))
          .map((f) => ({
            vendor: vendors[f.ip],
            host: f.ip,
            rtsp_port: f.rtsp_port ?? undefined,
            http_port: f.http_port ?? undefined,
            name: f.name || undefined,
          })),
        org_unit_id: unitId,
        ...cred,
      }),
    onSuccess: (res) => {
      setResults(res);
      setStep("done");
      qc.invalidateQueries({ queryKey: keys.devices });
      qc.invalidateQueries({ queryKey: keys.allCameras });
      qc.invalidateQueries({ queryKey: keys.units });
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const submitBulk = (e: FormEvent) => {
    e.preventDefault();
    bulk.mutate();
  };

  if (step === "bulk" || step === "done") {
    return (
      <Modal
        title={t("devices.scan.bulkTitle", { count: selected.size })}
        onClose={onClose}
        footer={
          step === "done" ? (
            <button className="btn btn-primary" onClick={onClose}>
              {t("devices.scan.done")}
            </button>
          ) : (
            <>
              <button className="btn btn-ghost" onClick={() => setStep("scan")}>
                {t("common.cancel")}
              </button>
              <button className="btn btn-primary" type="submit" form="bulk-form" disabled={!unitId || bulk.isPending}>
                {bulk.isPending ? t("devices.scan.adding") : t("common.add")}
              </button>
            </>
          )
        }
      >
        {step === "bulk" ? (
          <form id="bulk-form" className="form-grid" onSubmit={submitBulk}>
            <p className="muted wide" style={{ margin: 0, fontSize: "var(--fs-sm)" }}>
              {t("devices.scan.bulkHint")}
            </p>
            <label className="field wide">
              <span>{t("devices.deviceUnit")}</span>
              <UnitSelect units={units} value={unitId} onChange={setUnitId} required />
            </label>
            <CredentialPicker value={cred} onChange={setCred} />
            {error && <p className="form-error" role="alert">{error}</p>}
          </form>
        ) : (
          <div className="bulk-results">
            <strong>{t("devices.scan.results")}</strong>
            {results.map((r) => (
              <div key={r.host} className={`bulk-line${r.ok ? "" : " bad"}`}>
                {r.ok ? <CircleCheck size={16} /> : <TriangleAlert size={16} />}
                <span className="num">{r.host}</span>
                <span className="muted">{r.ok ? t("devices.scan.okLine", { count: r.cameras }) : codeText(t, r.error)}</span>
              </div>
            ))}
          </div>
        )}
      </Modal>
    );
  }

  return (
    <Modal
      title={t("devices.scan.title")}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.close")}
          </button>
          <button className="btn btn-primary" disabled={!selected.size} onClick={() => setStep("bulk")}>
            {t("devices.scan.addSelected", { count: selected.size })}
          </button>
        </>
      }
    >
      <div className="scan-modes">
        <section>
          <strong>{t("devices.scan.auto")}</strong>
          <p className="muted">{t("devices.scan.autoHint")}</p>
          <button className="btn" onClick={() => run.mutate("auto")} disabled={run.isPending}>
            <Radar size={16} />
            {t("devices.scan.start")}
          </button>
        </section>
        <section>
          <strong>{t("devices.scan.range")}</strong>
          <p className="muted">{t("devices.scan.rangeHint")}</p>
          <form
            style={{ display: "flex", gap: 8 }}
            onSubmit={(e) => {
              e.preventDefault();
              run.mutate("range");
            }}
          >
            <input className="input num" value={ranges} onChange={(e) => setRanges(e.target.value)} placeholder="192.168.3.0/24" required />
            <button className="btn" type="submit" disabled={run.isPending}>
              {t("devices.scan.start")}
            </button>
          </form>
        </section>
      </div>

      {run.isPending && (
        <p className="scan-progress">
          <span className="pulse" />
          {t("devices.scan.scanning")}
        </p>
      )}
      {error && <p className="form-error" role="alert">{error}</p>}

      {found && !run.isPending && (
        <>
          <p className="muted" style={{ margin: "16px 0 8px" }}>
            {found.length ? t("devices.scan.found", { count: found.length }) : t("devices.scan.nothing")}
          </p>
          {found.length > 0 && (
            <div className="table-wrap">
              <table className="table scan-table">
                <thead>
                  <tr>
                    <th>
                      <input
                        type="checkbox"
                        aria-label={t("devices.selectAll")}
                        checked={found.filter(selectable).length > 0 && found.filter(selectable).every((f) => selected.has(f.ip))}
                        onChange={(e) =>
                          setSelected(new Set(e.target.checked ? found.filter(selectable).map((f) => f.ip) : []))
                        }
                      />
                    </th>
                    <th>{t("devices.scan.colIp")}</th>
                    <th>{t("devices.vendor")}</th>
                    <th>{t("devices.colModel")}</th>
                    <th>{t("devices.scan.colMac")}</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {found.map((f) => (
                    <tr key={f.ip} className={selectable(f) ? undefined : "dim"} onClick={() => selectable(f) && toggle(f.ip)}>
                      <td onClick={(e) => e.stopPropagation()}>
                        <input type="checkbox" checked={selected.has(f.ip)} disabled={!selectable(f)} onChange={() => toggle(f.ip)} aria-label={f.ip} />
                      </td>
                      <td className="num">{f.ip}</td>
                      <td onClick={(e) => e.stopPropagation()}>
                        <select
                          className="select select-sm"
                          value={vendors[f.ip]}
                          onChange={(e) => setVendors((v) => ({ ...v, [f.ip]: e.target.value as Vendor }))}
                          disabled={!selectable(f)}
                        >
                          {VENDORS.filter((v) => !v.url).map((v) => (
                            <option key={v.id} value={v.id}>
                              {t(`devices.vendors.${v.id}`)}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>{f.model || f.name}</td>
                      <td className="num muted">{f.mac}</td>
                      <td className="actions" onClick={(e) => e.stopPropagation()}>
                        {f.device_id ? (
                          <span className="muted">{t("devices.scan.already", { name: f.device_name })}</span>
                        ) : f.activated === false ? (
                          <span className="badge warn" title={t("devices.scan.notActivatedHint")}>
                            {t("devices.scan.notActivated")}
                          </span>
                        ) : (
                          <button className="btn btn-ghost btn-sm" onClick={() => onAddOne(f, vendors[f.ip])}>
                            {t("devices.add")}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Modal>
  );
}
