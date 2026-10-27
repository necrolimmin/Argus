"""Finding cameras and recorders on the network.

Two complementary methods:

* `discover()`: multicast/broadcast probes (ONVIF WS-Discovery, Hikvision
  SADP, Dahua DHDiscover). Instant and detailed, also finds devices that
  were never set up, but only within the server's own network segment.
* `scan_ranges()`: unicast sweep of IP ranges. Crosses routers: checks the
  usual camera ports on every address, then asks each hit for its identity
  with a unicast WS-Discovery probe.

Runs in the backend in development and in the `scanner` container (host
networking) in Docker, where multicast can reach the real network.
"""

import asyncio
import ipaddress
import json
import re
import select
import socket
import struct
import time
import uuid
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote

import ifaddr

WSD_ADDR = ("239.255.255.250", 3702)
SADP_ADDR = ("239.255.255.250", 37020)
DAHUA_PORT = 37810

# Port -> what it suggests about the device.
PORT_HINTS = {8000: "hikvision", 37777: "dahua", 34567: "dvrip"}
SCAN_PORTS = (554, 80, 8000, 37777, 34567)
MAX_HOSTS = 4096


@dataclass
class Found:
    ip: str
    vendor: str = ""
    model: str = ""
    name: str = ""
    mac: str = ""
    serial: str = ""
    activated: bool | None = None
    http_port: int | None = None
    rtsp_port: int | None = None
    open_ports: list[int] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def merge(self, other: "Found") -> None:
        for key in ("vendor", "model", "name", "mac", "serial", "http_port", "rtsp_port"):
            if not getattr(self, key) and getattr(other, key):
                setattr(self, key, getattr(other, key))
        if other.activated is not None:
            self.activated = other.activated
        self.open_ports = sorted(set(self.open_ports) | set(other.open_ports))
        self.sources = sorted(set(self.sources) | set(other.sources))

    def as_dict(self) -> dict:
        return asdict(self)


def _guess_vendor(*texts: str) -> str:
    joined = " ".join(texts).lower()
    for needle, vendor in (
        ("hikvision", "hikvision"), ("ds-2", "hikvision"), ("ezviz", "ezviz"),
        ("dahua", "dahua"), ("ipc-h", "dahua"), ("uniview", "uniview"), ("ipc32", "uniview"),
        ("axis", "axis"), ("vigi", "vigi"), ("tp-link", "vigi"), ("reolink", "reolink"),
    ):
        if needle in joined:
            return vendor
    return ""


def _norm_mac(mac: str) -> str:
    return mac.strip().lower().replace("-", ":")


def local_ipv4() -> list[str]:
    ips = []
    for adapter in ifaddr.get_adapters():
        for ip in adapter.ips:
            if isinstance(ip.ip, str) and not ip.ip.startswith(("127.", "169.254.")):
                ips.append(ip.ip)
    return ips


# --- message builders and parsers (pure, unit-tested) --------------------------


def wsd_probe() -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing" '
        'xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery" '
        'xmlns:dn="http://www.onvif.org/ver10/network/wsdl">'
        f"<e:Header><w:MessageID>uuid:{uuid.uuid4()}</w:MessageID>"
        '<w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>'
        '<w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>'
        "</e:Header><e:Body><d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe></e:Body></e:Envelope>"
    ).encode()


def parse_wsd(data: bytes, sender_ip: str) -> Found | None:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    xaddrs = " ".join(el.text or "" for el in root.iter() if el.tag.endswith("}XAddrs"))
    scopes = " ".join(el.text or "" for el in root.iter() if el.tag.endswith("}Scopes"))
    if not xaddrs and not scopes:
        return None
    ip, port = sender_ip, None
    for m in re.finditer(r"https?://([\d.]+)(?::(\d+))?/", xaddrs):
        if m.group(1) == sender_ip or ip == sender_ip:
            ip, port = m.group(1), int(m.group(2) or 80)
            break

    def scope(key: str) -> str:
        m = re.search(rf"onvif://www\.onvif\.org/{key}/(\S+)", scopes, re.IGNORECASE)
        return unquote(m.group(1)) if m else ""

    name, hardware = scope("name"), scope("hardware")
    return Found(
        ip=ip,
        vendor=_guess_vendor(name, hardware) or "onvif",
        model=hardware,
        name=name,
        mac=_norm_mac(scope("MAC")),
        http_port=port,
        sources=["onvif"],
    )


def sadp_probe() -> bytes:
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f"<Probe><Uuid>{str(uuid.uuid4()).upper()}</Uuid><Types>inquiry</Types></Probe>"
    ).encode()


