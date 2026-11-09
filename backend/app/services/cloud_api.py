"""Talking to the Hik-Connect / EZVIZ cloud: login, session refresh, device list.

Both apps run on the same backend and differ in the login call and in the
"client type" they present. Argus logs in the way the phone apps do, so to
the cloud it is one more phone of the account owner (with a fixed feature
code, the same "phone" on every login).

The password is sent as its MD5, which is what the cloud expects. It must
only ever go to the vendor's own servers: every domain, including the one
the cloud redirects to, is checked against DOMAIN_RE.

Endpoints and codes are those of the public mobile apps, as also used by
pyEzvizApi (Apache-2.0).
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import asdict, dataclass, field

import httpx

DOMAIN_RE = re.compile(
    r"^[a-z0-9-]+(\.[a-z0-9-]+)*\.(ezvizlife\.com|ezviz\.com|ezvizru\.com|hik-connect\.com|hik-connectru\.com)\Z"
)

PROVIDERS = {
    # Global server first; an account the global server does not know is
    # tried on the Russian/CIS cloud, which is separate.
    "hik": {"client_type": "55", "login": "/v3/users/login/v2",
            "domains": ["api.hik-connect.com", "api.hik-connectru.com"]},
    "ezviz": {"client_type": "1", "login": "/v3/users/login/v5",
              "domains": ["apiieu.ezvizlife.com", "apiirus.ezvizru.com"]},
}

TIMEOUT = 20
MAX_PAGES = 40  # 50 per page: 2000 devices is far beyond any real account

# Set by tests to answer instead of the real cloud.
transport: httpx.AsyncBaseTransport | None = None


class CloudError(Exception):
    """A login or API failure; `code` is shown to the user (translated)."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


@dataclass
class Session:
    provider: str
    api: str  # the account's API domain
    session_id: str
    rf_session_id: str
    feature_code: str
    auth_addr: str = ""
    at: float = field(default_factory=time.time)  # when it was issued or refreshed

    @property
    def client_type(self) -> str:
        return PROVIDERS[self.provider]["client_type"]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        return cls(**{k: d[k] for k in cls.__dataclass_fields__ if k in d})


def feature_code(seed: str) -> str:
    return hashlib.md5(f"argus-{seed}".encode()).hexdigest()


def safe_domain(domain: str) -> str:
    d = (domain or "").strip().lower()
    if not DOMAIN_RE.match(d):
        raise CloudError("cloud_bad_server", d)
    return d


def headers(provider: str, fcode: str, session_id: str = "") -> dict:
    h = {
        "clientType": PROVIDERS[provider]["client_type"],
        "customNo": "1000001",
        "clientVersion": "5.12.1.0517",
        "lang": "en-US",
        "featureCode": fcode,
        "User-Agent": "okhttp/3.12.1",
    }
    if session_id:
        h["sessionId"] = session_id
    return h


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=TIMEOUT, transport=transport, follow_redirects=False)


async def _json(r: httpx.Response) -> dict:
    try:
        data = r.json()
    except ValueError as exc:
        raise CloudError("cloud_unavailable", f"HTTP {r.status_code}") from exc
    if not isinstance(data, dict):
        raise CloudError("cloud_unavailable", f"HTTP {r.status_code}")
    return data


def _code(data: dict):
    meta = data.get("meta") or {}
    code = meta.get("code")
    try:
        return int(code)
    except (TypeError, ValueError):
        return code


async def send_code(provider: str, login: str, fcode: str, domain: str = "") -> None:
    """Asks the cloud to e-mail / text the owner a one-time login code."""
    domain = safe_domain(domain or PROVIDERS[provider]["domains"][0])
    async with _client() as c:
        try:
            r = await c.post(f"https://{domain}/v3/sms/nologin/checkcode",
                             data={"from": login, "bizType": "TERMINAL_BIND"},
                             headers=headers(provider, fcode))
        except httpx.HTTPError as exc:
            raise CloudError("cloud_unavailable", str(exc)) from exc
    data = await _json(r)
    if _code(data) != 200:
        raise CloudError("cloud_code_not_sent", str(data.get("meta")))


async def login(provider: str, login: str, password: str, fcode: str,
                domain: str = "", sms_code: str = "") -> Session:
    """Logs in and returns the session. Raises CloudError with a user-facing code.

    `cloud_needs_code` means the account has two-step login on: the cloud
    has just sent the owner a code, and login must be repeated with it.
    """
    if provider not in PROVIDERS:
        raise CloudError("cloud_bad_provider", provider)
    spec = PROVIDERS[provider]
    domains = [domain] if domain else list(spec["domains"])
    pw = hashlib.md5(password.encode()).hexdigest()
    async with _client() as c:
        for start in domains:
            api = safe_domain(start)
            for _ in range(4):  # region redirects
                form = {"account": login, "password": pw, "featureCode": fcode}
                if provider == "ezviz":
                    form |= {"msgType": "3" if sms_code else "0", "cuName": "SSmartPhone_Android"}
                if sms_code:
                    form |= {"smsCode": sms_code, "bizType": "TERMINAL_BIND"}
                try:
                    r = await c.post(f"https://{api}{spec['login']}", data=form, headers=headers(provider, fcode))
                except httpx.HTTPError as exc:
                    raise CloudError("cloud_unavailable", str(exc)) from exc
                data = await _json(r)
                code = _code(data)
                if code == 1100:  # the account lives on another regional server
                    api = safe_domain((data.get("loginArea") or {}).get("apiDomain", ""))
                    continue
                break
            if code == 200:
                ls = data.get("loginSession") or {}
                area = (data.get("loginArea") or {}).get("apiDomain") or api
                s = Session(provider=provider, api=safe_domain(area), session_id=str(ls.get("sessionId") or ""),
                            rf_session_id=str(ls.get("rfSessionId") or ""), feature_code=fcode)
                if not s.session_id:
                    raise CloudError("cloud_unavailable", "no session in the answer")
                s.auth_addr = await _auth_addr(c, s)
                return s
            if code == 1013 and start != domains[-1]:
                continue  # unknown user here: try the other cloud
            if code in (1013, 1014, 1226):
                raise CloudError("cloud_bad_login")
            if code == 1015:
                raise CloudError("cloud_locked")
            if code == 1012:
                raise CloudError("cloud_bad_code")
            if code == 6002:
                await send_code(provider, login, fcode, api)
                raise CloudError("cloud_needs_code")
            if code in (1016, 1017, 6003):
                raise CloudError("cloud_captcha")
            raise CloudError("cloud_login_failed", str(data.get("meta")))
    raise CloudError("cloud_login_failed")


