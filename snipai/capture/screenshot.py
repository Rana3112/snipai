"""Screen capture via mss. DPI-aware via Qt geometry, not pixmap tagging.

mss returns PHYSICAL pixels. We keep pixmap untagged (no devicePixelRatio).
The overlay paints by stretching pixmap to widget rect — widget rect is
sized from Qt's logical screen geometry, so the result fits the actual
screen at every DPI.
"""
from __future__ import annotations
from dataclasses import dataclass
import mss
from PIL import Image
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPixmap, QGuiApplication


@dataclass
class Snapshot:
    pixmap: QPixmap          # physical-pixel snapshot (no dpr tag)
    rect: QRect              # LOGICAL virtual desktop rect (from Qt)
    pil_image: Image.Image   # physical-resolution PIL copy
    dpr: float               # physical / logical


def _qt_virtual_geometry() -> QRect:
    vg = QRect()
    for s in QGuiApplication.screens():
        vg = vg.united(s.geometry())
    return vg


def grab_virtual_desktop() -> Snapshot:
    qt_rect = _qt_virtual_geometry()  # logical
    with mss.mss() as sct:
        mon = sct.monitors[0]  # union of all monitors, physical pixels
        raw = sct.grab(mon)
        pil = Image.frombytes("RGB", raw.size, raw.rgb)
        data = pil.tobytes("raw", "RGB")
        qimg = QImage(
            data, pil.width, pil.height, pil.width * 3,
            QImage.Format.Format_RGB888,
        ).copy()
        pix = QPixmap.fromImage(qimg)  # untagged

    # dpr = physical pixels per logical pixel (use width as primary axis)
    dpr = pil.width / qt_rect.width() if qt_rect.width() else 1.0
    return Snapshot(pixmap=pix, rect=qt_rect, pil_image=pil, dpr=dpr)


def crop_png_bytes(snap: Snapshot, sel_logical: QRect) -> bytes:
    """Crop selection. `sel_logical` is in LOGICAL (Qt) virtual-desktop coords."""
    import io
    dpr = snap.dpr
    phys_x = int(round((sel_logical.x() - snap.rect.x()) * dpr))
    phys_y = int(round((sel_logical.y() - snap.rect.y()) * dpr))
    phys_w = int(round(sel_logical.width() * dpr))
    phys_h = int(round(sel_logical.height() * dpr))
    box = (phys_x, phys_y, phys_x + phys_w, phys_y + phys_h)
    cropped = snap.pil_image.crop(box)
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()
