import { RotateCw, ScanFace, VideoOff, X } from "lucide-react";
import { type CSSProperties, type DragEvent, useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { Camera, Quality } from "../api/types";
import { intlLocale } from "../i18n";
import { useCameraStream } from "../lib/webrtc";
import { DirectionBadge } from "./DirectionBadge";

interface TileProps {
  camera: Camera;
  quality: Quality;
  onOpen?: () => void;
  /** Wall tiles can be dragged to another cell; the full-screen one cannot. */
  onDragStart?: (e: DragEvent) => void;
  onDragOver?: (e: DragEvent) => void;
  onDragLeave?: () => void;
  onDrop?: (e: DragEvent) => void;
  dropTarget?: boolean;
  /** The big cell of the bento wall. */
  featured?: boolean;
  style?: CSSProperties;
}

/**
 * "Retry" on a dead tile starts the stream from scratch: the tile body is
 * remounted under a new key, which opens a fresh connection.
 */
export function CameraTile(props: TileProps) {
  const [attempt, setAttempt] = useState(0);
  return <TileBody key={attempt} {...props} onRetry={() => setAttempt((a) => a + 1)} />;
}

/** When the stream entered its current state, and a clock that ticks while it waits. */
function useSince(status: string) {
  const [since, setSince] = useState(() => Date.now());
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    setSince(Date.now());
    setNow(Date.now());
    if (status !== "connecting") return;
    const tick = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(tick);
  }, [status]);
  return { since, waited: Math.max(0, Math.round((now - since) / 1000)) };
}

function TileBody({
  camera,
  quality,
  onOpen,
  onDragStart,
  onDragOver,
  onDragLeave,
  onDrop,
  dropTarget,
  featured,
  style,
  onRetry,
}: TileProps & { onRetry: () => void }) {
  const { t } = useTranslation();
  const { videoRef, state } = useCameraStream(camera.id, quality, camera.enabled);
  const status = !camera.enabled ? "disabled" : state;
  const { since, waited } = useSince(status);
  const sinceTime = new Date(since).toLocaleTimeString(intlLocale(), { hour: "2-digit", minute: "2-digit" });

  return (
    <div
      className={`tile${dropTarget ? " drop-target" : ""}${featured ? " featured" : ""}`}
      style={style}
      data-direction={camera.face_recognition ? camera.direction : "none"}
      draggable={Boolean(onDragStart)}
      onDragStart={onDragStart}
      onDragOver={onDragOver}
      onDragLeave={onDragLeave}
      onDrop={onDrop}
      onDoubleClick={onOpen}
      onKeyDown={(e) => e.key === "Enter" && onOpen?.()}
      tabIndex={onOpen ? 0 : undefined}
      title={onOpen ? t("cameras.fullscreenHint") : undefined}
    >
      <video ref={videoRef} autoPlay muted playsInline />
      {status === "connecting" && (
        <div className="tile-state">
          <span className="spinner" aria-hidden />
          <span>
            {t("cameras.connecting")} <span className="num">{t("cameras.seconds", { n: waited })}</span>
          </span>
        </div>
      )}
      {status === "offline" && (
        <div className="tile-state">
          <VideoOff size={20} aria-hidden />
          <span>{t("cameras.offlineSince", { time: sinceTime })}</span>
          <button
            className="btn btn-sm tile-retry"
            onClick={(e) => {
              e.stopPropagation();
              onRetry();
            }}
            onDoubleClick={(e) => e.stopPropagation()}
          >
            <RotateCw size={14} aria-hidden />
            {t("common.retry")}
          </button>
        </div>
      )}
      {status === "disabled" && (
        <div className="tile-state">
          <span>{t("cameras.disabled")}</span>
        </div>
      )}
      {/* The camera's name on a solid scrim, readable on any frame. */}
      <div className="hud">
        <span className="hud-chip">
          {status === "offline" && <span className="dot offline" aria-hidden />}
          <span className="name">{camera.name}</span>
          {camera.face_recognition && <DirectionBadge direction={camera.direction} />}
        </span>
      </div>
      {camera.face_recognition && (
        <span className="hud-chip hud-corner" title={t("cameras.face")}>
          <ScanFace size={15} aria-label={t("cameras.face")} />
        </span>
      )}
    </div>
  );
}

/** Full-screen view of one camera on its main stream. */
export function FullscreenCamera({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const { t } = useTranslation();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return createPortal(
    <div className="fullscreen" role="dialog" aria-label={camera.name}>
      <div className="fill" onDoubleClick={onClose}>
        <CameraTile camera={camera} quality="main" />
      </div>
      <button className="icon-btn close" onClick={onClose} aria-label={t("common.close")}>
        <X size={20} />
      </button>
    </div>,
    document.body,
  );
}
