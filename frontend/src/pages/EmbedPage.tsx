import { KeyRound } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";

import { api, ApiError } from "../api/client";
import type { Camera, Quality } from "../api/types";
import { CameraTile } from "../components/CameraTile";
import { LANGUAGES, setLanguage } from "../i18n";
import { setExternalAccess } from "../lib/webrtc";

/**
 * One camera filling the window, for another site's <iframe>:
 *   /embed/<camera id>?key=<API key>      or      ?t=<link token>
 * Optional: quality=main|sub (sub by default), lang=ru|en|uz-Cyrl|uz-Latn,
 * title=<the camera's name on the other site, shown instead of its name in Argus>.
 * Nothing of Argus itself is reachable from here.
 */
export function EmbedPage() {
  const { t } = useTranslation();
  const { id, access, quality, title } = useMemo(() => {
    const params = new URLSearchParams(window.location.search);
    const key = params.get("key");
    const token = params.get("t");
    const lang = LANGUAGES.find((l) => l.code === params.get("lang"));
    if (lang) setLanguage(lang.code);
    const access = key ? `key=${encodeURIComponent(key)}` : token ? `t=${encodeURIComponent(token)}` : "";
    setExternalAccess(access);
    return {
      id: window.location.pathname.split("/")[2] ?? "",
      access,
      quality: (params.get("quality") === "main" ? "main" : "sub") as Quality,
      title: (params.get("title") ?? "").trim().slice(0, 200),
    };
  }, []);
  const [camera, setCamera] = useState<Camera | null>(null);
  const [problem, setProblem] = useState<"denied" | "missing" | "unreachable" | null>(access ? null : "denied");

  useEffect(() => {
    if (!access) return;
    let stale = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const load = () => {
      api
        .extCamera(id, access)
        .then((cam) => {
          if (stale) return;
          setProblem(null);
          // The tile needs a camera as the wall knows it; the rest stays empty.
          setCamera({ id: cam.id, name: title || cam.name, enabled: cam.enabled, face_recognition: false, direction: "none", channel: 1 } as Camera);
        })
        .catch((err) => {
          if (stale) return;
          const status = err instanceof ApiError ? err.status : 0;
          setProblem(status === 401 ? "denied" : status === 404 || status === 422 ? "missing" : "unreachable");
          // The server may be restarting; a wrong key will not fix itself.
          if (status !== 401 && status !== 404 && status !== 422) retry = setTimeout(load, 10_000);
        });
    };
    load();
    return () => {
      stale = true;
      clearTimeout(retry);
    };
  }, [id, access, title]);

  return (
    <div className="embed">
      {camera && !problem ? (
        <CameraTile camera={camera} quality={quality} />
      ) : (
        <div className="embed-note" role={problem ? "alert" : "status"}>
          {problem ? (
            <>
              <KeyRound size={20} aria-hidden />
              <span>{t(`embed.${problem}`)}</span>
            </>
          ) : (
            <span className="spinner" aria-hidden />
          )}
        </div>
      )}
    </div>
  );
}
