import { useEffect, useRef, useState } from "react";

import { api, getToken } from "../api/client";
import type { Quality } from "../api/types";

export type StreamState = "connecting" | "live" | "offline";
type Transport = "webrtc" | "mse";

/** Close the current attempt; returns nothing. */
type Stop = () => void;

// WebRTC gets this long to show a picture before MSE is tried. go2rtc can
// accept the offer and then send nothing when the codec does not fit.
const WEBRTC_TIMEOUT = 8000;

// Video codecs offered to go2rtc for MSE, H.264 profiles first.
const MSE_CODECS = ["avc1.640029", "avc1.64002A", "avc1.640033", "hvc1.1.6.L153.B0"];

// Which transport worked last time for a camera, so remounting a tile
// (changing the grid, paging) does not repeat a failed WebRTC attempt.
const preferred = new Map<string, Transport>();

function waitForIce(pc: RTCPeerConnection, ms: number): Promise<void> {
  if (pc.iceGatheringState === "complete") return Promise.resolve();
  return new Promise((resolve) => {
    const done = () => {
      pc.removeEventListener("icegatheringstatechange", check);
      clearTimeout(timer);
      resolve();
    };
    const check = () => pc.iceGatheringState === "complete" && done();
    const timer = setTimeout(done, ms);
    pc.addEventListener("icegatheringstatechange", check);
  });
}

/** WebRTC through go2rtc; the SDP exchange goes via the backend for access checks. */
function startWebrtc(cameraId: string, quality: Quality, video: HTMLVideoElement, fail: () => void): Stop {
  let stopped = false;
  const pc = new RTCPeerConnection();
  pc.addTransceiver("video", { direction: "recvonly" });
  pc.ontrack = (e) => {
    video.srcObject = e.streams[0] ?? new MediaStream([e.track]);
  };
  pc.onconnectionstatechange = () => {
    if (!stopped && (pc.connectionState === "failed" || pc.connectionState === "closed")) fail();
  };
  (async () => {
    try {
      await pc.setLocalDescription(await pc.createOffer());
      await waitForIce(pc, 1500);
      const answer = await api.webrtc(cameraId, quality, pc.localDescription!.sdp);
      if (!stopped) await pc.setRemoteDescription({ type: "answer", sdp: answer });
    } catch {
      if (!stopped) fail();
    }
  })();
  return () => {
    stopped = true;
    pc.close();
    video.srcObject = null;
  };
}

/** Fragmented MP4 over WebSocket into Media Source Extensions; plays H.265 too. */
function startMse(cameraId: string, quality: Quality, video: HTMLVideoElement, fail: () => void): Stop {
  const w = window as unknown as { ManagedMediaSource?: typeof MediaSource };
  const MS = w.ManagedMediaSource ?? window.MediaSource;
  if (!MS) {
    fail();
    return () => {};
  }
  const codecs = MSE_CODECS.filter((c) => MS.isTypeSupported(`video/mp4; codecs="${c}"`)).join();
  let stopped = false;
  const ms = new MS();
  let objectUrl = "";
  if (w.ManagedMediaSource && MS === w.ManagedMediaSource) {
    video.disableRemotePlayback = true;
    video.srcObject = ms;
  } else {
    objectUrl = URL.createObjectURL(ms);
    video.src = objectUrl;
  }

  let buffer: SourceBuffer | null = null;
  const queue: ArrayBuffer[] = [];
  const die = () => {
    if (!stopped) fail();
  };

  const pump = () => {
    if (!buffer || buffer.updating) return;
    const chunk = queue.shift();
    if (chunk) {
      try {
        buffer.appendBuffer(chunk);
      } catch {
        die();
      }
      return;
    }
    const ranges = buffer.buffered;
    if (!ranges.length) return;
    const end = ranges.end(ranges.length - 1);
    // Stay at the live edge: surveillance video is useless when it lags.
    if (end - video.currentTime > 2) video.currentTime = end - 0.3;
    const start = ranges.start(0);
    if (video.currentTime - start > 30) buffer.remove(start, video.currentTime - 10);
  };

  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(
    `${proto}://${location.host}/api/cameras/${cameraId}/mse?quality=${quality}&token=${encodeURIComponent(getToken() ?? "")}`,
  );
  ws.binaryType = "arraybuffer";
  ws.onopen = () => ws.send(JSON.stringify({ type: "mse", value: codecs }));
  ws.onmessage = (ev) => {
    if (typeof ev.data !== "string") {
      queue.push(ev.data as ArrayBuffer);
      pump();
      return;
    }
    const msg = JSON.parse(ev.data);
    if (msg.type === "error") return die();
    if (msg.type !== "mse") return;
    const open = () => {
      try {
        buffer = ms.addSourceBuffer(msg.value);
        buffer.mode = "segments";
        buffer.addEventListener("updateend", pump);
        pump();
      } catch {
        die(); // codec not supported by this browser
      }
    };
    if (ms.readyState === "open") open();
    else ms.addEventListener("sourceopen", open, { once: true });
  };
  ws.onclose = die;
  video.play().catch(() => {});

  return () => {
    stopped = true;
    ws.onclose = null;
    ws.close();
    video.removeAttribute("src");
    video.srcObject = null;
    video.load();
    if (objectUrl) URL.revokeObjectURL(objectUrl);
  };
}

