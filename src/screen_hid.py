#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HID transport for the AULA Neos75 screen (JPEG wallpaper channel).

Port of the reference project's `wallpaper/screen_wallpaper.js` framing, so the
whole lyric pipeline can ship as a single Python executable without Node.js.
"""
import struct
import time
import zlib

VID = 0x5542
PID = 0x0001
USAGE_PAGE = 0xFF60
USAGE = 0x61
BLOCK = 4096
CHUNK = 62


class ScreenError(RuntimeError):
    pass


def _hid():
    import hid  # hidapi
    return hid


SCREEN_IDS = ((0x5542, 0x0001), (0x6D66, 0x8572))   # wired screen / 2.4G dongle


def find_device(prefer_wired=True):
    """Locate the screen vendor interface (wired screen first, then 2.4G dongle)."""
    hid = _hid()
    found = []
    for info in hid.enumerate():
        if info.get("usage_page") != USAGE_PAGE or info.get("usage") != USAGE:
            continue
        vid, pid = info.get("vendor_id"), info.get("product_id")
        product = (info.get("product_string") or "").lower()
        # the 2.4G dongle exposes the same usage page but only echoes reports,
        # so only the wired screen can actually receive frames
        if (vid, pid) == (0x5542, 0x0001):
            found.append(info)
    if not found:
        return None
    found.sort(key=lambda i: 0 if (i["vendor_id"], i["product_id"]) == (0x5542, 0x0001) else 1)
    return found[0]


def official_app_running():
    """True when the AULA desktop app is running (it competes for the screen)."""
    try:
        import subprocess
        out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Aula Hub.exe", "/FO", "CSV", "/NH"],
                             capture_output=True, text=True, encoding="gbk", errors="ignore",
                             creationflags=0x08000000).stdout
        return "aula hub" in out.lower()
    except Exception:
        return False


def has_dongle_only():
    """True when the 2.4G dongle is present but the wired screen is not."""
    hid = _hid()
    dongle = wired = False
    for info in hid.enumerate():
        if (info.get("vendor_id"), info.get("product_id")) == (0x6D66, 0x8572):
            dongle = True
        if (info.get("vendor_id"), info.get("product_id")) == (0x5542, 0x0001):
            wired = True
    return dongle and not wired


def _report(payload: bytes) -> bytes:
    if len(payload) > 63:
        raise ScreenError("report payload too long")
    buf = bytearray(65)
    buf[0] = 0
    buf[1] = 0xBA
    buf[2:2 + len(payload)] = payload
    return bytes(buf)


def build_stream(jpeg: bytes, width: int, height: int) -> bytes:
    head = bytearray(13)
    head[0:2] = b"UB"
    struct.pack_into(">HHH", head, 2, width, height, 1)
    head[8] = 0
    struct.pack_into(">I", head, 9, len(jpeg))
    return bytes(head) + jpeg


def frames(stream: bytes):
    """Yield (report_bytes, expects_ack)."""
    start = bytes([6, 0xAA, 0xB0]) + struct.pack(">I", len(stream))
    yield _report(start), True

    p = 0
    n = len(stream)
    while p + BLOCK <= n:
        block = stream[p:p + BLOCK]
        crc = struct.pack("<I", zlib.crc32(block) & 0xFFFFFFFF)
        end = p + BLOCK
        while p < end:
            take = min(CHUNK, end - p)
            last = (p + take == end)
            payload = bytes([take]) + stream[p:p + take] + (crc if last else b"")
            yield _report(payload), last
            p += take
    while p < n:
        take = min(CHUNK, n - p)
        yield _report(bytes([take]) + stream[p:p + take]), False
        p += take


class Screen:
    def __init__(self):
        self.dev = None
        self.info = None

    def open(self):
        info = find_device()
        if not info:
            raise ScreenError("没有找到 Neos75 屏幕（USB 5542:0001 / 0xFF60）")
        dev = _hid().device()
        dev.open_path(info["path"])
        dev.set_nonblocking(0)
        self.dev = dev
        self.info = info
        return self

    def close(self):
        try:
            if self.dev:
                self.dev.close()
        except Exception:
            pass
        self.dev = None

    # ---------------------------------------------------------------- reads
    def _query(self, selector, min_len):
        body = bytes([0x41, 0, 1, selector])
        chk = (sum(body) ^ 0xFF) & 0xFF
        self.dev.write(bytes([0, 0xA5]) + body + bytes([chk]) + bytes(58))
        deadline = time.time() + 1.5
        while time.time() < deadline:
            data = bytes(self.dev.read(64, 300))
            if len(data) >= 6 and data[0] == 0xA5 and data[1] == 0x41 and data[4] == selector:
                size = data[3]
                if size < min_len + 1 or len(data) < 5 + size:
                    raise ScreenError("short read reply")
                return data[5:4 + size]
        raise ScreenError("read reply timeout")

    def status(self):
        info = self._query(0x14, 11)
        width, height = struct.unpack_from("<HH", info, 4)
        space = struct.unpack_from("<I", self._query(0x10, 4), 0)[0]
        return {
            "width": width,
            "height": height,
            "support_jpg": info[10] == 1,
            "space": space,
        }


    # ------------------------------------------------------------- dfu
    def enter_dfu(self, settle=0.7):
        """Ask the screen firmware to reboot into its DFU bootloader."""
        prepare = bytes([0x07, 0x03, 0x01, 0x20])
        tail = bytes([0x13, 0x02, 0x00, 0x00, 0x00, 0x00, 0x78, 0xB7])
        if not self.dev:
            self.open()
        for payload, wait in ((prepare, settle), (tail, 0.3)):
            buf = bytearray(65)
            buf[1:1 + len(payload)] = payload
            self.dev.write(bytes(buf))
            time.sleep(wait)
        return True

    # ---------------------------------------------------------------- write
    def push(self, jpeg: bytes, timeout=1.5):
        if len(jpeg) < 4 or jpeg[0:2] != b"\xff\xd8":
            raise ScreenError("frame is not a JPEG")
        stream = build_stream(jpeg, 480, 360)
        t0 = time.time()
        reports = 0
        for report, needs_ack in frames(stream):
            self.dev.write(report)
            reports += 1
            if needs_ack:
                self._wait_ack(timeout)
        return {"ms": int((time.time() - t0) * 1000), "reports": reports, "bytes": len(stream)}

    def _wait_ack(self, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = bytes(self.dev.read(64, 200))
            if len(data) >= 7 and data[0] == 0xBA:
                if data[6] != 0xFE:
                    raise ScreenError("device rejected image block")
                return
        raise ScreenError("ack timeout")
