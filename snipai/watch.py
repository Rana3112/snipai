"""Region watch — pin a screen region, poll it, alert when its content changes.

Pure-local: grabs the region via mss every `interval` seconds, computes a small
perceptual fingerprint (16x16 grayscale), and emits `changed` when the
fingerprint diverges past a threshold. No model calls while idle.
"""
from __future__ import annotations
import logging
import time
from PySide6.QtCore import QThread, Signal

log = logging.getLogger(__name__)


def _fingerprint(rgb: bytes, w: int, h: int) -> list[int]:
    """Downscale to 16x16 grayscale buckets — cheap change detector."""
    from PIL import Image
    img = Image.frombytes("RGB", (w, h), rgb).convert("L").resize((16, 16))
    return list(img.getdata())


def _distance(a: list[int], b: list[int]) -> float:
    if not a or not b or len(a) != len(b):
        return 1.0
    diff = sum(abs(x - y) for x, y in zip(a, b))
    return diff / (len(a) * 255.0)


def logical_rect_to_box(sel_logical, snap) -> dict:
    """Convert a logical Qt selection rect to a physical-pixel mss box."""
    import mss
    with mss.mss() as sct:
        mon = sct.monitors[0]
    dpr = snap.dpr or 1.0
    left = mon["left"] + int(round((sel_logical.x() - snap.rect.x()) * dpr))
    top = mon["top"] + int(round((sel_logical.y() - snap.rect.y()) * dpr))
    w = max(1, int(round(sel_logical.width() * dpr)))
    h = max(1, int(round(sel_logical.height() * dpr)))
    return {"left": left, "top": top, "width": w, "height": h}


class RegionWatcher(QThread):
    """Watches one physical-pixel box. Emits `changed(png_bytes)` on change."""

    changed = Signal(bytes)
    error = Signal(str)

    def __init__(self, box: dict, interval: float = 5.0,
                 threshold: float = 0.06, label: str = "", parent=None):
        super().__init__(parent)
        self.box = box            # {"left","top","width","height"} physical px
        self.interval = max(1.0, interval)
        self.threshold = threshold
        self.label = label or "region"
        self._stop = False

    def stop(self) -> None:
        self._stop = True
        self.requestInterruption()

    def _grab_png(self, sct) -> tuple[bytes, list[int], int, int]:
        import io
        from PIL import Image
        raw = sct.grab(self.box)
        pil = Image.frombytes("RGB", raw.size, raw.rgb)
        buf = io.BytesIO()
        pil.save(buf, format="PNG")
        fp = _fingerprint(pil.tobytes("raw", "RGB"), pil.width, pil.height)
        return buf.getvalue(), fp, pil.width, pil.height

    def run(self) -> None:
        try:
            import mss
            with mss.mss() as sct:
                _, baseline, _, _ = self._grab_png(sct)
                while not self._stop and not self.isInterruptionRequested():
                    # sleep in small slices so stop() is responsive
                    slept = 0.0
                    while slept < self.interval:
                        if self._stop or self.isInterruptionRequested():
                            return
                        time.sleep(0.2)
                        slept += 0.2

                    png, fp, _, _ = self._grab_png(sct)
                    if _distance(baseline, fp) >= self.threshold:
                        log.info("region '%s' changed", self.label)
                        baseline = fp
                        self.changed.emit(png)
        except Exception as e:
            log.exception("region watcher failed")
            self.error.emit(str(e))
