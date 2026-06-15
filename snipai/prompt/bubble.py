"""Floating input bubble shown anchored to the captured selection.

User types prompt, press Enter -> emits `submitted(prompt, png)`.
Esc cancels. Shift+Enter inserts newline.

Cluely AI-inspired design: glassmorphism, gradient accents, drop shadow.
"""
from __future__ import annotations
from PySide6.QtCore import Qt, QRect, Signal
from PySide6.QtGui import QGuiApplication, QPixmap, QKeyEvent, QImage, QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTextEdit, QPushButton,
    QSizePolicy, QGraphicsDropShadowEffect,
)


class _PromptEdit(QTextEdit):
    submitted = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setPlaceholderText("Ask AI about this selection...")
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                super().keyPressEvent(e)
                return
            self.submitted.emit()
            return
        super().keyPressEvent(e)


class PromptBubble(QWidget):
    submitted = Signal(str, bytes)   # prompt, png
    cancelled = Signal()

    BUBBLE_W = 480
    THUMB_MAX = 110

    def __init__(self, anchor: QRect, png: bytes, parent=None):
        super().__init__(parent)
        self.png = png
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        self._build_ui()
        self._load_thumb(png)
        self._position_near(anchor)

    # ---------------- UI ----------------
    def _build_ui(self) -> None:
        # Drop shadow on the outer container
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 8)
        shadow.setColor(QColor(0, 0, 0, 160))

        self.setStyleSheet("""
            QWidget#bubble {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #252a3a, stop:1 #1c2030);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
            QLabel#thumb {
                background: #141820;
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 12px;
            }
            QLabel#brand {
                color: #7c8aff;
                font-size: 9pt;
                font-weight: 600;
                letter-spacing: 1px;
            }
            QLabel#hint {
                color: #5a6070;
                font-size: 8pt;
            }
            QTextEdit {
                background: #141820;
                color: #e8eaf0;
                border: 1px solid rgba(255, 255, 255, 0.06);
                border-radius: 12px;
                padding: 10px 14px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 11pt;
                selection-background-color: #4a6aff;
            }
            QTextEdit:focus {
                border: 1px solid rgba(100, 130, 255, 0.4);
            }
            QPushButton#send {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #5b6aff, stop:1 #8b5cf6);
                color: white;
                border: none;
                border-radius: 10px;
                padding: 8px 20px;
                font-weight: 700;
                font-size: 10pt;
                letter-spacing: 0.5px;
            }
            QPushButton#send:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #6b7aff, stop:1 #9b6cf6);
            }
            QPushButton#send:pressed {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4b5aff, stop:1 #7b4cf6);
            }
            QPushButton#cancel {
                background: rgba(255, 255, 255, 0.05);
                color: #8a90a0;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 10px;
                padding: 8px 16px;
                font-size: 10pt;
            }
            QPushButton#cancel:hover {
                background: rgba(255, 255, 255, 0.1);
                color: #b0b6c6;
            }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        container = QWidget(self)
        container.setObjectName("bubble")
        container.setGraphicsEffect(shadow)
        outer.addWidget(container)

        v = QVBoxLayout(container)
        v.setContentsMargins(16, 14, 16, 14)
        v.setSpacing(10)

        # Top row: brand label
        brand = QLabel("SNIP AI", objectName="brand")
        v.addWidget(brand)

        # Content row: thumbnail + editor
        content = QHBoxLayout()
        content.setSpacing(12)

        self.thumb = QLabel(objectName="thumb")
        self.thumb.setFixedSize(self.THUMB_MAX, self.THUMB_MAX)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content.addWidget(self.thumb, 0)

        self.edit = _PromptEdit()
        self.edit.setMinimumHeight(self.THUMB_MAX)
        self.edit.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.edit.submitted.connect(self._submit)
        content.addWidget(self.edit, 1)
        v.addLayout(content)

        # Hint row
        hint = QLabel("Enter to send  ·  Shift+Enter for newline  ·  Esc to cancel", objectName="hint")
        v.addWidget(hint)

        # Button row
        btns = QHBoxLayout()
        btns.setSpacing(8)
        btns.addStretch(1)
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setObjectName("cancel")
        self.btn_cancel.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_cancel.clicked.connect(self._cancel)
        btns.addWidget(self.btn_cancel)
        self.btn_send = QPushButton("Ask AI  →")
        self.btn_send.setObjectName("send")
        self.btn_send.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_send.clicked.connect(self._submit)
        btns.addWidget(self.btn_send)
        v.addLayout(btns)

        self.setFixedWidth(self.BUBBLE_W + 32)  # account for outer margins

    def _load_thumb(self, png: bytes) -> None:
        dpr = float(QGuiApplication.primaryScreen().devicePixelRatio()) or 1.0
        target_px = int(self.THUMB_MAX * dpr)
        img = QImage.fromData(png, "PNG")
        pix = QPixmap.fromImage(img).scaled(
            target_px, target_px,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pix.setDevicePixelRatio(dpr)
        self.thumb.setPixmap(pix)

    def _position_near(self, anchor: QRect) -> None:
        self.adjustSize()
        size = self.sizeHint()
        screen = QGuiApplication.screenAt(anchor.center())
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        sg = screen.availableGeometry()

        # Prefer below selection
        x = anchor.x()
        y = anchor.y() + anchor.height() + 12

        if y + size.height() > sg.bottom():
            y = anchor.y() - size.height() - 12
        if y < sg.top():
            y = sg.top() + 12
        if x + size.width() > sg.right():
            x = sg.right() - size.width() - 12
        if x < sg.left():
            x = sg.left() + 12
        self.move(x, y)

    # ---------------- events ----------------
    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        super().keyPressEvent(e)

    def showEvent(self, e):
        super().showEvent(e)
        self.edit.setFocus()

    # ---------------- actions ----------------
    def _submit(self) -> None:
        text = self.edit.toPlainText().strip()
        if not text:
            text = "Describe and analyze this."
        self.submitted.emit(text, self.png)
        self.close()

    def _cancel(self) -> None:
        self.cancelled.emit()
        self.close()