const starters: Record<Transport, typeof startWebrtc> = { webrtc: startWebrtc, mse: startMse };

// No new frame for this long means the picture has frozen.
const STALL_MS = 6000;

function decodedFrames(video: HTMLVideoElement): number {
  // currentTime keeps running on a frozen WebRTC stream, so frames are
  // counted instead where the browser supports it.
  return video.getVideoPlaybackQuality?.().totalVideoFrames ?? video.currentTime;
}

/**
 * Plays a camera through go2rtc. Tries WebRTC (lowest delay) and falls back
 * to MSE, which also covers cameras sending H.265. Reconnects on its own.
 */
export function useCameraStream(cameraId: string, quality: Quality, enabled = true) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [state, setState] = useState<StreamState>("connecting");

  useEffect(() => {
    const video = videoRef.current;
    if (!enabled || !video) return;
    let cancelled = false;
    let stop: Stop = () => {};
    let timer: ReturnType<typeof setTimeout> | undefined;
    let watchdog: ReturnType<typeof setInterval> | undefined;
    let failures = 0;
    let live = false;
    const order: Transport[] = preferred.get(cameraId) === "mse" ? ["mse", "webrtc"] : ["webrtc", "mse"];
    let index = 0;

    const attempt = () => {
      if (cancelled) return;
      clearTimeout(timer);
      clearInterval(watchdog);
      stop();
      live = false;
      const transport = order[index % order.length];
      let failed = false;
      // `stalled`: the picture froze after playing, i.e. the camera or the
      // network dropped out. Retry the same transport; only a transport that
      // never showed a picture is swapped for the other one.
      const fail = (stalled = false) => {
        if (failed || cancelled) return;
        failed = true;
        clearInterval(watchdog);
        failures++;
        if (!stalled) index++;
        const roundDone = stalled || index % order.length === 0;
        if (roundDone) setState("offline");
        timer = setTimeout(attempt, roundDone ? Math.min(30_000, 2_000 * 2 ** Math.floor(failures / 2)) : 0);
      };
      setState("connecting");
      stop = starters[transport](cameraId, quality, video, () => fail(live));
      timer = setTimeout(() => !live && fail(), transport === "webrtc" ? WEBRTC_TIMEOUT : 15_000);
      onLive = () => {
        if (live) return;
        live = true;
        failures = 0;
        clearTimeout(timer);
        preferred.set(cameraId, transport);
        setState("live");
        // A dropped camera often leaves the connection open with no frames
        // coming, which looks like a frozen picture. Count decoded frames
        // and reconnect when none arrive for STALL_MS.
        let frames = decodedFrames(video);
        let lastChange = Date.now();
        watchdog = setInterval(() => {
          const now = decodedFrames(video);
          if (now !== frames) {
            frames = now;
            lastChange = Date.now();
          } else if (Date.now() - lastChange > STALL_MS) {
            fail(true);
          }
        }, 1000);
      };
    };

    let onLive = () => {};
    const playing = () => onLive();
    video.addEventListener("playing", playing);
    attempt();

    return () => {
      cancelled = true;
      clearTimeout(timer);
      clearInterval(watchdog);
      video.removeEventListener("playing", playing);
      stop();
    };
  }, [cameraId, quality, enabled]);

  return { videoRef, state };
}
