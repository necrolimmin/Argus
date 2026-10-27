import logging
import threading
import time

import numpy as np

log = logging.getLogger(__name__)


class CameraReader(threading.Thread):
    """Decodes one RTSP stream and offers frames at the current sample rate.

    Only the newest due frame is kept: if inference falls behind, stale
    frames are dropped instead of queueing up and adding delay.
    """

    def __init__(self, camera_id: str, url: str, wake: threading.Event):
        super().__init__(name=f"cam-{camera_id[:8]}", daemon=True)
        self.camera_id = camera_id
        self.url = url
        self.fps = 1.0
        self._wake = wake
        self._halt = threading.Event()
        self._lock = threading.Lock()
        self._pending: tuple[np.ndarray, float] | None = None
        self.connected = False

    def stop(self) -> None:
        self._halt.set()

    def take(self) -> tuple[np.ndarray, float] | None:
        with self._lock:
            item, self._pending = self._pending, None
        return item

    def run(self) -> None:
        backoff = 2.0
        while not self._halt.is_set():
            try:
                self._read()
                backoff = 2.0
            except Exception as exc:  # noqa: BLE001
                log.warning("camera %s: %s", self.camera_id, exc)
            self.connected = False
            if self._halt.wait(backoff):
                break
            backoff = min(backoff * 2, 30.0)

    def _read(self) -> None:
        import av

        options = {"rtsp_transport": "tcp", "timeout": "5000000", "fflags": "nobuffer"}
        with av.open(self.url, options=options, timeout=10) as container:
            stream = container.streams.video[0]
            stream.thread_type = "AUTO"
            self.connected = True
            log.info("camera %s connected", self.camera_id)
            next_at = 0.0
            for frame in container.decode(stream):
                if self._halt.is_set():
                    return
                now = time.time()
                if now < next_at:
                    continue
                next_at = now + 1.0 / max(self.fps, 0.1)
                image = frame.to_ndarray(format="bgr24")
                with self._lock:
                    self._pending = (image, now)
                self._wake.set()
