import { ChevronLeft, ChevronRight, ScanFace, Search, SquareDashed } from "lucide-react";
import { type DragEvent, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { useCameras, useUnits } from "../api/queries";
import type { Camera } from "../api/types";
import { CameraTile, FullscreenCamera } from "../components/CameraTile";
import { DirectionBadge } from "../components/DirectionBadge";
import { EventsDock } from "../components/EventsDock";
import { OrgTree } from "../components/OrgTree";
import { type Layout, useWall } from "../lib/store";
import { AUTO_MAX, bento, bentoCells, compact, place, swap } from "../lib/wall";

const LAYOUTS: Exclude<Layout, "auto">[] = [1, 4, 9, 16];
// What is being dragged onto a cell: another cell, or a camera from the list.
const SLOT = "application/x-argus-slot";
const CAMERA = "application/x-argus-camera";

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
  const [dropTarget, setDropTarget] = useState<number | null>(null);

  const unitNames = useMemo(() => new Map(units.map((u) => [u.id, u.name])), [units]);
  const byId = useMemo(() => new Map((all.data ?? []).map((c) => [c.id, c])), [all.data]);

  // Forget cameras that were deleted or are no longer visible to this user.
  useEffect(() => {
    if (!all.data) return;
    if (wall.cameraIds.some((id) => id !== null && !byId.has(id)))
      wall.setSlots(wall.cameraIds.map((id) => (id !== null && byId.has(id) ? id : null)));
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

  const selected = compact(wall.cameraIds).map((id) => byId.get(id)).filter((c): c is Camera => !!c);
  const faceIds = selected.filter((c) => c.face_recognition).map((c) => c.id);

  // Automatic mode packs the cameras and sizes the grid to their number;
  // a fixed grid keeps each camera in the cell it was put in, gaps included.
  const auto = wall.layout === "auto";
  const slots = auto ? compact(wall.cameraIds) : wall.cameraIds;
  // Automatic mode is a bento: the first camera is featured large and the
  // others sit around it. Drag a camera onto the big cell to feature it.
  const layoutAuto = bento(Math.min(Math.max(slots.length, 1), AUTO_MAX));
  const perPage = wall.layout === "auto" ? bentoCells(layoutAuto) : wall.layout;
  const grid = auto ? layoutAuto : { cols: Math.sqrt(perPage), rows: Math.sqrt(perPage), feature: { cols: 1, rows: 1 } };
  const featured = grid.feature.cols * grid.feature.rows > 1;
  const cellCount = perPage;
  const pages = Math.max(1, Math.ceil(slots.length / perPage));
  const page = Math.min(wall.page, pages - 1);
  const first = page * perPage;
  const cells = Array.from({ length: cellCount }, (_, i) => {
    const id = i < perPage ? slots[first + i] : null;
    return id ? byId.get(id) ?? null : null;
  });

  // Never a second page while everything fits on the first: gaps that would
  // push cameras over are dropped.
  useEffect(() => {
    if (slots.length > perPage && selected.length <= perPage) wall.setSlots(compact(wall.cameraIds));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [slots.length, perPage, selected.length]);

  const allListedSelected = listed.length > 0 && listed.every((c) => wall.cameraIds.includes(c.id));
  const toggleAll = () => {
    const ids = listed.map((c) => c.id);
    if (allListedSelected) wall.removeCameras(ids);
    else wall.addCameras(ids);
  };

  const acceptsDrop = (e: DragEvent) => e.dataTransfer.types.includes(SLOT) || e.dataTransfer.types.includes(CAMERA);
  const dropOn = (index: number) => ({
    onDragOver: (e: DragEvent) => {
      if (!acceptsDrop(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      setDropTarget(index);
    },
    onDragLeave: () => setDropTarget((t) => (t === index ? null : t)),
    onDrop: (e: DragEvent) => {
      e.preventDefault();
      setDropTarget(null);
      const target = first + index;
      const from = e.dataTransfer.getData(SLOT);
      const camera = e.dataTransfer.getData(CAMERA);
      if (from !== "") wall.setSlots(swap(slots, Number(from), target));
      else if (camera) wall.setSlots(place(slots, camera, target));
    },
  });

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
                <div className="search aside-search">
                  <Search size={15} />
                  <input className="input" placeholder={t("common.search")} value={query} onChange={(e) => setQuery(e.target.value)} />
                </div>
              )}
              <div className="aside-scroll">
                {unitList.isSuccess && unitList.data.length === 0 && (
                  <p className="aside-note tight">
                    {t("cameras.noCameras")} {t("cameras.addCamerasHint")}
                  </p>
                )}
                {listed.map((c) => (
                  <label
                    key={c.id}
                    className="cam-item"
                    draggable
                    onDragStart={(e) => {
                      e.dataTransfer.setData(CAMERA, c.id);
                      e.dataTransfer.effectAllowed = "move";
                    }}
                  >
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
          <h1>{t("nav.cameras")}</h1>
          {wall.unitId && <span className="scope">{unitNames.get(wall.unitId)}</span>}
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
            <button aria-pressed={auto} onClick={() => wall.setLayout("auto")} title={t("cameras.autoHint")}>
              {t("cameras.auto")}
            </button>
            {LAYOUTS.map((n) => (
              <button key={n} aria-pressed={wall.layout === n} onClick={() => wall.setLayout(n)} title={`${Math.sqrt(n)}×${Math.sqrt(n)}`}>
                <GridIcon n={n} />
              </button>
            ))}
          </div>
        </div>

        <div className="wall-body">
          {selected.length === 0 ? (
            <div className={`empty center${dropTarget === 0 ? " drop-target" : ""}`} {...dropOn(0)}>
              <SquareDashed size={40} strokeWidth={1.4} />
              <span>{t("cameras.nothingSelected")}</span>
            </div>
          ) : (
            <div
              className="grid"
              style={{
                gridTemplateColumns: `repeat(${grid.cols}, minmax(0, 1fr))`,
                gridTemplateRows: `repeat(${grid.rows}, minmax(0, 1fr))`,
              }}
            >
              {cells.map((c, i) =>
                c ? (
                  <CameraTile
                    key={c.id}
                    camera={c}
                    quality={cellCount === 1 || (featured && i === 0) ? "main" : "sub"}
                    featured={featured && i === 0}
                    style={featured && i === 0 ? { gridColumn: `span ${grid.feature.cols}`, gridRow: `span ${grid.feature.rows}` } : undefined}
                    onOpen={() => setFullscreen(c)}
                    dropTarget={dropTarget === i}
                    onDragStart={(e) => {
                      e.dataTransfer.setData(SLOT, String(first + i));
                      e.dataTransfer.effectAllowed = "move";
                    }}
                    {...dropOn(i)}
                  />
                ) : (
                  <div
                    key={`empty-${i}`}
                    className={`tile empty-slot${dropTarget === i ? " drop-target" : ""}`}
                    style={featured && i === 0 ? { gridColumn: `span ${grid.feature.cols}`, gridRow: `span ${grid.feature.rows}` } : undefined}
                    {...dropOn(i)}
                  />
                ),
              )}
            </div>
          )}
        </div>

        {faceIds.length > 0 && <EventsDock cameraIds={faceIds} defaultUnitId={wall.unitId} />}
      </section>

      {fullscreen && <FullscreenCamera camera={fullscreen} onClose={() => setFullscreen(null)} />}
    </div>
  );
}
