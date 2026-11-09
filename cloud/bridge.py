"""cloud-bridge: video of Hik-Connect / EZVIZ cameras, from the cloud into go2rtc.

The backend keeps the accounts' sessions and decides which streams are
needed; this service only moves video:

    cloud relay (VTM) --TCP--> bridge --Annex-B--> ffmpeg -c copy --RTSP--> go2rtc

For each wanted stream it asks the account's servers where the camera's
relay is, gets a stream ticket, opens the relay connection (protocol from
pyEzvizApi, Apache-2.0), unwraps the video (media.py) and pipes it to
ffmpeg, which publishes it into go2rtc under the camera's stream name. No
transcoding: the CPU cost is copying bytes.

HTTP API (header X-Bridge-Token: API_TOKEN):
  GET /health
  GET /state     {"accounts_set", "streams": {target: {...}}, "expired": [account ids]}
  PUT /accounts  {"<account id>": {provider, api, session_id, feature_code, auth_addr}}
  PUT /want      [{target, account, serial, channel, sub}]
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import socket
import subprocess
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests
from pyezvizapi.stream import VtmStreamClient, build_vtm_url

from media import Probe, PsDemux, RtpDepay, is_keyframe_start

API_PORT = int(os.environ.get("API_PORT", "8092"))
API_TOKEN = os.environ.get("API_TOKEN", "")
RTSP_BASE = os.environ.get("RTSP_BASE", "rtsp://go2rtc:8554").rstrip("/")
FFMPEG = os.environ.get("FFMPEG", "ffmpeg")

DOMAIN_RE = re.compile(
    r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.(ezvizlife\.com|ezviz\.com|ezvizru\.com|hik-connect\.com|hik-connectru\.com)\Z"
)
CLIENT_TYPE = {"hik": "55", "ezviz": "1"}
SESSION_CODES = {401, 1001, 1002, 1003, 1004}  # the cloud no longer accepts the session

RESOURCES_TTL = 600
TICKETS_TTL = 300
READ_TIMEOUT = 15  # no video for this long: the stream is dead
QUEUE_BYTES = 8 * 1024 * 1024

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("cloud-bridge")


class StreamError(Exception):
    """state: offline | encrypted | failed | session"""

    def __init__(self, state: str, detail: str = ""):
        super().__init__(detail or state)
        self.state = state


# --- accounts: where cameras are, stream tickets -----------------------------------


class Account:
    def __init__(self, aid: str, d: dict):
        self.id = aid
        self.provider = d.get("provider", "ezviz")
        self.api = str(d.get("api", ""))
        self.session_id = str(d.get("session_id", ""))
        self.feature_code = str(d.get("feature_code", ""))
        self.auth_addr = str(d.get("auth_addr", ""))
        self.lock = threading.Lock()
        self._resources: tuple[float, list, dict] | None = None
        self._tickets: tuple[float, list] | None = None
        self._ticket_n = 0

    def same(self, d: dict) -> bool:
        return (self.session_id, self.api, self.auth_addr) == (d.get("session_id"), d.get("api"), d.get("auth_addr"))

    def _headers(self) -> dict:
        return {"clientType": CLIENT_TYPE.get(self.provider, "1"), "customNo": "1000001",
                "clientVersion": "5.12.1.0517", "lang": "en-US", "featureCode": self.feature_code,
                "sessionId": self.session_id, "User-Agent": "okhttp/3.12.1"}

    def _get(self, url: str, params: dict) -> dict:
        try:
            r = requests.get(url, params=params, headers=self._headers(), timeout=20)
        except requests.RequestException as exc:
            raise StreamError("failed", f"cloud unreachable: {exc}") from exc
        if r.status_code == 401:
            raise StreamError("session")
        try:
            data = r.json()
        except ValueError as exc:
            raise StreamError("failed", f"cloud answered HTTP {r.status_code}") from exc
        return data if isinstance(data, dict) else {}

    def resources(self, fresh: bool = False) -> tuple[list, dict]:
        """The account's cameras/channels and the relay servers for them (cached)."""
        with self.lock:
            if not fresh and self._resources and time.monotonic() - self._resources[0] < RESOURCES_TTL:
                return self._resources[1], self._resources[2]
            if not DOMAIN_RE.match(self.api):
                raise StreamError("failed", f"bad api domain {self.api!r}")
            items, vtm, offset = [], {}, 0
            for _ in range(40):
                data = self._get(f"https://{self.api}/v3/userdevices/v1/resources/pagelist",
                                 {"filter": "VTM", "groupId": -1, "limit": 50, "offset": offset})
                code = (data.get("meta") or {}).get("code")
                if code in SESSION_CODES:
                    raise StreamError("session")
                if code != 200:
                    raise StreamError("failed", f"device list: {data.get('meta')}")
                page = data.get("resourceInfos") or []
                items += page
                if isinstance(data.get("VTM"), dict):
                    vtm.update(data["VTM"])
                if not page or not (data.get("page") or {}).get("hasNext"):
                    break
                offset += len(page)
            self._resources = (time.monotonic(), items, vtm)
            return items, vtm

    def resources_age(self) -> float:
        return time.monotonic() - self._resources[0] if self._resources else 1e9

    def ticket(self) -> str:
        """A stream ticket (VTDU token); the cloud hands out a batch at a time."""
        with self.lock:
            if not self._tickets or time.monotonic() - self._tickets[0] > TICKETS_TTL:
                host = re.sub(r"^https?://", "", self.auth_addr).split("/")[0].split(":")[0].lower()
                if not DOMAIN_RE.match(host):
                    raise StreamError("failed", f"bad auth server {self.auth_addr!r}")
                data = self._get(f"{self.auth_addr.rstrip('/')}/vtdutoken2",
                                 {"ssid": self.session_id, "sign": _session_sign(self.session_id)})
                tokens = [t for t in data.get("tokens") or [] if isinstance(t, str)]
                if str(data.get("retcode")) != "0" or not tokens:
                    if str(data.get("retcode")) in ("401", "403"):
                        raise StreamError("session")
                    raise StreamError("failed", f"stream ticket: retcode {data.get('retcode')}")
                self._tickets = (time.monotonic(), tokens)
                self._ticket_n = 0
            tokens = self._tickets[1]
            self._ticket_n += 1
            return tokens[(self._ticket_n - 1) % len(tokens)]