async def _auth_addr(c: httpx.AsyncClient, s: Session) -> str:
    """The server that issues stream tickets (needed to open video)."""
    try:
        r = await c.get(f"https://{s.api}/v3/configurations/system/info",
                        headers=headers(s.provider, s.feature_code, s.session_id))
        addr = str(((await _json(r)).get("systemConfigInfo") or {}).get("authAddr") or "").strip()
    except (httpx.HTTPError, CloudError):
        addr = ""
    host = re.sub(r"^https?://", "", addr).split("/")[0].split(":")[0].lower()
    if host and host not in ("null", "none") and DOMAIN_RE.match(host):
        return addr if addr.startswith("http") else f"https://{addr}"
    m = re.match(r"apii([a-z]+)\.", s.api)
    return f"https://{m.group(1)}auth.ezvizlife.com" if m else ""


async def refresh(s: Session) -> Session:
    """Extends the session without the password. Raises CloudError("cloud_session") if it cannot."""
    async with _client() as c:
        try:
            r = await c.put(f"https://{safe_domain(s.api)}/v3/apigateway/login",
                            data={"refreshSessionId": s.rf_session_id, "featureCode": s.feature_code},
                            headers=headers(s.provider, s.feature_code, s.session_id))
        except httpx.HTTPError as exc:
            raise CloudError("cloud_unavailable", str(exc)) from exc
        data = await _json(r)
        if _code(data) != 200:
            raise CloudError("cloud_session", str(data.get("meta")))
        info = data.get("sessionInfo") or {}
        s = Session.from_dict(s.to_dict())
        s.session_id = str(info.get("sessionId") or s.session_id)
        s.rf_session_id = str(info.get("refreshSessionId") or s.rf_session_id)
        s.at = time.time()
        return s


async def _pages(c: httpx.AsyncClient, s: Session, path: str, params: dict, key: str) -> tuple[list, dict]:
    items: list = []
    extra: dict = {}
    offset = 0
    for _ in range(MAX_PAGES):
        try:
            r = await c.get(f"https://{safe_domain(s.api)}{path}", params={**params, "groupId": -1, "limit": 50,
                                                                          "offset": offset},
                            headers=headers(s.provider, s.feature_code, s.session_id))
        except httpx.HTTPError as exc:
            raise CloudError("cloud_unavailable", str(exc)) from exc
        if r.status_code == 401:
            raise CloudError("cloud_session")
        data = await _json(r)
        code = _code(data)
        if code != 200:
            raise CloudError("cloud_session" if code in (401, 1001, 1002, 1003, 1004) else "cloud_unavailable",
                             str(data.get("meta")))
        page = data.get(key) or []
        items.extend(page)
        for k in ("statusInfos",):
            if isinstance(data.get(k), dict):
                extra.setdefault(k, {}).update(data[k])
        if not page or not (data.get("page") or {}).get("hasNext"):
            break
        offset += len(page)
    return items, extra


async def devices(s: Session) -> list[dict]:
    """The account's devices with their channels.

    [{serial, name, model, online, encrypted, channels: [{channel, name}]}]
    A camera has one channel; a recorder one per connected camera.
    """
    async with _client() as c:
        devs, extra = await _pages(c, s, "/v3/userdevices/v1/devices/pagelist",
                                   {"filter": "CONNECTION,STATUS,CHANNEL,VTM"}, "deviceInfos")
        res, _ = await _pages(c, s, "/v3/userdevices/v1/resources/pagelist", {"filter": "VTM"}, "resourceInfos")
    status = extra.get("statusInfos", {})
    chans: dict[str, dict[int, str]] = {}
    for r in res:
        serial = str(r.get("deviceSerial") or "")
        try:
            ch = int(r.get("localIndex"))
        except (TypeError, ValueError):
            continue
        if serial and ch >= 1:  # 0 is the recorder itself
            chans.setdefault(serial, {})[ch] = str(r.get("resourceName") or "").strip()[:120]
    out = []
    for d in devs:
        serial = str(d.get("deviceSerial") or "")
        if not serial:
            continue
        found = chans.get(serial) or {1: ""}
        out.append({
            "serial": serial,
            "name": str(d.get("name") or serial).strip()[:200],
            "model": str(d.get("deviceType") or "")[:200],
            "online": int(d.get("status") or 0) == 1,
            "encrypted": bool((status.get(serial) or {}).get("isEncrypt")),
            "channels": [{"channel": ch, "name": name} for ch, name in sorted(found.items())],
        })
    out.sort(key=lambda d: d["name"].lower())
    return out
