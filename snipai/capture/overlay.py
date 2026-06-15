"""Full-screen frameless overlay with rubber-band selection.

Sizing uses Qt screen geometry (logical coords). Pixmap stretched to
widget rect, so DPI mismatches don't cause magnification.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, QPoint, Signal, QSize
from PySide6.QtGui import (
    QPainter, QColor, QPen, QBrush, QFont, QGuiApplication, QKeyEvent,
    QMouseEvent, QPaintEvent, QCursor,
)
from PySide6.QtWidgets import QWidget

from .screenshot import Snapshot, crop_png_bytes


class CaptureOverlay(QWidget):
    selected = Signal(QRect, bytes)   # (logical virtual-desktop rect, png bytes)
    cancelled = Signal()

    def __init__(self, snap: Snapshot, parent=None):
        super().__init__(parent)
        self.snap = snap
        self._origin: QPoint | None = None
        self._current: QPoint | None = None
        self._dragging = False

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        self.setMouseTracking(True)

        # Use Qt's virtual desktop geometry (logical, DPI-correct).
        vg = QRect()
        for s in QGuiApplication.screens():
            vg = vg.united(s.geometry())
        self._virtual_geom = vg
        self.setGeometry(vg)

    # ---------------- paint ----------------
    def paintEvent(self, _: QPaintEvent) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        # Stretch snapshot to fill widget rect — avoids any DPI scaling mismatch.
        p.drawPixmap(self.rect(), self.snap.pixmap, self.snap.pixmap.rect())

        # Dim entire screen
        p.fillRect(self.rect(), QColor(0, 0, 0, 110))

        sel = self._selection_rect_local()
        if sel is not None and sel.width() > 0 and sel.height() > 0:
            # Cut-out: redraw original snapshot inside selection (source rect scaled)
            src = self._widget_to_pixmap(sel)
            p.drawPixmap(sel, self.snap.pixmap, src)

            pen = QPen(QColor(50, 160, 255), 2)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel)

            # Dimensions label
            label = f"{sel.width()} × {sel.height()}"
            p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            metrics = p.fontMetrics()
            tw = metrics.horizontalAdvance(label) + 12
            th = metrics.height() + 6
            lx = sel.x()
            ly = sel.y() - th - 4
            if ly < 0:
                ly = sel.y() + 4
            p.fillRect(lx, ly, tw, th, QColor(0, 0, 0, 200))
            p.setPen(QColor(255, 255, 255))
            p.drawText(lx + 6, ly + th - 6, label)
        else:
            # Hint text
            hint = "Drag to select  •  Esc to cancel"
            p.setFont(QFont("Segoe UI", 14, QFont.Weight.Medium))
            p.setPen(QColor(255, 255, 255, 220))
            r = self.rect()
            p.drawText(r.center().x() - 140, r.center().y(), hint)
        p.end()

    def _widget_to_pixmap(self, r: QRect) -> QRect:
        """Map widget-local rect to source-pixmap rect (handles size mismatch)."""
        w_widget = max(1, self.width())
        h_widget = max(1, self.height())
        pm = self.snap.pixmap
        # Use logical size of pixmap (size() honors devicePixelRatio).
        pm_w = pm.size().width()
        pm_h = pm.size().height()
        sx = pm_w / w_widget
        sy = pm_h / h_widget
        return QRect(
            int(r.x() * sx), int(r.y() * sy),
            int(r.width() * sx), int(r.height() * sy),
        )

    # ---------------- mouse ----------------
    def mousePressEvent(self, e: QMouseEvent) -> None:
        if e.button() == Qt.MouseButton.LeftButton:
            self._origin = e.position().toPoint()
            self._current = self._origin
            self._dragging = True
            self.update()
        elif e.button() == Qt.MouseButton.RightButton:
            self._cancel()

    def mouseMoveEvent(self, e: QMouseEvent) -> None:
        if self._dragging:
            self._current = e.position().toPoint()
            self.update()

    def mouseReleaseEvent(self, e: QMouseEvent) -> None:
        if e.button() != Qt.MouseButton.LeftButton or not self._dragging:
            return
        self._dragging = False
        sel = self._selection_rect_local()
        if sel is None or sel.width() < 5 or sel.height() < 5:
            self._cancel()
            return
        # Translate widget-local -> Qt virtual-desktop logical coords.
        global_rect = QRect(
            sel.x() + self._virtual_geom.x(),
            sel.y() + self._virtual_geom.y(),
            sel.width(),
            sel.height(),
        )
        png = crop_png_bytes(self.snap, global_rect)
        self.selected.emit(global_rect, png)
        self.close()

    # ---------------- key ----------------
    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self._cancel()

    # ---------------- helpers ----------------
    def _selection_rect_local(self) -> QRect | None:
        if self._origin is None or self._current is None:
            return None
        return QRect(self._origin, self._current).normalized()

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.close()
