import { ScanFace, VideoOff, X } from "lucide-react";
import { type CSSProperties, type DragEvent, useEffect } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { Camera, Quality } from "../api/types";
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

export function CameraTile({
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
}: TileProps) {
  const { t } = useTranslation();
  const { videoRef, state } = useCameraStream(camera.id, quality, camera.enabled);
  const status = !camera.enabled ? "disabled" : state;

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
      {status !== "live" && (
        <div className="tile-state">
          {status === "connecting" ? <span className="pulse" /> : <VideoOff size={22} />}
          <span>{t(`cameras.${status === "disabled" ? "disabled" : status}`)}</span>
        </div>
      )}
      {/* Glass chips over the picture: they stay readable on any frame. */}
      <div className="hud">
        <span className="hud-chip">
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
      <div onDoubleClick={onClose} style={{ position: "absolute", inset: 0 }}>
        <CameraTile camera={camera} quality="main" />
      </div>
      <button className="icon-btn close" onClick={onClose} aria-label={t("common.close")}>
        <X size={20} />
      </button>
    </div>,
    document.body,
  );
}
