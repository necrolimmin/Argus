"""Turning the cloud's packets into a plain H.264 / H.265 stream for ffmpeg.

The cloud relays whatever the device sends: recorders and most cameras send
MPEG-PS, battery cameras RTP, a few MPEG-TS. ffmpeg gets an Annex-B
elementary stream (or the TS as is) and copies it into go2rtc.

The probe also answers "can this be shown at all": with "video encryption"
on in the owner's app, the device encrypts its video with a code printed on
the camera, and what arrives is noise behind valid-looking headers.
"""

from __future__ import annotations

START = b"\x00\x00\x00\x01"
MAX_BUFFER = 4 * 1024 * 1024
# profile_idc of a real H.264 SPS; an encrypted one has a random byte here.
H264_PROFILES = frozenset({66, 77, 88, 100, 110, 118, 122, 128, 134, 135, 138, 139, 144, 244, 44, 83, 86})


class PsDemux:
    """MPEG-PS → the video elementary stream (Annex-B), packet by packet.

    Packets are skipped by their length, so start codes inside the video
    are never mistaken for packet starts; anything unrecognised (such as
    Hikvision's 40-byte file header) is skipped up to the next start code.
    """

    def __init__(self) -> None:
        self.buf = bytearray()

    def feed(self, data: bytes) -> bytes:
        b = self.buf
        b += data
        out = bytearray()
        i = 0
        n = len(b)
        while True:
            j = b.find(b"\x00\x00\x01", i)
            if j < 0:
                i = max(i, n - 3)
                break
            if j + 4 > n:
                i = j
                break
            sid = b[j + 3]
            if sid == 0xBA:  # pack header
                if j + 14 > n:
                    i = j
                    break
                size = 14 + (b[j + 13] & 7) if b[j + 4] >> 6 == 1 else 12
                if j + size > n:
                    i = j
                    break
                i = j + size
                continue
            if sid == 0xB9:  # program end
                i = j + 4
                continue
            if sid < 0xBB:  # a start code that is not a PS packet: resync
                i = j + 3
                continue
            if j + 6 > n:
                i = j
                break
            length = (b[j + 4] << 8) | b[j + 5]
            if 0xE0 <= sid <= 0xEF:
                if j + 9 > n:
                    i = j
                    break
                payload = j + 9 + b[j + 8]
                if length == 0:  # unbounded video packet: runs to the next PS start code
                    end = _next_ps_start(b, payload)
                    if end < 0:
                        i = j
                        break
                else:
                    end = j + 6 + length
                    if end > n:
                        i = j
                        break
                if payload < end:
                    out += b[payload:end]
                i = end
                continue
            end = j + 6 + length  # system header, stream map, audio, padding, private
            if end > n:
                i = j
                break
            i = end
        del b[:i]
        if len(b) > MAX_BUFFER:
            b.clear()
        return bytes(out)


def _next_ps_start(b: bytearray, start: int) -> int:
    # 0xB9 and up can never be a NAL header byte (forbidden bit), so inside
    # video data "00 00 01 ≥B9" only appears at a real PS packet start.
    i = start
    while True:
        j = b.find(b"\x00\x00\x01", i)
        if j < 0 or j + 3 >= len(b):
            return -1
        if b[j + 3] >= 0xB9:
            return j
        i = j + 3


def _hevc_header(b0: int, b1: int) -> bool:
    return b0 & 0x81 == 0 and b1 & 0xF8 == 0 and b1 & 0x07 != 0


class RtpDepay:
    """RTP (H.264 RFC 6184 / H.265 RFC 7798) → Annex-B.

    The codec is not announced (no SDP), so it is told from the payload
    headers of the first video packets: an H.265 header's second byte is
    almost always 0x01 (layer 0, temporal id 1), an H.264 one's is data.
    """

    VIDEO_PT = 96

    def __init__(self) -> None:
        self.codec: str | None = None
        self._held: list[bytes] = []
        self._votes = {"h264": 0, "hevc": 0}

    def feed(self, pkt: bytes) -> bytes:
        payload = _rtp_payload(pkt)
        if payload is None or len(payload) < 2:
            return b""
        if self.codec is None:
            self._vote(payload)
            self._held.append(payload)
            if max(self._votes.values()) < 8 and len(self._held) < 60:
                return b""
            self.codec = "hevc" if self._votes["hevc"] > self._votes["h264"] else "h264"
            held, self._held = self._held, []
            return b"".join(self._depay(p) for p in held)
        return self._depay(payload)

    def _vote(self, p: bytes) -> None:
        if _hevc_header(p[0], p[1]) and ((p[0] >> 1) & 0x3F) in (*range(0, 22), 32, 33, 34, 35, 39, 40, 48, 49):
            self._votes["hevc"] += 1
        elif p[0] & 0x80 == 0 and (p[0] & 0x1F) in (1, 5, 6, 7, 8, 9, 24, 28):
            self._votes["h264"] += 1

    def _depay(self, p: bytes) -> bytes:
        return _depay_hevc(p) if self.codec == "hevc" else _depay_h264(p)