def _session_sign(session_id: str) -> str:
    """The `s` claim of the session JWT, which the ticket server wants as `sign`."""
    parts = session_id.split(".")
    if len(parts) < 2:
        raise StreamError("session", "session is not a JWT")
    try:
        claims = json.loads(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)))
    except ValueError as exc:
        raise StreamError("session", "unreadable session") from exc
    sign = claims.get("s") if isinstance(claims, dict) else None
    if not isinstance(sign, str) or not sign:
        raise StreamError("session", "no sign in session")
    return sign


def stream_url(acc: Account, serial: str, channel: int, sub: bool) -> str:
    resources, vtm = acc.resources()
    res = _find(resources, serial, channel)
    if res is None and acc.resources_age() > 30:
        # A camera just added to the account, or back online: re-read once.
        resources, vtm = acc.resources(fresh=True)
        res = _find(resources, serial, channel)
    if res is None:
        raise StreamError("offline", f"{serial}/{channel} is not in the account's list")
    server = vtm.get(res.get("resourceId")) or {}
    host = server.get("externalIp") or server.get("domain") or server.get("internalIp")
    port = str(server.get("port") or "")
    if not host or not port.isdigit():
        raise StreamError("offline", f"no relay server for {serial}/{channel}")
    url = build_vtm_url(str(host).strip(), int(port), serial, str(res.get("streamBizUrl") or ""), acc.ticket(),
                        channel=channel, client_type=9)
    if sub:
        url = re.sub(r"(?<=[?&])stream=1(?=&|$)", "stream=2", url)
    return url


