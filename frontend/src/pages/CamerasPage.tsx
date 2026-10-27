import { ChevronLeft, ChevronRight, ScanFace, Search, SquareDashed } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCameras, useUnits } from "../api/queries";
import type { Camera } from "../api/types";
import { CameraTile, FullscreenCamera } from "../components/CameraTile";
import { DirectionBadge } from "../components/DirectionBadge";
import { EventsDock } from "../components/EventsDock";
import { OrgTree } from "../components/OrgTree";
import { type Layout, useWall } from "../lib/store";

const LAYOUTS: Layout[] = [1, 4, 9, 16];

function GridIcon({ n }: { n: number }) {
  const side = Math.sqrt(n);
  return (
    <span className="grid-icon" style={{ gridTemplateColumns: `repeat(${side}, 1fr)` }} aria-hidden>
      {Array.from({ length: n }, (_, i) => (
        <i key={i} />
      ))}
    </span>
  );
}

export function CamerasPage() {
  const { t } = useTranslation();
  const wall = useWall();
  const { data: units = [] } = useUnits();
  const unitList = useCameras(wall.unitId, wall.unitId !== null);
  const all = useCameras(null);
  const [query, setQuery] = useState("");
  const [fullscreen, setFullscreen] = useState<Camera | null>(null);

  const unitNames = useMemo(() => new Map(units.map((u) => [u.id, u.name])), [units]);
  const byId = useMemo(() => new Map((all.data ?? []).map((c) => [c.id, c])), [all.data]);

  // Forget cameras that were deleted or are no longer visible to this user.
  useEffect(() => {
    if (!all.data) return;
    const valid = wall.cameraIds.filter((id) => byId.has(id));
    if (valid.length !== wall.cameraIds.length) wall.setCameras(valid);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [all.data]);

  // Forget a remembered unit that no longer exists.
  useEffect(() => {
    if (units.length && wall.unitId && !unitNames.has(wall.unitId)) wall.setUnit(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [units]);

  const listed = useMemo(() => {
    const q = query.trim().toLowerCase();
    const cams = unitList.data ?? [];
    return q ? cams.filter((c) => c.name.toLowerCase().includes(q)) : cams;
  }, [unitList.data, query]);

  const selected = wall.cameraIds.map((id) => byId.get(id)).filter((c): c is Camera => !!c);
  const pages = Math.max(1, Math.ceil(selected.length / wall.layout));
  const page = Math.min(wall.page, pages - 1);
  const onScreen = selected.slice(page * wall.layout, (page + 1) * wall.layout);
  const faceIds = selected.filter((c) => c.face_recognition).map((c) => c.id);

  const allListedSelected = listed.length > 0 && listed.every((c) => wall.cameraIds.includes(c.id));
  const toggleAll = () => {
    const ids = new Set(wall.cameraIds);
    if (allListedSelected) listed.forEach((c) => ids.delete(c.id));
    else listed.forEach((c) => ids.add(c.id));
    wall.setCameras([...ids]);
  };

  return (
    <div className="wall-page">
      <aside className="aside">
        <section className="aside-section">
          <div className="aside-head">
            <h2>{t("cameras.structure")}</h2>
          </div>
          <div className="aside-scroll">
            <OrgTree units={units} selectedId={wall.unitId} onSelect={wall.setUnit} count="camera_count" />
          </div>
        </section>

        <section className="aside-section">
          <div className="aside-head">
            <h2>{t("cameras.list")}</h2>
            <span className="spacer" />
            {listed.length > 0 && (
              <button className="btn btn-ghost btn-sm" onClick={toggleAll}>
                {allListedSelected ? t("cameras.clear") : t("cameras.selectAll")}
              </button>
            )}
          </div>
          {wall.unitId === null ? (
            <p className="aside-note">{t("cameras.pickUnit")}</p>
          ) : (
            <>
              {(unitList.data?.length ?? 0) > 8 && (
                <div className="search" style={{ padding: "0 14px 8px" }}>
                  <Search size={15} style={{ left: 24 }} />
                  <input className="input" placeholder={t("common.search")} value={query} onChange={(e) => setQuery(e.target.value)} />
                </div>
              )}
              <div className="aside-scroll">
                {unitList.isSuccess && unitList.data.length === 0 && (
                  <p className="aside-note" style={{ padding: "4px 6px" }}>
                    {t("cameras.noCameras")} {t("cameras.addCamerasHint")}
                  </p>
                )}
                {listed.map((c) => (
                  <label key={c.id} className="cam-item">
                    <input type="checkbox" checked={wall.cameraIds.includes(c.id)} onChange={() => wall.toggleCamera(c.id)} />
                    <span className="cam-item-text">
                      <span className="cam-item-name">{c.name}</span>
                      <span className="cam-item-unit">{unitNames.get(c.org_unit_id)}</span>
                    </span>
                    {c.face_recognition &&
                      (c.direction === "none" ? (
                        <ScanFace size={15} className="muted" aria-label={t("cameras.face")} />
                      ) : (
                        <DirectionBadge direction={c.direction} />
                      ))}
                  </label>
                ))}
              </div>
            </>
          )}
        </section>
      </aside>

      <section className="wall">
        <div className="wall-toolbar">
          <span className="muted">{t("cameras.selected", { count: selected.length })}</span>
          <span className="spacer" />
          {pages > 1 && (
            <div className="pager">
              <button className="icon-btn sm" onClick={() => wall.setPage(page - 1)} disabled={page === 0} aria-label="‹">
                <ChevronLeft size={16} />
              </button>
              <span className="num">{t("cameras.page", { page: page + 1, pages })}</span>
              <button className="icon-btn sm" onClick={() => wall.setPage(page + 1)} disabled={page >= pages - 1} aria-label="›">
                <ChevronRight size={16} />
              </button>
            </div>
          )}
          <div className="segmented" role="group" aria-label={t("cameras.layout")}>
            {LAYOUTS.map((n) => (
              <button key={n} aria-pressed={wall.layout === n} onClick={() => wall.setLayout(n)} title={`${Math.sqrt(n)}×${Math.sqrt(n)}`}>
                <GridIcon n={n} />
              </button>
            ))}
          </div>
        </div>

        <div className="wall-body">
          {selected.length === 0 ? (
            <div className="empty center">
              <SquareDashed size={40} strokeWidth={1.4} />
              <span>{t("cameras.nothingSelected")}</span>
            </div>
          ) : (
            <div className="grid" data-layout={wall.layout}>
              {onScreen.map((c) => (
                <CameraTile key={c.id} camera={c} quality={wall.layout === 1 ? "main" : "sub"} onOpen={() => setFullscreen(c)} />
              ))}
              {wall.layout > 1 &&
                Array.from({ length: wall.layout - onScreen.length }, (_, i) => <div key={`empty-${i}`} className="tile empty-slot" />)}
            </div>
          )}
        </div>

        {faceIds.length > 0 && <EventsDock cameraIds={faceIds} defaultUnitId={wall.unitId} />}
      </section>

      {fullscreen && <FullscreenCamera camera={fullscreen} onClose={() => setFullscreen(null)} />}
    </div>
  );
}