def _rtp_payload(pkt: bytes) -> bytes | None:
    if len(pkt) < 12 or pkt[0] >> 6 != 2 or pkt[1] & 0x7F != RtpDepay.VIDEO_PT:
        return None
    off = 12 + 4 * (pkt[0] & 0x0F)
    if pkt[0] & 0x10:
        if len(pkt) < off + 4:
            return None
        off += 4 + 4 * int.from_bytes(pkt[off + 2:off + 4], "big")
    end = len(pkt)
    if pkt[0] & 0x20 and end > off:
        end -= pkt[-1]
    return pkt[off:end] if off < end else None


def _depay_h264(p: bytes) -> bytes:
    t = p[0] & 0x1F
    if 1 <= t <= 23:
        return START + p
    if t == 24:  # STAP-A
        out = bytearray()
        i = 1
        while i + 2 <= len(p):
            size = int.from_bytes(p[i:i + 2], "big")
            i += 2
            if size == 0 or i + size > len(p):
                break
            out += START + p[i:i + size]
            i += size
        return bytes(out)
    if t == 28 and len(p) > 2:  # FU-A
        if p[1] & 0x80:
            return START + bytes([(p[0] & 0xE0) | (p[1] & 0x1F)]) + p[2:]
        return p[2:]
    return b""


def _depay_hevc(p: bytes) -> bytes:
    t = (p[0] >> 1) & 0x3F
    if t < 48:
        return START + p
    if t == 48:  # aggregation packet
        out = bytearray()
        i = 2
        while i + 2 <= len(p):
            size = int.from_bytes(p[i:i + 2], "big")
            i += 2
            if size == 0 or i + size > len(p):
                break
            out += START + p[i:i + size]
            i += size
        return bytes(out)
    if t == 49 and len(p) > 3:  # fragmentation unit
        if p[2] & 0x80:
            return START + bytes([(p[0] & 0x81) | ((p[2] & 0x3F) << 1), p[1]]) + p[3:]
        return p[3:]
    return b""


def nal_headers(data: bytes):
    """(offset, first byte, second byte) of each NAL unit in an Annex-B chunk."""
    i = 0
    n = len(data)
    while True:
        j = data.find(b"\x00\x00\x01", i)
        if j < 0 or j + 4 >= n:
            return
        yield j + 3, data[j + 3], data[j + 4]
        i = j + 3


class Probe:
    """Watches the start of an Annex-B stream: codec, and whether it is readable.

    verdict: None (not yet), "h264", "hevc" or "encrypted". `gate` drops
    everything before the first parameter set, so ffmpeg starts cleanly.
    """

    LIMIT = 3 * 1024 * 1024  # this much video without a clean parameter set: give up

    def __init__(self) -> None:
        self.verdict: str | None = None
        self.seen = 0
        self.bad = 0
        self.started = False

    def look(self, data: bytes) -> None:
        if self.verdict is not None:
            return
        self.seen += len(data)
        for off, b0, b1 in nal_headers(data):
            body = data[off + 2:off + 3] if off + 2 < len(data) else b""
            if _hevc_header(b0, b1) and (b0 >> 1) & 0x3F == 32:  # H.265 VPS
                if body and body[0] & 0x0F == 0x0C:
                    self.verdict = "hevc"
                    return
                self.bad += 1
            elif b0 & 0x9F == 0x07:  # H.264 SPS
                if b1 in H264_PROFILES:
                    self.verdict = "h264"
                    return
                self.bad += 1
        if self.bad >= 3 or self.seen > self.LIMIT:
            self.verdict = "encrypted"

    def gate(self, data: bytes) -> bytes:
        """Passes data on from the first parameter set (SPS/VPS) onwards."""
        if self.started:
            return data
        for off, b0, b1 in nal_headers(data):
            if (b0 & 0x9F == 0x07) or (_hevc_header(b0, b1) and (b0 >> 1) & 0x3F == 32):
                self.started = True
                return data[max(0, off - 4 if data[off - 4:off] == START else off - 3):]
        return b""


def is_keyframe_start(data: bytes, codec: str) -> bool:
    """The chunk starts a point a decoder can join at (parameter set or IDR)."""
    for _off, b0, b1 in nal_headers(data[:64]):
        if codec == "hevc":
            t = (b0 >> 1) & 0x3F
            return 16 <= t <= 21 or 32 <= t <= 34
        if codec == "h264":
            return (b0 & 0x1F) in (5, 7, 8)
        return True
    return codec == "mpegts"
