#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Crop / zoom dialog for background and idle images."""
import tkinter as tk

from PIL import Image, ImageTk

BG = "#0A0C10"
CARD = "#12161F"
FG = "#F2F4F8"
MUTED = "#8A93A6"
DIM = "#5B6478"
ACCENT = "#4D6BFE"
FONT = "Microsoft YaHei UI"


class CropDialog(tk.Toplevel):
    """Pick which 480x360 region of an image to show, with zoom and pan."""

    FW, FH = 400, 300          # crop frame on the canvas
    CW, CH = 480, 372          # canvas size

    def __init__(self, master, path, crop=None, title="调整画面区域"):
        super().__init__(master)
        self.title(title)
        self.configure(bg=BG)
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        try:
            self.iconbitmap(master.winfo_toplevel().iconbitmap())
        except Exception:
            pass

        self.result = None
        self.img = Image.open(path).convert("RGB")
        self._photo = None
        self._job = None
        self.X0 = (self.CW - self.FW) // 2
        self.Y0 = 22

        self.s_min = max(self.FW / self.img.width, self.FH / self.img.height)
        if crop:
            x0, y0, x1, y1 = crop
            self.s = self.FW / max(1e-6, (x1 - x0) * self.img.width)
            self.s = max(self.s, self.s_min)
            self.ox = self.X0 - x0 * self.img.width * self.s
            self.oy = self.Y0 - y0 * self.img.height * self.s
        else:
            self.s = self.s_min
            self.ox = self.X0 + (self.FW - self.img.width * self.s) / 2
            self.oy = self.Y0 + (self.FH - self.img.height * self.s) / 2

        self._build()
        self._clamp()
        self._render()

    # ------------------------------------------------------------------ ui
    def _build(self):
        tk.Label(self, text="拖动图片选择显示区域，滚轮或滑杆缩放", bg=BG, fg=MUTED,
                 font=(FONT, 9)).pack(pady=(12, 6))

        self.canvas = tk.Canvas(self, width=self.CW, height=self.CH, bg="#000000",
                                highlightthickness=0, cursor="fleur")
        self.canvas.pack(padx=16)
        self.canvas.bind("<Button-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<MouseWheel>", self._wheel)

        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=16, pady=(10, 0))
        tk.Label(bar, text="缩放", bg=BG, fg=MUTED, font=(FONT, 9)).pack(side="left")
        self.zoom = tk.Scale(bar, from_=1.0, to=5.0, resolution=0.01, orient="horizontal",
                             showvalue=False, bg=BG, fg=FG, troughcolor=CARD,
                             highlightthickness=0, bd=0, command=self._set_zoom)
        self.zoom.set(round(self.s / self.s_min, 2))
        self.zoom.pack(side="left", fill="x", expand=True, padx=8)

        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=16, pady=12)
        tk.Label(row, text="画面比例固定 4:3（键盘屏幕 480×360）", bg=BG, fg=DIM,
                 font=(FONT, 8)).pack(side="left")
        tk.Button(row, text="重置", command=self._reset, bg=CARD, fg=FG, bd=0, relief="flat",
                  font=(FONT, 9), padx=12, pady=5, cursor="hand2").pack(side="right", padx=4)
        tk.Button(row, text="取消", command=self.destroy, bg=CARD, fg=FG, bd=0, relief="flat",
                  font=(FONT, 9), padx=12, pady=5, cursor="hand2").pack(side="right", padx=4)
        tk.Button(row, text="确定", command=self._ok, bg=ACCENT, fg="#FFFFFF", bd=0, relief="flat",
                  font=(FONT, 9, "bold"), padx=16, pady=5, cursor="hand2").pack(side="right", padx=4)

        self.update_idletasks()
        try:
            px = self.master.winfo_rootx() + (self.master.winfo_width() - self.winfo_width()) // 2
            py = self.master.winfo_rooty() + (self.master.winfo_height() - self.winfo_height()) // 2
            self.geometry(f"+{max(0, px)}+{max(0, py)}")
        except Exception:
            pass

    # ------------------------------------------------------------- geometry
    def _clamp(self):
        w = self.img.width * self.s
        h = self.img.height * self.s
        self.ox = min(self.X0, max(self.X0 + self.FW - w, self.ox))
        self.oy = min(self.Y0, max(self.Y0 + self.FH - h, self.oy))

    def _press(self, event):
        self._drag_from = (event.x, event.y, self.ox, self.oy)

    def _drag(self, event):
        if not self._drag_from:
            return
        x0, y0, ox, oy = self._drag_from
        self.ox = ox + (event.x - x0)
        self.oy = oy + (event.y - y0)
        self._clamp()
        self._render()

    def _wheel(self, event):
        factor = 1.1 if event.delta > 0 else 1 / 1.1
        self._zoom_by(factor)

    def _set_zoom(self, value):
        self._zoom_by(float(value) / max(1e-6, self.s / self.s_min), absolute=True,
                      target=self.s_min * float(value))

    def _zoom_by(self, factor, absolute=False, target=None):
        new_s = target if absolute else self.s * factor
        new_s = max(self.s_min, min(self.s_min * 6, new_s))
        cx = self.X0 + self.FW / 2
        cy = self.Y0 + self.FH / 2
        ix = (cx - self.ox) / self.s
        iy = (cy - self.oy) / self.s
        self.s = new_s
        self.ox = cx - ix * self.s
        self.oy = cy - iy * self.s
        self._clamp()
        self.zoom.set(round(self.s / self.s_min, 2))
        self._render()

    def _reset(self):
        self.s = self.s_min
        self.ox = self.X0 + (self.FW - self.img.width * self.s) / 2
        self.oy = self.Y0 + (self.FH - self.img.height * self.s) / 2
        self._clamp()
        self.zoom.set(1.0)
        self._render()

    # --------------------------------------------------------------- draw
    def _render(self):
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(16, self._draw)

    def _draw(self):
        self._job = None
        c = self.canvas
        c.delete("all")
        w = max(1, int(self.img.width * self.s))
        h = max(1, int(self.img.height * self.s))
        disp = self.img.resize((w, h), Image.LANCZOS)
        self._photo = ImageTk.PhotoImage(disp)
        c.create_image(int(self.ox), int(self.oy), image=self._photo, anchor="nw")

        x0, y0 = self.X0, self.Y0
        x1, y1 = x0 + self.FW, y0 + self.FH
        for rect in ((0, 0, self.CW, y0), (0, y1, self.CW, self.CH),
                     (0, y0, x0, y1), (x1, y0, self.CW, y1)):
            c.create_rectangle(*rect, fill="#000000", stipple="gray50", outline="")
        c.create_rectangle(x0, y0, x1, y1, outline="#FFFFFF", width=2)
        for (cx, cy) in ((x0, y0), (x1, y0), (x0, y1), (x1, y1)):
            c.create_rectangle(cx - 6, cy - 6, cx + 6, cy + 6, fill="#FFFFFF", outline="")

    def _ok(self):
        iw, ih = self.img.size
        x0 = max(0.0, (self.X0 - self.ox) / (iw * self.s))
        y0 = max(0.0, (self.Y0 - self.oy) / (ih * self.s))
        x1 = min(1.0, (self.X0 + self.FW - self.ox) / (iw * self.s))
        y1 = min(1.0, (self.Y0 + self.FH - self.oy) / (ih * self.s))
        if x1 - x0 < 0.02 or y1 - y0 < 0.02:
            x0, y0, x1, y1 = 0.0, 0.0, 1.0, 1.0
        self.result = [round(x0, 4), round(y0, 4), round(x1, 4), round(y1, 4)]
        self.destroy()


def preview_thumb(path, crop, size=(104, 78)):
    """Small preview of the chosen region, for the settings rows."""
    from PIL import Image as _Image
    img = _Image.open(path).convert("RGB")
    if crop:
        x0, y0, x1, y1 = crop
        img = img.crop((int(x0 * img.width), int(y0 * img.height),
                        int(x1 * img.width), int(y1 * img.height)))
    scale = max(size[0] / img.width, size[1] / img.height)
    img = img.resize((max(1, int(img.width * scale)), max(1, int(img.height * scale))), _Image.LANCZOS)
    left = (img.width - size[0]) // 2
    top = (img.height - size[1]) // 2
    return img.crop((left, top, left + size[0], top + size[1]))
