"""Checks media.py against real streams made by ffmpeg (skipped without ffmpeg).

    cd cloud && python -m pytest -q test_media.py
"""

import shutil
import socket
import subprocess
import threading

import pytest

from media import START, Probe, PsDemux, RtpDepay, is_keyframe_start

FFMPEG = shutil.which("ffmpeg")
needs_ffmpeg = pytest.mark.skipif(FFMPEG is None, reason="ffmpeg not installed")


def _encode(codec: str, fmt: str, out: str = "pipe:1", extra=()) -> bytes:
    enc = ["-c:v", "libx264", "-profile:v", "main"] if codec == "h264" else ["-c:v", "libx265", "-x265-params",
                                                                              "log-level=error"]
    cmd = [FFMPEG, "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x240:rate=15", "-t", "2",
           *enc, "-g", "15", "-pix_fmt", "yuv420p", *extra, "-f", fmt, out]
    return subprocess.run(cmd, capture_output=True, check=True).stdout


def _decodes(data: bytes, fmt: str) -> int:
    """Frames ffmpeg decodes from the stream; fails on decoder errors."""
    r = subprocess.run([FFMPEG, "-v", "error", "-f", fmt, "-i", "pipe:0", "-f", "null", "-",
                        "-progress", "pipe:1", "-nostats"], input=data, capture_output=True)
    assert r.returncode == 0, r.stderr.decode()
    assert not r.stderr.strip(), r.stderr.decode()[:500]
    frames = [int(line.split("=")[1]) for line in r.stdout.decode().splitlines() if line.startswith("frame=")]
    return frames[-1] if frames else 0


def _chunks(data: bytes, size: int):
    return [data[i:i + size] for i in range(0, len(data), size)]


@needs_ffmpeg
@pytest.mark.parametrize("piece", [188, 1400, 7001])
def test_ps_h264_any_chunking(piece):
    ps = _encode("h264", "vob", extra=["-an"])
    demux = PsDemux()
    es = b"".join(demux.feed(c) for c in _chunks(b"IMKH" + bytes(36) + ps, piece))
    probe = Probe()
    probe.look(es)
    assert probe.verdict == "h264"
    assert _decodes(probe.gate(es), "h264") == 30


def _rtp_packets(codec: str) -> list[bytes]:
    """RTP packets as ffmpeg sends them (caught on a local UDP port)."""
    rx = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    rx.bind(("127.0.0.1", 0))
    rx.settimeout(3)
    port = rx.getsockname()[1]
    pkts: list[bytes] = []

    def catch():
        try:
            while True:
                pkts.append(rx.recv(65535))
        except OSError:
            pass

    t = threading.Thread(target=catch)
    t.start()
    _encode(codec, "rtp", f"rtp://127.0.0.1:{port}?pkt_size=1200", extra=["-payload_type", "96"])
    t.join()
    rx.close()
    return pkts


@needs_ffmpeg
@pytest.mark.parametrize("codec", ["h264", "hevc"])
def test_rtp_depay(codec):
    depay = RtpDepay()
    es = b"".join(depay.feed(p) for p in _rtp_packets(codec))
    assert depay.codec == codec
    probe = Probe()
    probe.look(es)
    assert probe.verdict == codec
    assert _decodes(probe.gate(es), codec) == 30


@needs_ffmpeg
def test_hevc_annexb_probe():
    es = _encode("hevc", "hevc")
    probe = Probe()
    probe.look(es)
    assert probe.verdict == "hevc"
    assert es.startswith(START) or es.startswith(b"\x00\x00\x01")


def test_encrypted_parameter_sets():
    # Headers intact, bodies scrambled: what "video encryption" produces.
    h264 = (START + b"\x67\xd3\x11\x22" + START + b"\x68\xaa" + START + b"\x65\x88\x99") * 3
    probe = Probe()
    probe.look(h264)
    assert probe.verdict == "encrypted"
    hevc = (START + b"\x40\x01\x9e\x55" + START + b"\x42\x01\x01\x01") * 3
    probe = Probe()
    probe.look(hevc)
    assert probe.verdict == "encrypted"


def test_gate_and_keyframes():
    probe = Probe()
    p_frame = START + b"\x41\x9a\x00"
    assert probe.gate(p_frame) == b""
    sps = START + b"\x67\x4d\x00\x1e"
    assert probe.gate(p_frame + sps) == sps
    assert probe.gate(p_frame) == p_frame
    assert is_keyframe_start(START + b"\x65\x88", "h264")
    assert not is_keyframe_start(START + b"\x41\x9a", "h264")
    assert is_keyframe_start(START + b"\x26\x01\xaf", "hevc")  # IDR_W_RADL
    assert not is_keyframe_start(START + b"\x02\x01\xd0", "hevc")


def test_ps_unbounded_video_packet():
    es = START + b"\x67\x4d\x00\x1e" + START + b"\x65" + b"\x11" * 50
    pack = b"\x00\x00\x01\xba\x44" + bytes(8) + b"\xf8"
    pes = b"\x00\x00\x01\xe0\x00\x00\x80\x00\x00" + es
    demux = PsDemux()
    out = demux.feed(pack + pes)  # end unknown until the next packet starts
    out += demux.feed(pack)
    assert out == es