def _find(resources: list, serial: str, channel: int) -> dict | None:
    mine = [r for r in resources if isinstance(r, dict) and r.get("deviceSerial") == serial]
    return next((r for r in mine if str(r.get("localIndex")) == str(channel)), None) or (
        mine[0] if channel == 1 and len(mine) == 1 else None)


# --- ffmpeg ----------------------------------------------------------------------------


class Pump:
    """One ffmpeg per stream; fed from a queue so the cloud reader never blocks.

    A reader that blocks on a slow pipe stops reading the relay socket and the
    relay drops packets, which breaks frames. When ffmpeg falls this far
    behind, the backlog is dropped and feeding resumes at the next keyframe.
    """

    def __init__(self, target: str, fmt: str):
        self.target = target
        self.fmt = fmt
        probe = ["-analyzeduration", "500000", "-probesize", "500000"] if fmt == "mpegts" else [
            "-analyzeduration", "0", "-probesize", "64k"]
        cmd = [FFMPEG, "-hide_banner", "-loglevel", "error", "-fflags", "+discardcorrupt",
               "-use_wallclock_as_timestamps", "1", "-flags", "low_delay", "-thread_queue_size", "1024",
               *probe, "-f", fmt, "-i", "pipe:0",
               "-map", "0:v:0", "-an", "-c:v", "copy", "-f", "rtsp", "-rtsp_transport", "tcp",
               f"{RTSP_BASE}/{target}"]
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL)
        self.q: deque[bytes] = deque()
        self.size = 0
        self.cv = threading.Condition()
        self.dropping = False
        self.closed = False
        threading.Thread(target=self._write, daemon=True).start()

    def alive(self) -> bool:
        return not self.closed and self.proc.poll() is None

    def put(self, data: bytes) -> None:
        with self.cv:
            if self.size + len(data) > QUEUE_BYTES and not self.dropping:
                log.warning("%s: ffmpeg is behind, dropping %d KB", self.target, self.size // 1024)
                self.q.clear()
                self.size = 0
                self.dropping = True
            if self.dropping:
                if not is_keyframe_start(data, self.fmt):
                    return
                self.dropping = False
            self.q.append(data)
            self.size += len(data)
            self.cv.notify()

    def _write(self) -> None:
        while True:
            with self.cv:
                while not self.q and not self.closed:
                    self.cv.wait(1)
                if self.closed:
                    return
                chunk = self.q.popleft()
                self.size -= len(chunk)
            try:
                self.proc.stdin.write(chunk)
                self.proc.stdin.flush()
            except (OSError, ValueError):
                self.close()
                return

    def close(self) -> None:
        with self.cv:
            self.closed = True
            self.cv.notify_all()
        try:
            self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.terminate()
            self.proc.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            self.proc.kill()


# --- one stream -------------------------------------------------------------------------


class Worker(threading.Thread):
    def __init__(self, bridge: "Bridge", want: dict):
        super().__init__(daemon=True, name=want["target"])
        self.bridge = bridge
        self.want = want
        self.target = want["target"]
        self.stop = threading.Event()
        self.sock: socket.socket | None = None
        self.state = "starting"
        self.error = ""
        self.codec = ""
        self.bytes = 0
        self.since = time.time()
        self.sub_fallback = False
        self.sub_fails = 0
        self.had_video = False

    def info(self) -> dict:
        return {"state": self.state, "error": self.error[:200], "codec": self.codec, "bytes": self.bytes,
                "since": int(self.since), "sub_fallback": self.sub_fallback}

    def halt(self) -> None:
        self.stop.set()
        s = self.sock
        if s is not None:
            try:
                s.shutdown(socket.SHUT_RDWR)  # wakes the reader blocked in recv
            except OSError:
                pass

    def _connect(self, address, timeout):
        s = socket.create_connection(address, timeout)
        self.sock = s
        if self.stop.is_set():
            s.close()
        return s

    def _set(self, state: str, error: str = "") -> None:
        if state != self.state or error != self.error:
            log.info("%s: %s %s", self.target, state, error)
        self.state, self.error = state, error

    def run(self) -> None:
        backoff = 3
        while not self.stop.is_set():
            acc = self.bridge.account(self.want["account"])
            if acc is None:
                self._set("waiting", "no session for this account yet")
                self.stop.wait(3)
                continue
            self.had_video = False
            try:
                self._play(acc)
                pause = 1
            except StreamError as exc:
                if exc.state == "session":
                    self.bridge.expire(acc.id)
                    self._set("waiting", "cloud session ended, renewing")
                    pause = 5
                elif exc.state == "encrypted":
                    self._set("encrypted", str(exc))
                    pause = 600
                elif exc.state == "offline":
                    self._set("offline", str(exc))
                    pause = 60
                else:
                    self._set("failed", str(exc))
                    pause = backoff
                    backoff = min(backoff * 2, 60)
                if self.want["sub"] and not self.sub_fallback and exc.state in ("failed", "offline") and not self.had_video:
                    self.sub_fails += 1
                    if self.sub_fails >= 2:
                        log.info("%s: no sub stream, using the main one", self.target)
                        self.sub_fallback = True
                        pause = 1
            except Exception as exc:  # noqa: BLE001
                log.exception("%s: unexpected", self.target)
                self._set("failed", str(exc))
                pause = backoff
                backoff = min(backoff * 2, 60)
            if self.had_video:
                backoff = 3
            self.stop.wait(pause)
        self._set("stopped")

    def _play(self, acc: Account) -> None:
        w = self.want
        sub = w["sub"] and not self.sub_fallback
        url = stream_url(acc, w["serial"], int(w["channel"]), sub)
        self._set("starting")
        pump: Pump | None = None
        client = VtmStreamClient(url, timeout=READ_TIMEOUT, socket_factory=self._connect)
        try:
            info = client.start()
            if info.result not in (None, 0):
                raise StreamError("offline", f"relay refused the stream (result {info.result})")
            unwrap = None
            probe = Probe()
            fmt = ""
            for pkt in client.iter_packets():
                if self.stop.is_set():
                    return
                if pkt.encrypted:
                    raise StreamError("encrypted", "encrypted relay link")
                body = bytes(pkt.body)
                if not body:
                    continue
                if unwrap is None:
                    if body[0] == 0x47:
                        unwrap, fmt = (lambda b: b), "mpegts"
                    elif body[0] >> 6 == 2 and body[:4] != b"\x00\x00\x01\xba":
                        unwrap = RtpDepay().feed
                    else:
                        unwrap = PsDemux().feed  # also skips a leading "IMKH" file header
                data = unwrap(body)
                if not data:
                    continue
                if fmt != "mpegts":
                    probe.look(data)
                    if probe.verdict == "encrypted":
                        raise StreamError("encrypted", 'video is encrypted ("video encryption" is on)')
                    if probe.verdict is None:
                        continue
                    fmt = probe.verdict
                    data = probe.gate(data)
                    if not data:
                        continue
                if pump is None or not pump.alive():
                    if pump is not None:
                        raise StreamError("failed", "ffmpeg exited")
                    pump = Pump(self.target, fmt)
                    self.codec = fmt
                    log.info("%s: video %s, publishing", self.target, fmt)
                pump.put(data)
                self.bytes += len(data)
                if not self.had_video:
                    self.had_video = True
                    self.since = time.time()
                    self._set("playing")
        except StreamError:
            raise
        except Exception as exc:  # socket errors, pyezvizapi errors
            if self.stop.is_set():
                return
            if "offline or unreachable" in str(exc).lower():
                raise StreamError("failed", "no video from the device") from exc
            raise StreamError("failed", str(exc)) from exc
        finally:
            try:
                client.close()
            except OSError:
                pass
            self.sock = None
            if pump is not None:
                pump.close()


# --- the service ---------------------------------------------------------------------------


class Bridge:
    def __init__(self):
        self.lock = threading.Lock()
        self.accounts: dict[str, Account] = {}
        self.accounts_set = False
        self.expired: set[str] = set()
        self.workers: dict[str, Worker] = {}
        self.retired: dict[str, tuple[float, dict]] = {}

    def account(self, aid: str) -> Account | None:
        with self.lock:
            return None if aid in self.expired else self.accounts.get(aid)

    def expire(self, aid: str) -> None:
        with self.lock:
            self.expired.add(aid)

    def set_accounts(self, d: dict) -> None:
        with self.lock:
            fresh = {}
            for aid, info in d.items():
                old = self.accounts.get(aid)
                if old is not None and old.same(info):
                    fresh[aid] = old
                else:
                    fresh[aid] = Account(aid, info)
                    self.expired.discard(aid)
            self.expired &= set(fresh)
            self.accounts = fresh
            self.accounts_set = True

    def set_want(self, wants: list) -> None:
        keep = {}
        for w in wants:
            try:
                keep[str(w["target"])] = {"target": str(w["target"]), "account": str(w["account"]),
                                          "serial": str(w["serial"]), "channel": int(w["channel"]),
                                          "sub": bool(w.get("sub"))}
            except (KeyError, TypeError, ValueError):
                continue
        with self.lock:
            for target, wk in list(self.workers.items()):
                if keep.get(target) != wk.want:
                    wk.halt()
                    self.retired[target] = (time.monotonic(), wk.info())
                    del self.workers[target]
            for target, want in keep.items():
                if target not in self.workers and re.match(r"^[A-Za-z0-9_-]{1,100}$", target):
                    wk = Worker(self, want)
                    self.workers[target] = wk
                    self.retired.pop(target, None)
                    wk.start()

    def report(self) -> dict:
        with self.lock:
            now = time.monotonic()
            self.retired = {t: v for t, v in self.retired.items() if now - v[0] < 30}
            streams = {t: w.info() for t, w in self.workers.items()}
            return {"accounts_set": self.accounts_set, "streams": streams, "expired": sorted(self.expired)}


BRIDGE = Bridge()


class Api(BaseHTTPRequestHandler):
    server_version = "argus-cloud-bridge"

    def log_message(self, *args):
        pass

    def _send(self, code: int, body) -> None:
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        if self.path == "/health":
            return True
        if API_TOKEN and self.headers.get("X-Bridge-Token") == API_TOKEN:
            return True
        self._send(403, {"error": "forbidden"})
        return False

    def do_GET(self):
        if not self._authorized():
            return
        if self.path == "/health":
            self._send(200, {"ok": True})
        elif self.path == "/state":
            self._send(200, BRIDGE.report())
        else:
            self._send(404, {"error": "not found"})

    def do_PUT(self):
        if not self._authorized():
            return
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2 * 1024 * 1024:
            self._send(413, {"error": "too large"})
            return
        try:
            body = json.loads(self.rfile.read(n) or b"null")
        except ValueError:
            self._send(400, {"error": "bad json"})
            return
        if self.path == "/accounts" and isinstance(body, dict):
            BRIDGE.set_accounts({str(k): v for k, v in body.items() if isinstance(v, dict)})
            self._send(200, {})
        elif self.path == "/want" and isinstance(body, list):
            BRIDGE.set_want(body)
            self._send(200, {})
        else:
            self._send(404, {"error": "not found"})


def main() -> None:
    if not API_TOKEN:
        log.warning("API_TOKEN is empty: the API refuses everything but /health")
    server = ThreadingHTTPServer(("0.0.0.0", API_PORT), Api)
    log.info("cloud bridge ready: API %d, publishing to %s", API_PORT, RTSP_BASE)
    server.serve_forever()


if __name__ == "__main__":
    main()
