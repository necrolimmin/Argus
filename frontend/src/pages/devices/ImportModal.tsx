import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Download, FileUp } from "lucide-react";
import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { keys } from "../../api/queries";
import type { ImportRow } from "../../api/types";
import { Modal } from "../../components/Modal";
import { errorText } from "../../lib/errors";
import { useUi } from "../../lib/store";

export function ImportModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const notify = useUi((s) => s.notify);
  const fileRef = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<ImportRow[] | null>(null);
  const [error, setError] = useState("");

  const preview = useMutation({
    mutationFn: (file: File) => api.importPreview(file),
    onSuccess: (r) => {
      setRows(r);
      setError("");
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const run = useMutation({
    mutationFn: () => api.importDevices(rows!.filter((r) => !r.errors.length)),
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: keys.devices });
      qc.invalidateQueries({ queryKey: keys.allCameras });
      qc.invalidateQueries({ queryKey: keys.units });
      notify(t("devices.importer.done", { devices: res.devices, cameras: res.cameras }));
      onClose();
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const downloadTemplate = async () => {
    try {
      const blob = await api.importTemplate();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "argus-cameras.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorText(t, e));
    }
  };

  const good = rows?.filter((r) => !r.errors.length) ?? [];
  const bad = rows?.filter((r) => r.errors.length) ?? [];

  return (
    <Modal
      title={t("devices.importer.title")}
      onClose={onClose}
      wide
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>
            {t("common.cancel")}
          </button>
          <button className="btn btn-primary" onClick={() => run.mutate()} disabled={!good.length || run.isPending}>
            {t("devices.importer.run")}
          </button>
        </>
      }
    >
      <p className="lead">
        {t("devices.importer.hint")}
      </p>
      <div className="row wrap">
        <button className="btn" onClick={downloadTemplate}>
          <Download size={16} />
          {t("devices.importer.template")}
        </button>
        <button className="btn" onClick={() => fileRef.current?.click()} disabled={preview.isPending}>
          <FileUp size={16} />
          {t("devices.importer.choose")}
        </button>
        <input
          ref={fileRef}
          type="file"
          accept=".xlsx,.csv"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) preview.mutate(file);
            e.target.value = "";
          }}
        />
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}

      {rows && (
        <div className="stack mt-4">
          <div>
            <strong>{t("devices.importer.rowsOk", { count: good.length })}</strong>
            {bad.length > 0 && <div className="form-error">{t("devices.importer.rowsBad", { count: bad.length })}</div>}
          </div>
          <div className="table-wrap scroll-box">
            <table className="table">
              <thead>
                <tr>
                  <th>{t("devices.importer.colRow")}</th>
                  <th>{t("devices.colName")}</th>
                  <th>{t("devices.vendor")}</th>
                  <th>{t("devices.colAddress")}</th>
                  <th>{t("devices.colUnit")}</th>
                  <th>{t("devices.importer.colProblem")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.row} className={r.errors.length ? "row-bad" : undefined} style={{ cursor: "default" }}>
                    <td className="num muted">{r.row}</td>
                    <td>{r.name}</td>
                    <td>{r.vendor}</td>
                    <td className="num">
                      {r.host}
                      {r.channel > 1 ? ` #${r.channel}` : ""}
                    </td>
                    <td className="muted">{r.org_path}</td>
                    <td className="form-error text-sm">
                      {r.errors.map((e) => t(`devices.importer.problems.${e}`, { defaultValue: e })).join(", ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </Modal>
  );
}
