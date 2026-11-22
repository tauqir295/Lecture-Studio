"""Render SlideSpecs to a 1920x1080 (16:9) PDF with Qt — offline, topic-neutral theme."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

from PySide6.QtCore import QMarginsF, QRect, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QImage, QPageLayout, QPageSize, QPainter, QPdfWriter, QPen

from src.backend.content.model import BULLETS, CODE, HEADING, IMAGE, PARAGRAPH, QUOTE, TABLE, Block
from src.backend.content.slide_builder import SlideSpec

W, H = 1920, 1080
MX, TOP, BODY_TOP, BODY_BOTTOM = 110, 64, 250, 985
THEME = dict(bg="#0b1b2b", bg2="#10263b", ink="#ffffff", ink2="#c3d6e8", mut="#7f97ad", acc="#4fb3ff",
             hi="#ffc247", code_bg="#050f19", code_ink="#e8f3ff", line="#1d3650")
SANS = ["Helvetica Neue", "Arial", "Segoe UI", "DejaVu Sans"]
MONO = ["Menlo", "SF Mono", "Consolas", "DejaVu Sans Mono", "Courier New"]
MIN_SCALE = 0.72


def _ensure_app():
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QGuiApplication
    if QGuiApplication.instance() is None:
        QApplication(sys.argv[:1] or ["deck"])


def _font(families, px: int, bold=False) -> QFont:
    f = QFont()
    f.setFamilies(families)
    f.setPixelSize(max(int(px), 8))
    f.setBold(bold)
    return f


class _Page:
    def __init__(self, painter: QPainter):
        self.p = painter

    def text_height(self, text: str, font: QFont, width: int) -> int:
        fm = QFontMetrics(font)
        r = fm.boundingRect(QRect(0, 0, width, 100000), Qt.TextWordWrap, text)
        return r.height()

    def draw_text(self, x, y, w, text, font, color, flags=Qt.TextWordWrap) -> int:
        h = self.text_height(text, font, w)
        self.p.setFont(font)
        self.p.setPen(QColor(color))
        self.p.drawText(QRect(int(x), int(y), int(w), int(h) + 4), flags, text)
        return h


def _element_height(pg: _Page, el: Block, s: float, width: int) -> int:
    return _draw_element(pg, el, s, MX, 0, width, measure=True)


def _draw_element(pg: _Page, el: Block, s: float, x: int, y: int, width: int, measure=False) -> int:
    """Draw (or measure) one element; returns its height."""
    p = pg.p
    if el.kind in (PARAGRAPH, QUOTE, HEADING):
        f = _font(SANS, (44 if el.kind != HEADING else 46) * s, bold=el.kind == HEADING)
        indent = 34 if el.kind == QUOTE else 0
        h = pg.text_height(el.text, f, width - indent)
        if not measure:
            if el.kind == QUOTE:
                p.fillRect(QRect(x, y, 8, h), QColor(THEME["acc"]))
            pg.draw_text(x + indent, y, width - indent, el.text, f, THEME["ink2"] if el.kind != HEADING else THEME["hi"])
        return h + int(26 * s)
    if el.kind == BULLETS:
        f = _font(SANS, 44 * s)
        total = 0
        for n, raw in enumerate(el.items, 1):
            level = (len(raw) - len(raw.lstrip(" "))) // 2
            item = raw.strip()
            ind = int((60 + 50 * level) * s)
            h = pg.text_height(item, f, width - ind)
            if not measure:
                cy = y + total
                if el.numbered and level == 0:
                    pg.draw_text(x, cy, ind, f"{n}.", _font(SANS, 40 * s, True), THEME["acc"], Qt.AlignLeft)
                else:
                    d = int(16 * s)
                    p.fillRect(QRect(x + ind - int(38 * s), cy + int(20 * s), d, d),
                               QColor(THEME["acc"] if level == 0 else THEME["mut"]))
                pg.draw_text(x + ind, cy, width - ind, item, f, THEME["ink"])
            total += h + int(22 * s)
        return total + int(10 * s)
    if el.kind == CODE:
        f = _font(MONO, 30 * s)
        fm = QFontMetrics(f)
        cols = max(20, int((width - 60) / max(fm.horizontalAdvance("M"), 1)))
        lines = []
        for line in (el.text.expandtabs(4).splitlines() or [""]):
            while len(line) > cols:
                lines.append(line[:cols]); line = "  ↪ " + line[cols:]
            lines.append(line)
        lh = fm.lineSpacing() + int(4 * s)
        label_h = int(34 * s) if el.language else int(10 * s)
        h = label_h + lh * len(lines) + int(40 * s)
        if not measure:
            p.setPen(QPen(QColor("#1f3b57"), 3))
            p.setBrush(QColor(THEME["code_bg"]))
            p.drawRoundedRect(QRectF(x, y, width, h), 18, 18)
            if el.language:
                pg.draw_text(x + 28, y + 14, width, el.language.upper(), _font(SANS, 20 * s, True), THEME["mut"])
            p.setFont(f)
            for i, line in enumerate(lines):
                p.setPen(QColor(THEME["mut"] if line.lstrip().startswith(("#", "//", "--")) else THEME["code_ink"]))
                p.drawText(int(x + 30), int(y + label_h + 20 * s + i * lh + fm.ascent()), line)
        return h + int(24 * s)
    if el.kind == TABLE:
        rows = el.rows
        f, fb = _font(SANS, 30 * s), _font(SANS, 30 * s, True)
        ncol = max(len(r) for r in rows)
        weights = [max(4, max((len(r[c]) if c < len(r) else 0) for r in rows)) for c in range(ncol)]
        tot = sum(min(w, 40) for w in weights)
        widths = [int(width * min(w, 40) / tot) for w in weights]
        pad = int(14 * s)
        heights = [max(pg.text_height(r[c] if c < len(r) else "", fb if ri == 0 else f, widths[c] - 2 * pad)
                       for c in range(ncol)) + 2 * pad for ri, r in enumerate(rows)]
        if not measure:
            cy = y
            for ri, r in enumerate(rows):
                cx = x
                if ri == 0:
                    p.fillRect(QRect(x, cy, width, heights[0]), QColor("#16385a"))
                elif ri % 2 == 0:
                    p.fillRect(QRect(x, cy, width, heights[ri]), QColor(THEME["bg2"]))
                for c in range(ncol):
                    pg.draw_text(cx + pad, cy + pad, widths[c] - 2 * pad, r[c] if c < len(r) else "",
                                 fb if ri == 0 else f, THEME["ink"] if ri == 0 else THEME["ink2"])
                    cx += widths[c]
                cy += heights[ri]
                p.fillRect(QRect(x, cy - 1, width, 2), QColor(THEME["line"]))
        return sum(heights) + int(20 * s)
    if el.kind == IMAGE:
        return 0  # images are laid out by _draw_image_slide
    return 0


def _draw_frame(pg: _Page, spec: SlideSpec, n: int, total: int, footer: str) -> int:
    p = pg.p
    p.fillRect(QRect(0, 0, W, H), QColor(THEME["bg"]))
    y = TOP
    if spec.kicker:
        y += pg.draw_text(MX, y, W - 2 * MX, spec.kicker.upper(), _font(SANS, 24, True), THEME["acc"]) + 8
    title_font = _font(SANS, 64, True)
    if pg.text_height(spec.title, title_font, W - 2 * MX) > 160:
        title_font = _font(SANS, 52, True)
    y += pg.draw_text(MX, y, W - 2 * MX, spec.title, title_font, THEME["ink"])
    p.fillRect(QRect(MX, 1008, W - 2 * MX, 2), QColor(THEME["line"]))
    pg.draw_text(MX, 1024, 1200, footer, _font(SANS, 22), THEME["mut"], Qt.AlignLeft)
    pg.draw_text(W - MX - 200, 1024, 200, f"{n} / {total}", _font(SANS, 22), THEME["mut"], Qt.AlignRight)
    return max(BODY_TOP, y + 40)


def _draw_title_slide(pg: _Page, spec: SlideSpec, footer: str) -> None:
    p = pg.p
    p.fillRect(QRect(0, 0, W, H), QColor(THEME["bg"]))
    p.fillRect(QRect(MX - 30, 330, 12, 420), QColor(THEME["acc"]))
    y = 340
    if spec.kicker:
        y += pg.draw_text(MX, y, W - 2 * MX, spec.kicker, _font(SANS, 30, True), THEME["acc"]) + 20
    f = _font(SANS, 104, True)
    if pg.text_height(spec.title, f, W - 2 * MX) > 260:
        f = _font(SANS, 80, True)
    y += pg.draw_text(MX, y, W - 2 * MX, spec.title, f, THEME["ink"]) + 30
    for el in spec.elements:
        pg.draw_text(MX, y, W - 2 * MX - 200, el.text, _font(SANS, 44), THEME["ink2"])
    pg.draw_text(MX, 1024, 1200, footer, _font(SANS, 22), THEME["mut"], Qt.AlignLeft)


def _draw_image_slide(pg: _Page, spec: SlideSpec, top: int) -> List[str]:
    warnings = []
    el = spec.elements[0]
    caption_h = pg.text_height(el.text, _font(SANS, 36), W - 2 * MX) + 20 if el.text else 0
    box = QRect(MX, top, W - 2 * MX, BODY_BOTTOM - top - caption_h)
    img = QImage(str(el.image_path)) if el.image_path else QImage()
    if img.isNull():
        pg.p.fillRect(box, QColor(THEME["bg2"]))
        pg.draw_text(box.x(), box.center().y() - 30, box.width(), "[image not available]",
                     _font(SANS, 36), THEME["mut"], Qt.AlignHCenter)
        warnings.append(f"Image could not be loaded on slide '{spec.title}'.")
    else:
        scaled = img.size().scaled(box.size(), Qt.KeepAspectRatio)
        if img.width() < box.width() // 3 and img.height() < box.height() // 3:  # don't over-upscale tiny images
            scaled = img.size() * 2
        target = QRect(box.x() + (box.width() - scaled.width()) // 2, box.y() + (box.height() - scaled.height()) // 2,
                       scaled.width(), scaled.height())
        pg.p.drawImage(target, img)
    if el.text:
        pg.draw_text(MX, BODY_BOTTOM - caption_h + 10, W - 2 * MX, el.text, _font(SANS, 36), THEME["ink2"],
                     Qt.AlignHCenter | Qt.TextWordWrap)
    return warnings


def render_pdf(slides: List[SlideSpec], out_pdf: Path, footer: str) -> List[str]:
    """Write all slides to `out_pdf`. Returns layout warnings (e.g. content had to be shrunk)."""
    _ensure_app()
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    writer = QPdfWriter(str(out_pdf))
    writer.setPageLayout(QPageLayout(QPageSize(QSizeF(1440, 810), QPageSize.Point), QPageLayout.Portrait,
                                     QMarginsF(0, 0, 0, 0)))
    writer.setResolution(96)
    writer.setTitle(footer)
    warnings: List[str] = []
    p = QPainter(writer)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.TextAntialiasing)
    pg = _Page(p)
    try:
        for n, spec in enumerate(slides, 1):
            if n > 1:
                writer.newPage()
            if spec.kind == "title":
                _draw_title_slide(pg, spec, footer)
                continue
            top = _draw_frame(pg, spec, n, len(slides), footer)
            if spec.kind == "image":
                warnings += _draw_image_slide(pg, spec, top)
                continue
            width = W - 2 * MX
            avail = BODY_BOTTOM - top
            scale = 1.0
            while scale > MIN_SCALE and sum(_element_height(pg, e, scale, width) for e in spec.elements) > avail:
                scale -= 0.04
            used = sum(_element_height(pg, e, scale, width) for e in spec.elements)
            if used > avail:
                warnings.append(f"Slide {n} '{spec.title}' is very dense; some content may be clipped.")
            y = top + max(0, (avail - used) // 3) if spec.kind == "content" else top
            p.save()
            p.setClipRect(QRect(0, top - 10, W, BODY_BOTTOM - top + 20))
            for e in spec.elements:
                y += _draw_element(pg, e, scale, MX, y, width)
            p.restore()
    finally:
        p.end()
    return warnings
