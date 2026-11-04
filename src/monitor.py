#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PC resource monitor: CPU / RAM / GPU / disk / network."""
import subprocess
import threading
import time

_last_net = {"t": 0.0, "recv": 0, "sent": 0}


class GpuSampler(threading.Thread):
    """Keeps a `typeperf` process alive and sums the 3D engine counters."""

    def __init__(self):
        super().__init__(daemon=True)
        self.util = None
        self.ready = False
        self._proc = None
        self._cols = None

    def run(self):
        try:
            self._proc = subprocess.Popen(
                ["typeperf", r"\GPU Engine(*)\Utilization Percentage", "-si", "2"],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, encoding="mbcs", errors="ignore",
                creationflags=0x08000000)
        except Exception:
            return
        for line in self._proc.stdout:
            line = line.strip()
            if not line:
                continue
            if line.startswith('"(PDH-CSV'):
                parts = [p for p in line.split('","')]
                self._cols = [i for i, p in enumerate(parts) if "engtype_3D" in p]
                self.ready = True
                continue
            if not self._cols:
                continue
            parts = line.split('","')
            total = 0.0
            for i in self._cols:
                if i >= len(parts):
                    continue
                try:
                    total += float(parts[i].strip('"'))
                except Exception:
                    pass
            self.util = round(min(100.0, total), 1)

    def stop(self):
        try:
            if self._proc:
                self._proc.kill()
        except Exception:
            pass


GPU = GpuSampler()


def start_gpu():
    if not GPU.is_alive():
        GPU.start()
        time.sleep(0.4)


def stop_gpu():
    GPU.stop()


def gpu_util():
    return GPU.util


def snapshot():
    """One reading of every metric; cheap except the very first GPU sample."""
    out = {"cpu": None, "mem": None, "disk": None, "down": None, "up": None,
           "gpu": GPU.util, "uptime": None}
    try:
        import psutil
        out["cpu"] = psutil.cpu_percent(interval=None)
        m = psutil.virtual_memory()
        out["mem"] = (m.percent, round(m.used / (1024 ** 3), 1), round(m.total / (1024 ** 3), 1))
        try:
            d = psutil.disk_usage("C:\\")
            out["disk"] = (d.percent, round(d.used / (1024 ** 3)), round(d.total / (1024 ** 3)))
        except Exception:
            pass
        now = time.time()
        counters = psutil.net_io_counters()
        if _last_net["t"]:
            dt = max(0.1, now - _last_net["t"])
            out["down"] = max(0.0, (counters.bytes_recv - _last_net["recv"]) / dt)
            out["up"] = max(0.0, (counters.bytes_sent - _last_net["sent"]) / dt)
        _last_net.update({"t": now, "recv": counters.bytes_recv, "sent": counters.bytes_sent})
        out["uptime"] = int(time.time() - psutil.boot_time())
    except Exception:
        pass
    return out


def human_rate(bps):
    if bps is None:
        return "—"
    if bps >= 1024 * 1024:
        return f"{bps / (1024*1024):.1f} MB/s"
    if bps >= 1024:
        return f"{bps / 1024:.0f} KB/s"
    return f"{bps:.0f} B/s"
