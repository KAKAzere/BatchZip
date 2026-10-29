from collections import OrderedDict

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPainterPath,
                           QPalette, QPen, QPixmap)
from PySide6.QtWidgets import QStyledItemDelegate

from qfluentwidgets import FluentIcon, isDarkTheme, qconfig

from ui.product_ui import paint_halo_bar
from ui.task_model import TaskQueueModel

# H.2-P PROTO-MARKER-DELEGATE: Fluent (Microsoft Store / Windows 11) card surface.


class TaskQueueDelegate(QStyledItemDelegate):
    """Paint the approved compact card without constructing an item widget.

    H.2-P adds a Fluent visual layer: a real card surface, restrained hover and
    pressed feedback, and state-dependent affordance emphasis.

    The two card caches are deliberately left untouched - their keys, bounds and
    counters are part of the validated hot path, so interaction state is drawn
    as a separate layer instead of being folded into a cache key.
    """

    ICONS = {
        "Queued": "◷", "Compressing": "◐", "Paused": "Ⅱ",
        "Completed": "✓", "Warning": "⚠", "Failed": "✕", "Cancelled": "■",
    }

    COLORS = {
        "Queued": ((95, 104, 117), (191, 197, 205)),
        "Compressing": ((15, 93, 218), (79, 163, 255)),
        "Paused": ((140, 90, 8), (240, 189, 101)),
        "Completed": ((35, 107, 64), (121, 201, 154)),
        "Warning": ((140, 90, 8), (240, 189, 101)),
        "Failed": ((161, 42, 42), (241, 154, 154)),
        "Cancelled": ((95, 104, 117), (191, 197, 205)),
    }

    # BatchZip brand accent, sampled from assets/icon/app_icon.svg. The running
    # and the standby states carry it; success, warning and danger keep their own
    # semantics so they stay distinguishable.
    ACCENT = (15, 93, 218)          # #0F5DDA
    ACCENT_LIGHT = (79, 163, 255)   # #4FA3FF

    # --- Fluent geometry: one radius language for every surface ---
    RADIUS = 8                 # card
    RADIUS_CONTROL = 6         # delete hover surface
    RADIUS_PILL = 11           # status badge capsule (22 px tall)

    # --- interaction states ---
    STATE_NORMAL = "normal"
    STATE_HOVER = "hover"
    STATE_PRESSED = "pressed"
    STATE_DRAG = "drag"
    STATE_LOCKED = "locked"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.paused = False
        self._delete_pixmaps = {}
        self._card_chrome = OrderedDict()
        self._full_cards = OrderedDict()
        self._full_card_hits = 0
        self._full_card_misses = 0
        self._full_card_evictions = 0
        self._full_card_bypasses = 0
        self._folder_by_task = {}
        self._grip_pixmaps = {}
        self._fonts = {}
        for compact in (False, True):
            grip = QFont("Segoe UI Symbol")
            grip.setPixelSize(14 if compact else 16)
            grip.setBold(True)
            icon = QFont("Segoe UI Emoji")
            icon.setPixelSize(18 if compact else 22)
            badge = QFont("Microsoft YaHei UI")
            badge.setPointSize(8 if compact else 9)
            badge.setWeight(QFont.Weight.DemiBold)
            title = QFont("Microsoft YaHei UI")
            title.setPointSize(10 if compact else 12)
            title.setBold(True)
            path = QFont("Microsoft YaHei UI")
            path.setPointSize(8 if compact else 9)
            self._fonts[compact] = (
                grip, icon, badge, QFontMetrics(badge),
                title, QFontMetrics(title), path, QFontMetrics(path),
            )
        model = parent.model()
        model.rowsInserted.connect(self._cache_folder_rows)
        model.rowsRemoved.connect(self._rebuild_folder_cache)
        model.modelReset.connect(self._rebuild_folder_cache)
        model.dataChanged.connect(self._folder_data_changed)
        self._rebuild_folder_cache()

    # -------------------------------------------------------- Fluent tokens
    @staticmethod
    def _mix(first, second, ratio):
        """Blend two colours; the only tuning knobs are ratios, not RGB literals."""
        ratio = 0.0 if ratio < 0.0 else (1.0 if ratio > 1.0 else ratio)
        return QColor(
            int(round(first.red() + (second.red() - first.red()) * ratio)),
            int(round(first.green() + (second.green() - first.green()) * ratio)),
            int(round(first.blue() + (second.blue() - first.blue()) * ratio)),
        )

    def _page_color(self, dark):
        """Page colour behind the queue, read from the window palette.

        qfluentwidgets paints the theme itself, so in dark mode the Qt palette
        can still report light values. The palette is therefore only trusted
        when it agrees with the active theme; otherwise a neutral base is used
        and the whole ramp is derived from it.
        """
        view = self.parent()
        window = view.window() if view is not None else None
        if window is not None:
            colour = window.palette().color(QPalette.ColorRole.Window)
            if colour.isValid() and colour.alpha() > 0 and colour.value() > 0:
                candidate = QColor(colour.red(), colour.green(), colour.blue())
                if (candidate.value() < 128) == bool(dark):
                    return candidate
        return QColor(32, 32, 32) if dark else QColor(243, 243, 243)

    def _accent_color(self, dark):
        """The live BatchZip accent.

        Read from the qfluentwidgets theme colour, which main.py sets to the
        brand blue, so the queue never carries a second accent of its own. The
        window palette is the fallback, and the icon-sampled constants are the
        last resort.
        """
        colour = qconfig.themeColor.value
        if colour.isValid() and colour.alpha() > 0:
            return QColor(colour.red(), colour.green(), colour.blue())
        view = self.parent()
        window = view.window() if view is not None else None
        if window is not None:
            colour = window.palette().color(QPalette.ColorRole.Highlight)
            if colour.isValid() and colour.alpha() > 0:
                candidate = QColor(colour.red(), colour.green(), colour.blue())
                if (candidate.value() < 128) == bool(dark):
                    return candidate
        return QColor(*self.ACCENT_LIGHT) if dark else QColor(*self.ACCENT)

    def _tokens(self, dark):
        """Surface ramp for one theme. Cards sit slightly above the page.

        hover/pressed are translucent subtle fills, not opaque surfaces: the
        feedback layer is painted over the finished card, so an opaque value
        would hide the title, path and badge underneath it.
        """
        page = self._page_color(dark)
        white = QColor(255, 255, 255)
        if dark:
            return {
                "surface": self._mix(page, white, 0.07),
                "stroke": QColor(255, 255, 255),
                "shadow": QColor(0, 0, 0),
            }
        return {
            "surface": self._mix(page, white, 0.92),
            "stroke": QColor(0, 0, 0),
            "shadow": QColor(0, 0, 0),
        }

    @staticmethod
    def _fill_alpha(state, dark):
        """Subtle-fill strength. Dark themes lighten on hover, light themes darken."""
        if state == TaskQueueDelegate.STATE_HOVER:
            return 20 if dark else 10
        if state == TaskQueueDelegate.STATE_PRESSED:
            return 10 if dark else 20
        return 0

    @staticmethod
    def _stroke_alpha(state):
        return {
            TaskQueueDelegate.STATE_NORMAL: 20,
            TaskQueueDelegate.STATE_HOVER: 46,
            TaskQueueDelegate.STATE_PRESSED: 34,
            TaskQueueDelegate.STATE_DRAG: 52,
            TaskQueueDelegate.STATE_LOCKED: 16,
        }.get(state, 20)

    @staticmethod
    def _grip_alpha(state):
        return {
            TaskQueueDelegate.STATE_NORMAL: 78,
            TaskQueueDelegate.STATE_HOVER: 140,
            TaskQueueDelegate.STATE_PRESSED: 150,
            TaskQueueDelegate.STATE_DRAG: 170,
            TaskQueueDelegate.STATE_LOCKED: 40,
        }.get(state, 78)

    @staticmethod
    def _delete_alpha(state):
        return {
            TaskQueueDelegate.STATE_NORMAL: 96,
            TaskQueueDelegate.STATE_HOVER: 165,
            TaskQueueDelegate.STATE_PRESSED: 175,
            TaskQueueDelegate.STATE_DRAG: 60,
            TaskQueueDelegate.STATE_LOCKED: 45,
        }.get(state, 96)

    # -------------------------------------------------------- folder caching
    def _cache_folder_rows(self, _parent, first, last):
        model = self.parent().model()
        for row in range(first, last + 1):
            index = model.index(row)
            task = model.data(index, TaskQueueModel.TaskRole)
            self._folder_by_task[id(task)] = bool(model.data(index, TaskQueueModel.IsFolderRole))

    def _rebuild_folder_cache(self, *_):
        self._folder_by_task.clear()
        model = self.parent().model()
        if model.rowCount():
            self._cache_folder_rows(None, 0, model.rowCount() - 1)

    def _folder_data_changed(self, first, last, roles):
        if not roles or any(role in roles for role in (
            TaskQueueModel.TaskRole, TaskQueueModel.PathRole, TaskQueueModel.IsFolderRole
        )):
            self._cache_folder_rows(None, first.row(), last.row())

    # ------------------------------------------------------------- pixmaps
    def _delete_pixmap(self, painter, dark, state):
        dpr = painter.device().devicePixelRatioF()
        key = (dark, state, dpr, 18)
        if key not in self._delete_pixmaps:
            pixels = max(1, round(18 * dpr))
            pixmap = QPixmap(pixels, pixels)
            pixmap.setDevicePixelRatio(pixels / 18)
            pixmap.fill(Qt.GlobalColor.transparent)
            base = QColor(255, 255, 255) if dark else QColor(32, 32, 32)
            colour = QColor(base)
            colour.setAlpha(self._delete_alpha(state))
            try:
                icon_painter = QPainter(pixmap)
                try:
                    FluentIcon.DELETE.icon(color=colour).paint(
                        icon_painter, QRect(0, 0, 18, 18)
                    )
                finally:
                    icon_painter.end()
            except (AttributeError, TypeError):
                pixmap = None
            self._delete_pixmaps[key] = pixmap
        return self._delete_pixmaps[key]

    def _grip_pixmap(self, painter, dark, state, compact):
        """Fluent drag handle: a six-dot grid, crisper than a glyph and font-free."""
        dpr = painter.device().devicePixelRatioF()
        width, height = 14, 18
        key = (dark, state, compact, dpr)
        pixmap = self._grip_pixmaps.get(key)
        if pixmap is None:
            pixmap = QPixmap(max(1, round(width * dpr)), max(1, round(height * dpr)))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.GlobalColor.transparent)
            grip_painter = QPainter(pixmap)
            try:
                grip_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                colour = QColor(255, 255, 255) if dark else QColor(32, 32, 32)
                colour.setAlpha(self._grip_alpha(state))
                grip_painter.setPen(Qt.PenStyle.NoPen)
                grip_painter.setBrush(colour)
                step = 5
                origin_x = (width - step) / 2.0
                origin_y = (height - 2 * step) / 2.0
                for column in range(2):
                    for row in range(3):
                        grip_painter.drawEllipse(
                            QRectF(origin_x + column * step - 1.15,
                                   origin_y + row * step - 1.15, 2.3, 2.3)
                        )
            finally:
                grip_painter.end()
            if len(self._grip_pixmaps) > 24:
                self._grip_pixmaps.clear()
            self._grip_pixmaps[key] = pixmap
        return pixmap

    def _card_chrome_pixmap(self, painter, width, height, dark):
        """Card surface: a real Fluent surface, not just a drawn outline.

        Key, LRU bound and identity semantics are unchanged from the validated
        implementation; only the painted content became a surface.
        """
        dpr = painter.device().devicePixelRatioF()
        key = (width, height, dark, dpr)
        pixmap = self._card_chrome.get(key)
        if pixmap is None:
            tokens = self._tokens(dark)
            pixmap = QPixmap(max(1, round((width + 2) * dpr)), max(1, round((height + 2) * dpr)))
            pixmap.setDevicePixelRatio(dpr)
            pixmap.fill(Qt.GlobalColor.transparent)
            chrome_painter = QPainter(pixmap)
            chrome_painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            body = QRectF(1, 1, width - 1, height - 1)
            chrome_painter.setPen(Qt.PenStyle.NoPen)
            chrome_painter.setBrush(tokens["surface"])
            chrome_painter.drawRoundedRect(body, self.RADIUS, self.RADIUS)
            stroke = QColor(tokens["stroke"])
            stroke.setAlpha(self._stroke_alpha(self.STATE_NORMAL))
            chrome_painter.setBrush(Qt.BrushStyle.NoBrush)
            chrome_painter.setPen(QPen(stroke, 1))
            chrome_painter.drawRoundedRect(body.adjusted(0.5, 0.5, -0.5, -0.5),
                                           self.RADIUS, self.RADIUS)
            chrome_painter.end()
            self._card_chrome[key] = pixmap
            if len(self._card_chrome) > 24:
                self._card_chrome.popitem(last=False)
        else:
            self._card_chrome.move_to_end(key)
        return pixmap

    # -------------------------------------------------------------- layout
    def sizeHint(self, option, index):
        view = self.parent()
        width = max(1, view.gridSize().width() - (4 if view._grid else 1))
        return QSize(width, 60 if index.model().rowCount() >= 5 else 64)

    def _delete_rect(self, item_rect, compact):
        rect = item_rect.adjusted(0, 0, -1, -1)
        inset = 12 if compact else 14
        return QRect(rect.right() - inset - 32,
                     rect.top() + (rect.height() - 32) // 2, 32, 32)

    def _grip_rect(self, item_rect, compact):
        rect = item_rect.adjusted(0, 0, -1, -1)
        inset = 12 if compact else 14
        return QRect(rect.left() + inset - 4, rect.top(), 22, rect.height())

    def delete_hit_test(self, index, item_rect, point):
        return self._delete_rect(item_rect, index.model().rowCount() >= 5).contains(point)

    def grip_hit_test(self, index, item_rect, point):
        return self._grip_rect(item_rect, index.model().rowCount() >= 5).contains(point)

    # ----------------------------------------------------------- drag ghost
    def render_card(self, index, width, height, dpr):
        """Render one card into a standalone pixmap for the live drag ghost.

        Uses the same _draw_card path as normal painting, so the floating card
        keeps the original text, status and icon. The surface is baked in, so
        the lifted card is opaque by construction.
        """
        model = index.model()
        compact = model.rowCount() >= 5
        dark = isDarkTheme()
        raw = model.data(index, TaskQueueModel.StatusRole)
        status = model.data(index, TaskQueueModel.DisplayStatusRole) or "Queued"
        if self.paused and raw == "Compressing":
            status = "Paused"
        name = model.data(index, TaskQueueModel.NameRole) or ""
        path = model.data(index, TaskQueueModel.PathRole) or ""
        task = model.data(index, TaskQueueModel.TaskRole)
        folder = self._folder_by_task.get(id(task), False)
        progress = model.data(index, TaskQueueModel.ProgressRole) or 0
        dpr = dpr or 1.0
        pixmap = QPixmap(max(1, round((width + 2) * dpr)),
                         max(1, round((height + 2) * dpr)))
        pixmap.setDevicePixelRatio(dpr)
        pixmap.fill(Qt.GlobalColor.transparent)
        offscreen = QPainter(pixmap)
        try:
            card = QRect(1, 1, width, height)
            self._draw_card(offscreen, card, compact, dark, raw, status,
                            name, path, folder, progress)
            self._draw_affordances(offscreen, card, compact, dark, self.STATE_DRAG)
        finally:
            offscreen.end()
        return pixmap

    def _draw_placeholder(self, painter, option_rect):
        """Fluent empty slot: soft accent tint, dashed outline, no content.

        Deliberately lighter than the lifted card so the dragged card keeps the
        stronger visual weight.
        """
        dark = isDarkTheme()
        accent = self._accent_color(dark)
        rect = QRectF(option_rect.adjusted(0, 0, -1, -1))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        fill = QColor(accent)
        fill.setAlpha(26 if dark else 18)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, self.RADIUS, self.RADIUS)
        edge = QColor(accent)
        edge.setAlpha(110 if dark else 85)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(edge, 1, Qt.PenStyle.DashLine))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                                self.RADIUS, self.RADIUS)
        painter.restore()

    # ------------------------------------------------------------- painting
    def _state_for(self, view, visual_row, dragging):
        if dragging:
            return self.STATE_DRAG
        locked = getattr(view, "is_queue_locked", None)
        if callable(locked) and locked():
            return self.STATE_LOCKED
        press = getattr(view, "press_row", None)
        if callable(press) and press() == visual_row:
            return self.STATE_PRESSED
        hover = getattr(view, "hover_row", None)
        if callable(hover) and hover() == visual_row:
            return self.STATE_HOVER
        return self.STATE_NORMAL

    def paint(self, painter, option, index):
        view = self.parent()
        dragging = (getattr(view, "is_drag_active", None) is not None
                    and view.is_drag_active())
        visual_row = index.row()
        if dragging:
            if view.is_placeholder_row(visual_row):
                self._draw_placeholder(painter, option.rect)
                return
            source_row = view.preview_source_row(visual_row)
            if source_row != visual_row:
                index = index.model().index(source_row, index.column())
        model = index.model()
        compact = model.rowCount() >= 5
        dark = isDarkTheme()
        raw = model.data(index, TaskQueueModel.StatusRole)
        status = model.data(index, TaskQueueModel.DisplayStatusRole) or "Queued"
        if self.paused and raw == "Compressing":
            status = "Paused"
        name = model.data(index, TaskQueueModel.NameRole) or ""
        path = model.data(index, TaskQueueModel.PathRole) or ""
        task = model.data(index, TaskQueueModel.TaskRole)
        folder = self._folder_by_task.get(id(task), False)
        progress = model.data(index, TaskQueueModel.ProgressRole) or 0
        if not option.rect.adjusted(0, 0, -1, -1).isValid():
            return
        state = self._state_for(view, visual_row, dragging)
        if raw != "Compressing":
            dpr = painter.device().devicePixelRatioF()
            key = (id(task), name, path, folder, raw, status, compact,
                   option.rect.width(), option.rect.height(), dark, dpr)
            pixmap = self._full_cards.get(key)
            if pixmap is None:
                width, height = option.rect.width(), option.rect.height()
                pixmap = QPixmap(max(1, round((width + 2) * dpr)),
                                 max(1, round((height + 2) * dpr)))
                pixmap.setDevicePixelRatio(dpr)
                pixmap.fill(Qt.GlobalColor.transparent)
                offscreen = QPainter(pixmap)
                try:
                    self._draw_card(offscreen, QRect(1, 1, width, height), compact, dark,
                                    raw, status, name, path, folder, progress)
                finally:
                    offscreen.end()
                self._full_cards[key] = pixmap
                self._full_card_misses += 1
                if len(self._full_cards) > 96:
                    self._full_cards.popitem(last=False)
                    self._full_card_evictions += 1
            else:
                self._full_cards.move_to_end(key)
                self._full_card_hits += 1
            painter.drawPixmap(option.rect.topLeft() - QPoint(1, 1), pixmap)
            self._draw_state_layer(painter, option.rect, dark, state)
            self._draw_affordances(painter, option.rect, compact, dark, state)
            return
        self._full_card_bypasses += 1
        self._draw_card(painter, option.rect, compact, dark, raw, status,
                        name, path, folder, progress)
        self._draw_state_layer(painter, option.rect, dark, state)
        self._draw_affordances(painter, option.rect, compact, dark, state)

    # ------------------------------------------------------ state + chrome
    def _draw_state_layer(self, painter, option_rect, dark, state):
        """Hover / pressed feedback, drawn over the cached card.

        Kept out of both card caches on purpose: their keys are part of the
        validated hot path and must not gain an interaction dimension.
        """
        if state == self.STATE_NORMAL:
            return
        tokens = self._tokens(dark)
        rect = QRectF(option_rect.adjusted(0, 0, -1, -1))
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        body = QPainterPath()
        body.addRoundedRect(rect, self.RADIUS, self.RADIUS)

        fill_alpha = self._fill_alpha(state, dark)
        if fill_alpha:
            fill = QColor(tokens["stroke"])
            fill.setAlpha(fill_alpha)
            painter.save()
            painter.setClipPath(body)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(fill)
            painter.drawRect(rect)
            painter.restore()

        stroke = QColor(tokens["stroke"])
        stroke.setAlpha(self._stroke_alpha(state))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(stroke, 1))
        painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5),
                                self.RADIUS, self.RADIUS)

        # Restrained elevation: a hairline just outside the top edge reads as a
        # soft lift without a real shadow, which the 2 px card gap would clip.
        if state in (self.STATE_HOVER, self.STATE_PRESSED):
            lift = QColor(tokens["shadow"])
            lift.setAlpha(14 if state == self.STATE_HOVER else 8)
            painter.setPen(QPen(lift, 1))
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1),
                                    self.RADIUS - 1, self.RADIUS - 1)
        painter.restore()

    def _draw_affordances(self, painter, option_rect, compact, dark, state):
        """Drag handle and delete affordance at the emphasis for this state."""
        rect = option_rect.adjusted(0, 0, -1, -1)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        grip = self._grip_rect(option_rect, compact)
        grip_pixmap = self._grip_pixmap(painter, dark, state, compact)
        painter.drawPixmap(
            QPoint(grip.center().x() - 7, grip.center().y() - 9), grip_pixmap
        )

        delete = self._delete_rect(option_rect, compact)
        view = self.parent()
        control = None
        hover_control = getattr(view, "hover_control", None)
        if callable(hover_control):
            control = hover_control()
        if control == "delete" and state in (self.STATE_HOVER, self.STATE_PRESSED):
            # A dedicated highlight only while the pointer is actually on it;
            # a plain card hover just raises the icon's contrast.
            surface = QColor(255, 255, 255, 28) if dark else QColor(0, 0, 0, 20)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(surface)
            painter.drawRoundedRect(QRectF(delete), self.RADIUS_CONTROL, self.RADIUS_CONTROL)

        delete_pixmap = self._delete_pixmap(painter, dark, state)
        if delete_pixmap is not None:
            painter.drawPixmap(delete.adjusted(7, 7, -7, -7), delete_pixmap)
        else:
            base = QColor(255, 255, 255) if dark else QColor(32, 32, 32)
            fallback = QColor(base)
            fallback.setAlpha(self._delete_alpha(state))
            painter.setPen(fallback)
            painter.drawText(delete, Qt.AlignmentFlag.AlignCenter, "×")
        painter.restore()

    def _draw_card(self, painter, option_rect, compact, dark, raw, status,
                   name, path, folder, progress):
        """Surface + content. Affordances are painted separately so their
        emphasis can follow the interaction state without entering the cache."""
        rect = option_rect.adjusted(0, 0, -1, -1)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(
            option_rect.topLeft() - QPoint(1, 1),
            self._card_chrome_pixmap(painter, option_rect.width(), option_rect.height(), dark),
        )
        tokens = self._tokens(dark)

        inset = 12 if compact else 14
        y = rect.top()
        grip = QRect(rect.left() + inset - 4, y, 22, rect.height())
        icon = QRect(grip.right() + 6, y, 24, rect.height())
        delete = self._delete_rect(option_rect, compact)
        grip_font, icon_font, badge_font, badge_metrics, title_font, title_metrics, path_font, path_metrics = self._fonts[compact]

        painter.setFont(icon_font)
        painter.drawText(icon, Qt.AlignmentFlag.AlignCenter, "📁" if folder else "📄")

        label = f"{self.ICONS.get(status, '○')}  {status}"
        badge_width = badge_metrics.horizontalAdvance(label) + 14
        badge = QRect(delete.left() - 10 - badge_width, y + (rect.height() - 22) // 2,
                      badge_width, 22)
        light, dark_rgb = self.COLORS.get(status, self.COLORS["Queued"])
        r, g, b = dark_rgb if dark else light
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(r, g, b, 26 if dark else 20))
        painter.drawRoundedRect(QRectF(badge), self.RADIUS_PILL, self.RADIUS_PILL)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(r, g, b, 70 if dark else 58), 1))
        painter.drawRoundedRect(QRectF(badge).adjusted(0.5, 0.5, -0.5, -0.5),
                                self.RADIUS_PILL, self.RADIUS_PILL)
        painter.setPen(QColor(r, g, b))
        painter.setFont(badge_font)
        painter.drawText(badge.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter, label)

        text_left = icon.right() + 10
        text_right = badge.left() - 10
        text_width = max(0, text_right - text_left)
        if text_width:
            title = QRect(text_left, y + (6 if compact else 7), text_width, 20)
            secondary = QRect(text_left, y + (28 if compact else 31), text_width, 17)
            painter.setFont(title_font)
            painter.setPen(QColor(240, 240, 240) if dark else QColor(28, 28, 28))
            painter.drawText(title, Qt.AlignmentFlag.AlignVCenter,
                             title_metrics.elidedText(name, Qt.TextElideMode.ElideRight, text_width))
            painter.setFont(path_font)
            painter.setPen(QColor(160, 160, 160) if dark else QColor(112, 112, 112))
            painter.drawText(secondary, Qt.AlignmentFlag.AlignVCenter,
                             path_metrics.elidedText(path, Qt.TextElideMode.ElideMiddle, text_width))
            if raw == "Compressing":
                # Product-UI: halo progress. The bar is a gradient with a soft
                # two-pass glow behind the filled part, which makes the moving
                # edge read continuously instead of as a hard step. The glow is
                # translucent rounded rects, not a blur effect, so a long queue
                # stays cheap to paint.
                bar = QRect(text_left, y + rect.height() - 12, max(0, text_width - 34), 11)
                paint_halo_bar(painter, bar, min(progress, 100) / 100.0)
                painter.setFont(path_font)
                painter.setPen(QColor(160, 160, 160) if dark else QColor(112, 112, 112))
                painter.drawText(QRect(bar.right() + 6, bar.top() + bar.height() // 2 - 8,
                                       32, 16),
                                 Qt.AlignmentFlag.AlignCenter, f"{progress}%")
        painter.restore()
