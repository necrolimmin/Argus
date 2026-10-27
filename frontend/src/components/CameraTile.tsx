import { ScanFace, VideoOff, X } from "lucide-react";
import { useEffect } from "react";
import { createPortal } from "react-dom";
import { useTranslation } from "react-i18next";

import type { Camera, Quality } from "../api/types";
import { useCameraStream } from "../lib/webrtc";
import { DirectionBadge } from "./DirectionBadge";

interface TileProps {
  camera: Camera;
  quality: Quality;
  onOpen?: () => void;
}

export function CameraTile({ camera, quality, onOpen }: TileProps) {
  const { t } = useTranslation();
  const { videoRef, state } = useCameraStream(camera.id, quality, camera.enabled);
  const status = !camera.enabled ? "disabled" : state;

  return (
    <div
      className="tile"
      data-direction={camera.face_recognition ? camera.direction : "none"}
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
      <div className="tile-label">
        <span className="name">{camera.name}</span>
        {camera.face_recognition && <DirectionBadge direction={camera.direction} />}
        {camera.face_recognition && (
          <span className="face-mark" title={t("cameras.face")}>
            <ScanFace size={15} aria-label={t("cameras.face")} />
          </span>
        )}
      </div>
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
