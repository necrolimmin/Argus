import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCameras, useUnits } from "../api/queries";
import type { Camera } from "../api/types";
import { unitPath } from "../lib/tree";
import { ChannelTag } from "./CameraTile";

/** A checkbox that also shows "some of these", for a group of items. */
export function GroupCheck({ state, onChange, label }: { state: "all" | "some" | "none"; onChange: () => void; label: string }) {
  const ref = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = state === "some";
  }, [state]);
  return <input ref={ref} type="checkbox" checked={state === "all"} onChange={onChange} aria-label={label} title={label} />;
}

/**
 * The cameras a viewer (or the holder of an API key) may watch, grouped by unit as they are in the
 * structure, so "everything at the warehouse" is one tick.
 */
export function CameraAccess({
  value,
  onChange,
  emptyHint,
}: {
  value: string[];
  onChange: (ids: string[]) => void;
  /** What an empty choice means here; by default, what it means for a viewer. */
  emptyHint?: string;
}) {
  const { t } = useTranslation();
  const { data: cameras = [], isSuccess } = useCameras(null);
  const { data: units = [] } = useUnits();
  const [query, setQuery] = useState("");
  const chosen = useMemo(() => new Set(value), [value]);
  const recorders = useMemo(() => {
    const count = new Map<string, number>();
    for (const c of cameras) count.set(c.device_id, (count.get(c.device_id) ?? 0) + 1);
    return new Set([...count].filter(([, n]) => n > 1).map(([id]) => id));
  }, [cameras]);

  const groups = useMemo(() => {
    const q = query.trim().toLowerCase();
    const byUnit = new Map<string, Camera[]>();
    for (const c of cameras) {
      const path = unitPath(units, c.org_unit_id);
      if (q && !`${c.name} ${path}`.toLowerCase().includes(q)) continue;
      byUnit.set(c.org_unit_id, [...(byUnit.get(c.org_unit_id) ?? []), c]);
    }
    return [...byUnit.entries()]
      .map(([unitId, cams]) => ({ unitId, path: unitPath(units, unitId), cams }))
      .sort((a, b) => a.path.localeCompare(b.path));
  }, [cameras, units, query]);

  const toggle = (ids: string[], on: boolean) => {
    const next = new Set(chosen);
    for (const id of ids) {
      if (on) next.add(id);
      else next.delete(id);
    }
    onChange([...next]);
  };

  if (isSuccess && cameras.length === 0) return <p className="hint">{t("users.camerasEmpty")}</p>;

  return (
    <div className="access">
      <div className="access-head">
        <div className="search">
          <Search size={15} />
          <input className="input" placeholder={t("common.search")} value={query} onChange={(e) => setQuery(e.target.value)} />
        </div>
        <span className={`access-count num${value.length ? "" : " none"}`}>{t("users.camerasPicked", { count: value.length })}</span>
      </div>
      <div className="access-list">
        {groups.map((g) => {
          const ids = g.cams.map((c) => c.id);
          const picked = ids.filter((id) => chosen.has(id)).length;
          const state = picked === 0 ? "none" : picked === ids.length ? "all" : "some";
          return (
            <section key={g.unitId} className="access-group">
              <label className="access-unit">
                <GroupCheck state={state} onChange={() => toggle(ids, state !== "all")} label={t("users.pickGroup")} />
                <span className="access-path">{g.path}</span>
                <span className="num muted">
                  {picked}/{ids.length}
                </span>
              </label>
              {g.cams.map((c) => (
                <label key={c.id} className={`access-cam${chosen.has(c.id) ? " on" : ""}`}>
                  <input type="checkbox" checked={chosen.has(c.id)} onChange={(e) => toggle([c.id], e.target.checked)} />
                  {recorders.has(c.device_id) && <ChannelTag channel={c.channel} />}
                  <span>{c.name}</span>
                </label>
              ))}
            </section>
          );
        })}
      </div>
      {value.length === 0 && <span className="hint">{emptyHint ?? t("users.camerasNone")}</span>}
    </div>
  );
}