def parse_sadp(data: bytes) -> Found | None:
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return None
    if not root.tag.endswith("ProbeMatch"):
        return None

    def t(tag: str) -> str:
        el = root.find(tag)
        return (el.text or "").strip() if el is not None and el.text else ""

    ip = t("IPv4Address")
    if not ip:
        return None
    activated = t("Activated").lower()
    http_port = t("HttpPort")
    return Found(
        ip=ip,
        vendor="ezviz" if "ezviz" in t("DeviceDescription").lower() else "hikvision",
        model=t("DeviceDescription"),
        serial=t("DeviceSN"),
        mac=_norm_mac(t("MAC")),
        activated=None if not activated else activated == "true",
        http_port=int(http_port) if http_port.isdigit() else None,
        sources=["sadp"],
    )


def dahua_probe() -> bytes:
    body = json.dumps({"method": "DHDiscover.search", "params": {"mac": "", "uni": 1}}).encode()
    header = b"\x20\x00\x00\x00DHIP" + b"\x00" * 8 + struct.pack("<I", len(body)) + b"\x00" * 4
    header += struct.pack("<I", len(body)) + b"\x00" * 4
    return header + body


def parse_dahua(data: bytes) -> Found | None:
    start = data.find(b"{")
    if start < 0:
        return None
    try:
        msg = json.loads(data[start:].split(b"\x00")[0])
    except (ValueError, UnicodeDecodeError):
        return None
    info = (msg.get("params") or {}).get("deviceInfo") or {}
    ip = ((info.get("IPv4Address") or {}).get("IPAddress")) or ""
    if not ip:
        return None
    init = info.get("Init")
    return Found(
        ip=ip,
        vendor="dahua",
        model=info.get("DeviceType", ""),
        name=info.get("MachineName", ""),
        serial=info.get("SerialNo", ""),
        mac=_norm_mac(info.get("Mac", "")),
        # Dahua reports uninitialised devices with Init == 1.
        activated=None if init is None else init != 1,
        http_port=info.get("HttpPort"),
        sources=["dahua"],
    )


# --- multicast discovery -------------------------------------------------------


def _collect(sock: socket.socket, deadline: float, parse, results: dict[str, Found]) -> None:
    while (left := deadline - time.monotonic()) > 0:
        ready, _, _ = select.select([sock], [], [], left)
        if not ready:
            return
        try:
            data, (sender, _) = sock.recvfrom(65535)
        except OSError:
            return
        found = parse(data, sender) if parse is parse_wsd else parse(data)
        if found:
            results.setdefault(found.ip, Found(ip=found.ip)).merge(found)


def _multicast_socket(iface_ip: str, bind_port: int = 0) -> socket.socket:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface_ip))
    s.bind(("" if bind_port else iface_ip, bind_port))
    return s


def discover_sync(timeout: float = 3.0) -> list[Found]:
    results: dict[str, Found] = {}
    sockets: list[tuple[socket.socket, object]] = []
    for iface in local_ipv4():
        try:
            wsd = _multicast_socket(iface)
            wsd.sendto(wsd_probe(), WSD_ADDR)
            sockets.append((wsd, parse_wsd))
        except OSError:
            pass
        try:
            # SADP answers to the multicast group, so listen on its port.
            sadp = _multicast_socket(iface, SADP_ADDR[1])
            sadp.setsockopt(
                socket.IPPROTO_IP,
                socket.IP_ADD_MEMBERSHIP,
                socket.inet_aton(SADP_ADDR[0]) + socket.inet_aton(iface),
            )
            sadp.sendto(sadp_probe(), SADP_ADDR)
            sockets.append((sadp, parse_sadp))
        except OSError:
            pass
        try:
            dh = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
            dh.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            dh.bind((iface, 0))
            dh.sendto(dahua_probe(), ("255.255.255.255", DAHUA_PORT))
            sockets.append((dh, parse_dahua))
        except OSError:
            pass

    deadline = time.monotonic() + timeout
    try:
        while (left := deadline - time.monotonic()) > 0:
            ready, _, _ = select.select([s for s, _ in sockets], [], [], left)
            if not ready:
                break
            for sock in ready:
                parse = next(p for s, p in sockets if s is sock)
                _collect(sock, time.monotonic() + 0.05, parse, results)
    finally:
        for s, _ in sockets:
            s.close()
    return sorted(results.values(), key=lambda f: ipaddress.ip_address(f.ip))


async def discover(timeout: float = 3.0) -> list[Found]:
    return await asyncio.to_thread(discover_sync, timeout)


# --- range scan ----------------------------------------------------------------


