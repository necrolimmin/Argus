import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Download, FileSpreadsheet, ImageOff } from "lucide-react";
import { type DragEvent, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { api } from "../../api/client";
import { keys } from "../../api/queries";
import type { EmployeeImportRow } from "../../api/types";
import { Modal } from "../../components/Modal";
import { codeText, errorText } from "../../lib/errors";

const ACCEPT = ".xlsx,.csv,.zip";

/**
 * Employees from a filled-in template. The steps are a real sequence: get the
 * template, fill it, upload it; then a preview with each row's photos, so a
 * picture that landed in the wrong row is seen before anything is saved.
 */
export function EmployeeImportModal({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [preview, setPreview] = useState<{ token: string; rows: EmployeeImportRow[] } | null>(null);
  const [started, setStarted] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [error, setError] = useState("");

  const read = useMutation({
    mutationFn: (file: File) => api.employeeImportPreview(file),
    onSuccess: (r) => {
      setPreview(r);
      setError("");
    },
    onError: (e) => setError(errorText(t, e)),
  });

  const start = useMutation({
    mutationFn: () => api.employeeImportStart(preview!.token),
    onSuccess: () => setStarted(true),
    onError: (e) => setError(errorText(t, e)),
  });

  const progress = useQuery({
    queryKey: ["employee-import", preview?.token],
    queryFn: () => api.employeeImportProgress(preview!.token),
    enabled: started,
    refetchInterval: (q) => (q.state.data?.finished ? false : 1000),
  });
  const job = progress.data ?? start.data;
  const finished = !!job?.finished;

  useEffect(() => {
    if (finished) qc.invalidateQueries({ queryKey: keys.employees });
  }, [finished, qc]);

  const close = () => {
    // A preview that was never imported leaves its photos on the server; drop them.
    if (preview && !started) api.employeeImportCancel(preview.token).catch(() => {});
    onClose();
  };

  const choose = (file: File | undefined) => {
    if (!file) return;
    if (preview && !started) api.employeeImportCancel(preview.token).catch(() => {});
    setPreview(null);
    read.mutate(file);
  };

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    choose(e.dataTransfer.files[0]);
  };

  const downloadTemplate = async () => {
    try {
      const url = URL.createObjectURL(await api.employeeImportTemplate());
      const a = document.createElement("a");
      a.href = url;
      a.download = "argus-employees.xlsx";
      a.click();
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(errorText(t, e));
    }
  };

  const rows = preview?.rows ?? [];
  const good = rows.filter((r) => !r.errors.length);
  const fresh = good.filter((r) => r.action === "create").length;
  const photos = good.reduce((n, r) => n + r.photos.length, 0);

  let footer;
  if (finished || started) {
    footer = (
      <button className="btn btn-primary" onClick={onClose} disabled={!finished}>
        {t("common.close")}
      </button>
    );
  } else {
    footer = (
      <>
        <button className="btn btn-ghost" onClick={close}>
          {t("common.cancel")}
        </button>
        {preview && (
          <button className="btn btn-primary" onClick={() => start.mutate()} disabled={!good.length || start.isPending}>
            {t("org.importer.run", { count: good.length })}
          </button>
        )}
      </>
    );
  }

  return (
    <Modal title={t("org.importer.title")} onClose={started && !finished ? () => {} : close} wide footer={footer}>
      {!started && !preview && (
        <ol className="import-steps">
          <li>
            <strong>{t("org.importer.step1")}</strong>
            <span>{t("org.importer.step1Hint")}</span>
            <button className="btn btn-sm" onClick={downloadTemplate}>
              <Download size={14} />
              {t("org.importer.template")}
            </button>
          </li>
          <li>
            <strong>{t("org.importer.step2")}</strong>
            <span>{t("org.importer.step2Hint")}</span>
          </li>
          <li>
            <strong>{t("org.importer.step3")}</strong>
            <span>{t("org.importer.step3Hint")}</span>
          </li>
        </ol>
      )}

      {!started && (
        <div
          className={`drop-zone${dragging ? " over" : ""}${preview ? " compact" : ""}`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <FileSpreadsheet size={preview ? 18 : 28} aria-hidden />
          <span>{read.isPending ? t("org.importer.reading") : t("org.importer.drop")}</span>
          <button className="btn" onClick={() => fileRef.current?.click()} disabled={read.isPending}>
            {preview ? t("org.importer.another") : t("org.importer.choose")}
          </button>
          <input
            ref={fileRef}
            type="file"
            accept={ACCEPT}
            hidden
            onChange={(e) => {
              choose(e.target.files?.[0]);
              e.target.value = "";
            }}
          />
        </div>
      )}
      {error && (
        <p className="form-error" role="alert">
          {error}
        </p>
      )}

      {preview && !started && (
        <>
          <div className="import-summary">
            <span className="badge">{t("org.importer.rowsNew", { count: fresh })}</span>
            {good.length > fresh && <span className="badge">{t("org.importer.rowsUpdate", { count: good.length - fresh })}</span>}
            <span className="badge">{t("org.importer.photos", { count: photos })}</span>
            {rows.length > good.length && (
              <span className="badge danger">{t("org.importer.rowsBad", { count: rows.length - good.length })}</span>
            )}
          </div>
          <div className="table-wrap scroll-box">
            <table className="table import-table">
              <thead>
                <tr>
                  <th className="num">{t("org.importer.colRow")}</th>
                  <th>{t("org.importer.colPhotos")}</th>
                  <th>{t("org.importer.colName")}</th>
                  <th>{t("org.importer.colNumber")}</th>
                  <th>{t("org.importer.colUnit")}</th>
                  <th>{t("org.importer.colNote")}</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.row} className={r.errors.length ? "row-bad" : undefined}>
                    <td className="num muted">{r.row}</td>
                    <td>
                      <span className="import-faces">
                        {r.photos.length ? (
                          r.photos.map((p) => <img key={p.path} src={p.url} alt="" loading="lazy" />)
                        ) : (
                          <span className="import-noface" title={t("org.noPhotoHint")}>
                            <ImageOff size={14} aria-hidden />
                          </span>
                        )}
                      </span>
                    </td>
                    <td>
                      {r.full_name || <span className="muted">—</span>}
                      {r.position && <div className="muted text-sm">{r.position}</div>}
                    </td>
                    <td className="num">{r.personnel_number}</td>
                    <td className="muted">{r.org_path}</td>
                    <td className="text-sm">
                      {r.errors.length > 0 && (
                        <span className="form-error">
                          {r.errors.map((e) => t(`org.importer.problems.${e}`, { defaultValue: e })).join(", ")}
                        </span>
                      )}
                      {!r.errors.length && (
                        <span className={`badge${r.action === "update" ? " warn" : ""}`}>
                          {t(r.action === "update" ? "org.importer.actionUpdate" : "org.importer.actionNew")}
                        </span>
                      )}
                      {r.warnings.length > 0 && (
                        <div className="muted">
                          {r.warnings.map((w) => t(`org.importer.warnings.${w}`, { defaultValue: w })).join(", ")}
                        </div>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}

      {started && job && !finished && (
        <div className="import-progress" role="status">
          <strong>{t("org.importer.running", { done: job.done, total: job.total })}</strong>
          <span className="meter">
            <i style={{ width: `${job.total ? (job.done / job.total) * 100 : 0}%` }} />
          </span>
          <span className="muted text-sm">{t("org.importer.runningHint")}</span>
        </div>
      )}

      {job && finished && (
        <div className="import-done">
          <CheckCircle2 size={28} aria-hidden className="ok" />
          <strong>{t("org.importer.done")}</strong>
          <span>{t("org.importer.summary", { created: job.created, updated: job.updated, photos: job.photos })}</span>
          {job.skipped_rows.length > 0 && (
            <span className="muted">{t("org.importer.skipped", { rows: job.skipped_rows.join(", ") })}</span>
          )}
          {job.photo_problems.length > 0 && (
            <div className="import-problems">
              <strong>{t("org.importer.rejected")}</strong>
              <ul>
                {job.photo_problems.map((p, i) => (
                  <li key={i}>
                    <span className="num muted">{p.row}</span> {p.full_name}: {codeText(t, p.code)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
}