def _split_specs(specs: list[str]) -> list[str]:
    """Normalizes what people type into one range per item.

    Handles spaces around the dash ("10.0.0.1 - 10.0.0.9"), typographic
    dashes, several ranges in one line, "10.0.0.*" and a bare "10.0.0".
    """
    out: list[str] = []
    for raw in specs:
        text = re.sub(r"\s*[-‐-―−]\s*", "-", raw.strip())
        for spec in re.split(r"[,;\s]+", text):
            if not spec:
                continue
            if spec.endswith(".*"):
                spec = spec[:-2] + ".0/24"
            elif re.fullmatch(r"\d{1,3}\.\d{1,3}\.\d{1,3}\.?", spec):
                spec = spec.rstrip(".") + ".0/24"
            out.append(spec)
    return out


def parse_ranges(specs: list[str]) -> list[str]:
    """Accepts "192.168.3.0/24", "192.168.3.10-192.168.3.50", "192.168.3.10-50",
    "192.168.3.*" or "192.168.3"; see `_split_specs` for the tolerated spellings."""
    hosts: list[str] = []
    for spec in _split_specs(specs):
        if "/" in spec:
            net = ipaddress.ip_network(spec, strict=False)
            hosts.extend(str(h) for h in (net.hosts() if net.num_addresses > 2 else net))
        elif "-" in spec:
            start_s, end_s = spec.split("-", 1)
            start = ipaddress.IPv4Address(start_s)
            end = (
                ipaddress.IPv4Address(end_s)
                if "." in end_s
                else ipaddress.IPv4Address(".".join(start_s.split(".")[:3] + [end_s]))
            )
            if end < start:
                raise ValueError(spec)
            hosts.extend(str(ipaddress.IPv4Address(i)) for i in range(int(start), int(end) + 1))
        else:
            hosts.append(str(ipaddress.IPv4Address(spec)))
        if len(hosts) > MAX_HOSTS:
            raise OverflowError(MAX_HOSTS)
    return list(dict.fromkeys(hosts))


async def _port_open(ip: str, port: int, timeout: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout)
        writer.close()
        return True
    except (OSError, asyncio.TimeoutError):
        return False


class _WsdUnicast(asyncio.DatagramProtocol):
    def __init__(self, ip: str):
        self.ip = ip
        self.result: Found | None = None
        self.done = asyncio.get_running_loop().create_future()

    def datagram_received(self, data, addr):
        self.result = parse_wsd(data, addr[0])
        if not self.done.done():
            self.done.set_result(None)


async def _wsd_unicast(ip: str, timeout: float = 1.2) -> Found | None:
    loop = asyncio.get_running_loop()
    try:
        transport, proto = await loop.create_datagram_endpoint(lambda: _WsdUnicast(ip), remote_addr=(ip, 3702))
    except OSError:
        return None
    try:
        transport.sendto(wsd_probe())
        await asyncio.wait_for(proto.done, timeout)
        return proto.result
    except asyncio.TimeoutError:
        return None
    finally:
        transport.close()


async def scan_ranges(specs: list[str], timeout: float = 1.5) -> list[Found]:
    hosts = parse_ranges(specs)
    # Many parallel half-open connections make slow cameras miss the window
    # (and Windows throttles them), so the sweep is moderate and the hosts
    # that stayed silent get a second, slower look.
    limit = asyncio.Semaphore(64)

    async def ports_of(ip: str, ports: tuple[int, ...], wait: float) -> list[int]:
        async with limit:
            opened = await asyncio.gather(*(_port_open(ip, p, wait) for p in ports))
        return [p for p, ok in zip(ports, opened) if ok]

    async def check(ip: str) -> Found | None:
        ports = await ports_of(ip, SCAN_PORTS, timeout)
        if not ports:
            ports = await ports_of(ip, (554, 8000, 37777, 34567), timeout * 2.5)
            if ports:
                ports = sorted(set(ports) | set(await ports_of(ip, (80,), timeout * 2.5)))
        # Port 80 alone is any web server; a camera has RTSP or a vendor port.
        if not any(p in ports for p in (554, 8000, 37777, 34567)):
            return None
        found = Found(
            ip=ip,
            vendor=next((PORT_HINTS[p] for p in ports if p in PORT_HINTS), ""),
            open_ports=ports,
            rtsp_port=554 if 554 in ports else None,
            http_port=80 if 80 in ports else None,
            sources=["scan"],
        )
        onvif = await _wsd_unicast(ip)
        if onvif:
            vendor_hint = found.vendor
            found.merge(onvif)
            # A vendor port is a stronger hint than a generic ONVIF answer.
            found.vendor = vendor_hint or onvif.vendor
        return found

    results = await asyncio.gather(*(check(ip) for ip in hosts))
    return [f for f in results if f]
