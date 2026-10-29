import math
import os

from PySide6.QtCore import QElapsedTimer, QModelIndex, QPoint, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPalette, QPen, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QApplication, QListView

from ui.task_delegate import TaskQueueDelegate
from ui.task_model import TaskQueueModel

# H.1-P PROTO-MARKER-VIEW: live drag ghost + placeholder reorder prototype.


class TaskQueueView(QListView):
    """Queue view responsible for task interaction, layout, scrolling, and
    view-level presentation state.

    H.1-P prototype: the view owns a *visual* drag preview only. Reordering is
    still committed by a single Model.moveRows() call on mouse release; the
    model's order is never touched while a drag is in flight.
    """

    # --- H.1-P ghost polish (visual tuning only) ---
    # The card in your hand must read as a solid, fully readable object. All of
    # the "lifted" separation comes from the shadow and outline, never from
    # making the card itself see-through.
    GHOST_OPACITY = 1.0
    GHOST_SHADOW_PAD = 6
    GHOST_RADIUS = 8
    GHOST_SHADOW_LAYERS = ((0, 32), (1, 20), (2, 13), (3, 8))
    GHOST_OUTLINE = (120, 130, 150, 160)
    PLACEHOLDER_PEN = (120, 150, 200, 85)
    PLACEHOLDER_FILL = (120, 150, 200, 18)
    # Grid candidate switching: a grid card is wide, so waiting for the target's
    # centre line made the placeholder feel late. Switch once the pointer is this
    # far into the target, measured from the edge the drag entered through.
    CANDIDATE_ENTER_RATIO = 0.30
    CANDIDATE_DEAD_BAND = 10

    # --- H.3-P / H.3-P2 smooth wheel reconstruction (input model only) ---
    # A wheel event never moves the view: it only pushes the TARGET. The timer
    # owns the visual position and follows the target with a critically damped
    # second-order tracker, which turns discrete notches into one continuous,
    # velocity-continuous motion.
    WHEEL_STEP_PX = 96.0            # logical px per 120-unit notch
    WHEEL_OMEGA_S = 36.0            # critically damped stiffness (1/s)
    WHEEL_STOP_PX = 1.0             # visual rest: remaining distance
    WHEEL_STOP_VELOCITY = 0.05      # visual rest: velocity (px/ms)
    WHEEL_TICK_MS = 8               # timer interval
    WHEEL_SETTLE_MS = 400.0         # safety fallback only, not the normal path
    WHEEL_MAX_BACKLOG_VIEWPORTS = 3.0

    WHEEL_TRACE = bool(os.environ.get("BATCHZIP_WHEEL_TRACE"))

    def __init__(self, model=None, parent=None):
        super().__init__(parent)
        self.setModel(model if model is not None else TaskQueueModel(self))
        self.setItemDelegate(TaskQueueDelegate(self))
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMovement(QListView.Movement.Static)
        self.setViewMode(QListView.ViewMode.ListMode)
        self.setUniformItemSizes(True)
        self.setSpacing(2)
        # Needed so hover feedback arrives without a button held.
        self.viewport().setMouseTracking(True)
        self._grid = False
        self._last_width = -1
        self._wheel_position = 0.0
        self._wheel_velocity = 0.0
        self._wheel_target = 0.0
        self._wheel_idle_ms = 0.0
        self._wheel_applying = False
        self._wheel_stop_reason = None
        self._wheel_overshoot_brakes = 0
        self._wheel_clock = QElapsedTimer()
        self._wheel_timer = QTimer(self)
        self._wheel_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._wheel_timer.timeout.connect(self._advance_wheel_scroll)
        self._wheel_trace = []
        self._delete_press_task = None
        self._drag_task = None
        self._drag_origin = None
        self._dragging = False
        self._queue_locked = False
        # --- H.1-P drag preview state (visual only) ---
        self._drag_active = False
        self._drag_source_row = -1
        self._drag_slot = -1
        self._drag_pixmap = None
        self._drag_card_offset = QPoint()
        self._drag_grab = QPoint()
        self._drag_pos = QPoint()
        # Grid candidate hysteresis state (plain scalars, no state machine).
        self._drag_hover_row = -1
        self._drag_after = None
        self._drag_prev_x = 0
        self._drag_entered_from_left = True
        # --- H.2-P interaction feedback state (presentation only) ---
        self._hover_row = -1
        self._hover_control = None
        self._press_row = -1
        scrollbar = self.verticalScrollBar()
        scrollbar.sliderPressed.connect(self._stop_wheel_scroll)
        scrollbar.sliderReleased.connect(self._stop_wheel_scroll)
        scrollbar.rangeChanged.connect(self._stop_wheel_scroll)
        scrollbar.valueChanged.connect(self._sync_manual_scroll)
        self.model().rowsRemoved.connect(self._update_geometry_after_remove)
        self.set_grid_mode(False)

    # ------------------------------------------------------------------ input
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._end_drag_visuals()
            self._delete_press_task = None
            self._drag_task = None
            self._drag_origin = None
            self._dragging = False
            self._set_press(-1)
            if self._queue_locked:
                super().mousePressEvent(event)
                return
            point = event.position().toPoint()
            index = self.indexAt(point)
            if index.isValid() and self.itemDelegate().delete_hit_test(
                index, self.visualRect(index), point
            ):
                model = self.model()
                if model.data(index, TaskQueueModel.DeletableRole):
                    self._delete_press_task = model.data(index, TaskQueueModel.TaskRole)
                event.accept()
                return
            if index.isValid():
                self._set_press(index.row())
                self._drag_task = self.model().data(index, TaskQueueModel.TaskRole)
                self._drag_origin = point
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_task is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if not self._dragging and (
                event.position().toPoint() - self._drag_origin
            ).manhattanLength() >= QApplication.startDragDistance():
                self._begin_drag()
            if self._dragging:
                self._update_drag(event.position().toPoint())
                event.accept()
                return
        self._update_hover(event.position().toPoint())
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self._set_hover(-1, None)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._set_press(-1)
        if (event.button() == Qt.MouseButton.LeftButton
                and not self._queue_locked
                and self._delete_press_task is not None):
            task = self._delete_press_task
            self._delete_press_task = None
            point = event.position().toPoint()
            index = self.indexAt(point)
            if index.isValid() and self.model().data(index, TaskQueueModel.TaskRole) is task:
                if self.itemDelegate().delete_hit_test(index, self.visualRect(index), point):
                    if self.model().data(index, TaskQueueModel.DeletableRole):
                        self.model().remove_task(task)
            event.accept()
            return
        if event.button() == Qt.MouseButton.LeftButton and self._drag_task is not None:
            task = self._drag_task
            dragging = self._dragging
            source = self._drag_source_row
            slot = self._drag_slot
            self._drag_task = None
            self._drag_origin = None
            self._dragging = False
            if dragging:
                self.viewport().unsetCursor()
                self._end_drag_visuals()
                super().mouseReleaseEvent(event)
                self._commit_drag(task, source, slot, event.position().toPoint())
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self._drag_active:
            self._cancel_drag()
            event.accept()
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------ H.2-P feedback
    # Interaction state lives here and is read by the delegate at paint time.
    # It is presentation only: membership, order and identity stay in the model,
    # and none of the drag paths read it.
    def hover_row(self):
        return self._hover_row

    def press_row(self):
        return self._press_row

    def hover_control(self):
        return self._hover_control

    def is_queue_locked(self):
        return self._queue_locked

    def _set_hover(self, row, control):
        if row == self._hover_row and control == self._hover_control:
            return
        self._hover_row = row
        self._hover_control = control
        self._apply_cursor()
        self.viewport().update()

    def _set_press(self, row):
        if row == self._press_row:
            return
        self._press_row = row
        self.viewport().update()

    def _update_hover(self, point):
        if self._dragging or self._drag_active:
            return
        index = self.indexAt(point)
        if not index.isValid():
            self._set_hover(-1, None)
            return
        rect = self.visualRect(index)
        delegate = self.itemDelegate()
        if not self._queue_locked and delegate.delete_hit_test(index, rect, point):
            self._set_hover(index.row(), "delete")
        elif not self._queue_locked and delegate.grip_hit_test(index, rect, point):
            self._set_hover(index.row(), "grip")
        else:
            self._set_hover(index.row(), None)

    def _apply_cursor(self):
        if self._dragging:
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self._queue_locked:
            self.viewport().unsetCursor()
            return
        if self._hover_control == "delete":
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor)
        elif self._hover_control == "grip":
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            self.viewport().unsetCursor()

    # ------------------------------------------------- H.1-P drag preview
    def is_drag_active(self):
        return self._drag_active

    def is_placeholder_row(self, visual_row):
        return self._drag_active and visual_row == self._drag_slot

    def preview_source_row(self, visual_row):
        """Map a *visual* row to the model row whose content belongs there.

        While dragging, the dragged task is projected to the candidate slot and
        every other task shifts to fill the gap. The model itself is untouched.
        """
        if not self._drag_active:
            return visual_row
        model = self.model()
        count = model.rowCount()
        source = self._drag_source_row
        if source < 0 or source >= count:
            return visual_row
        others = [row for row in range(count) if row != source]
        slot = max(0, min(len(others), self._drag_slot))
        order = others[:slot] + [source] + others[slot:]
        if 0 <= visual_row < len(order):
            return order[visual_row]
        return visual_row

    def _begin_drag(self):
        model = self.model()
        row = model.row_for_task(self._drag_task)
        if row < 0:
            return
        index = model.index(row)
        rect = self.visualRect(index)
        if rect.width() <= 0 or rect.height() <= 0:
            return
        delegate = self.itemDelegate()
        dpr = self.viewport().devicePixelRatioF()
        # Render the card content from the model (transparent surface, chrome and
        # text only). Grabbing screen pixels is deliberately avoided: the grabbed
        # rectangle is the whole grid cell - wider than the card - and it has
        # square corners, so its background pixels painted a white frame and
        # white corners around the lifted card.
        card = delegate.render_card(index, rect.width(), rect.height(), dpr)
        surface = self._surface_color()
        self._drag_active = True
        self._drag_source_row = row
        self._drag_slot = row
        self._drag_pixmap, self._drag_card_offset = self._compose_ghost(
            card, rect.width(), rect.height(), dpr, surface
        )
        self._drag_grab = self._drag_origin - rect.topLeft()
        self._drag_pos = QPoint(self._drag_origin)
        self._drag_hover_row = -1
        self._drag_after = None
        self._drag_prev_x = self._drag_origin.x()
        self._drag_entered_from_left = True
        self._dragging = True
        self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
        self.viewport().update()

    def _surface_color(self):
        """Colour of the surface behind the queue, i.e. the card's own surface.

        Read from the palette on purpose: grabbing screen pixels depends on the
        window being renderable and on the platform backing store, which proved
        unreliable. The palette is stable in every environment.
        """
        top = self.window()
        if top is not None:
            palette = top.palette()
            for role in (QPalette.ColorRole.Base, QPalette.ColorRole.Window,
                         QPalette.ColorRole.Button):
                colour = palette.color(role)
                if colour.isValid() and colour.alpha() > 0 and colour != QColor(0, 0, 0):
                    return QColor(colour.red(), colour.green(), colour.blue())
        return QColor(255, 255, 255)

    def _compose_ghost(self, card, width, height, dpr, surface):
        """Build the lifted card: opaque rounded surface, a restrained shadow and
        a firmer outline, with the card content clipped to the rounded shape so
        nothing can spill past the corners.

        Composed once per drag, so the paint path stays a single drawPixmap.
        """
        pad = self.GHOST_SHADOW_PAD
        radius = self.GHOST_RADIUS
        dpr = dpr or 1.0
        ghost = QPixmap(max(1, round((width + pad * 2) * dpr)),
                        max(1, round((height + pad * 2) * dpr)))
        ghost.setDevicePixelRatio(dpr)
        ghost.fill(Qt.GlobalColor.transparent)
        painter = QPainter(ghost)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            card_rect = QRectF(pad, pad, width, height)

            painter.setPen(Qt.PenStyle.NoPen)
            shadow_base = card_rect.adjusted(0, 1, 0, 1)
            for spread, alpha in self.GHOST_SHADOW_LAYERS:
                painter.setBrush(QColor(0, 0, 0, alpha))
                painter.drawRoundedRect(
                    shadow_base.adjusted(-spread, -spread, spread, spread),
                    radius + spread, radius + spread,
                )

            # Opaque card surface: the dragged card must never show the list
            # through it, whatever the captured pixels contained.
            painter.setBrush(surface)
            painter.drawRoundedRect(card_rect, radius, radius)

            # Clip the content to the rounded shape so the card's own square
            # pixmap corners cannot paint outside it.
            path = QPainterPath()
            path.addRoundedRect(card_rect, radius, radius)
            painter.save()
            painter.setClipPath(path)
            painter.drawPixmap(QPoint(pad - 1, pad - 1), card)
            painter.restore()

            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor(*self.GHOST_OUTLINE), 1))
            painter.drawRoundedRect(
                card_rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius
            )
        finally:
            painter.end()
        return ghost, QPoint(pad, pad)

    def _update_drag(self, point):
        self._drag_pos = QPoint(point)
        slot = self._slot_from_pos(point)
        if slot != self._drag_slot:
            self._drag_slot = slot
        self._drag_prev_x = point.x()
        self.viewport().update()

    def _grid_after(self, index, point):
        """True when the pointer sits on the `after` side of this grid card.

        A grid card is wide, so waiting for its centre line felt late. The
        switch happens CANDIDATE_ENTER_RATIO into the card, measured from the
        edge the drag came in through, so leftward and rightward behave
        symmetrically.

        The entry side is latched once per card - a tiny backwards move cannot
        flip the threshold back and forth - and a small dead band absorbs
        hovering exactly on the boundary.

        This returns a side only. It deliberately does NOT return a Qt
        destinationChild: the hover candidate must live in the projected
        layout, and the destinationChild conversion happens once, at commit.
        """
        row = index.row()
        rect = self.visualRect(index)
        width = max(1, rect.width())
        if row != self._drag_hover_row:
            # Latch the entry side once per card, from the direction of travel in
            # the LINEAR order - not from the horizontal direction. In a grid the
            # next row starts to the left, so a leftward pointer move can still be
            # forward progress; using x alone inverted the threshold there.
            if self._drag_hover_row < 0:
                # First card of the drag: fall back to the actual travel
                # direction, otherwise approaching from the right would latch
                # the left threshold and jump the candidate forward.
                self._drag_entered_from_left = point.x() >= self._drag_prev_x
            else:
                self._drag_entered_from_left = row > self._drag_hover_row
            self._drag_hover_row = row
            self._drag_after = None
        ratio = (self.CANDIDATE_ENTER_RATIO if self._drag_entered_from_left
                 else 1.0 - self.CANDIDATE_ENTER_RATIO)
        threshold = rect.left() + width * ratio
        if self._drag_after:
            after = point.x() >= threshold - self.CANDIDATE_DEAD_BAND
        else:
            after = point.x() >= threshold
        self._drag_after = after
        return after

    def _insertion_slot(self, cell, after):
        """Visual insertion index for a hovered cell, in projected space.

        The view paints a projection while dragging: the source row shows the
        placeholder and every other row shifts to fill the gap. A cell number is
        therefore NOT a model row - cell `c` shows remaining[c] when it sits
        left of the placeholder and remaining[c - 1] when it sits right of it.

        Reading the card's remaining index through the projection is what keeps
        the placeholder under the pointer. Treating the cell number as a model
        row biased every candidate one slot to the right once the projection had
        shifted, which is the reported "drag left, placeholder jumps right".
        """
        count = self.model().rowCount()
        if count <= 0:
            return 0
        slot = max(0, min(count - 1, self._drag_slot))
        if cell == slot:
            # The pointer is on the gap itself; the gap stays where it is.
            return slot
        base = cell if cell < slot else cell - 1
        return max(0, min(count - 1, base + (1 if after else 0)))

    def _slot_from_pos(self, point):
        """Visual insertion index: where the dragged card lands in the
        remaining sequence (model order minus the dragged row).

        Computed directly in the layout the user is looking at. The Qt
        same-parent destinationChild convention is applied exactly once, in
        _commit_drag, and is never used for the hover candidate.
        """
        model = self.model()
        count = model.rowCount()
        source = self._drag_source_row
        if count <= 0 or source < 0:
            return 0
        if not self.viewport().rect().contains(point):
            # A release here cancels, so the preview must show no reorder.
            return source
        index = self.indexAt(point)
        if index.isValid():
            if self._grid:
                after = self._grid_after(index, point)
            else:
                rect = self.visualRect(index)
                after = point.y() >= rect.center().y()
            return self._insertion_slot(index.row(), after)
        last = self.visualRect(model.index(count - 1))
        after_last = point.y() > last.bottom() or (
            self._grid and last.top() <= point.y() <= last.bottom()
            and point.x() > last.right()
        )
        if after_last:
            return count - 1
        if self._grid:
            # Grid cells leave gutters between columns and margin beside the
            # grid. Sliding across a gutter must not throw the candidate back to
            # the source row, so the current insertion index is held; sliding
            # past the right edge of a row means that row is finished, so the
            # candidate settles after that row's last card.
            first = self.visualRect(model.index(0))
            if first.top() <= point.y() <= last.bottom():
                if point.x() > last.right():
                    probe = self.indexAt(QPoint(last.right() - 2, point.y()))
                    if probe.isValid():
                        return self._insertion_slot(probe.row(), True)
                return max(0, self._drag_slot)
        return source

    def _end_drag_visuals(self):
        self._drag_active = False
        self._drag_source_row = -1
        self._drag_slot = -1
        self._drag_pixmap = None
        self._drag_card_offset = QPoint()
        self._drag_hover_row = -1
        self._drag_after = None
        self._drag_entered_from_left = True
        self.viewport().update()

    def _cancel_drag(self):
        self._end_drag_visuals()
        self._drag_task = None
        self._drag_origin = None
        self._dragging = False
        self.viewport().unsetCursor()

    def _commit_drag(self, task, source, slot, point):
        """The single reorder commit: exactly one Model.moveRows() call."""
        if self._queue_locked:
            return
        model = self.model()
        row = model.row_for_task(task)
        if row < 0 or source < 0 or row != source:
            return
        if not self.viewport().rect().contains(point):
            return
        count = model.rowCount()
        if count <= 1:
            return
        slot = max(0, min(count - 1, slot))
        if slot == row:
            return
        destination = slot if slot < row else slot + 1
        model.moveRows(QModelIndex(), row, 1, QModelIndex(), destination)

    def paintEvent(self, event):
        super().paintEvent(event)
        if not self._drag_active or self._drag_pixmap is None:
            return
        painter = QPainter(self.viewport())
        try:
            if self.GHOST_OPACITY < 1.0:
                painter.setOpacity(self.GHOST_OPACITY)
            painter.drawPixmap(
                self._drag_pos - self._drag_grab - self._drag_card_offset,
                self._drag_pixmap,
            )
        finally:
            painter.end()

    def _move_dragged_task(self, task, point):
        if self._queue_locked:
            return
        model = self.model()
        source = model.row_for_task(task)
        if source < 0 or not self.viewport().rect().contains(point):
            return
        index = self.indexAt(point)
        if index.isValid():
            rect = self.visualRect(index)
            before = (point.x() < rect.center().x() if self._grid
                      else point.y() < rect.center().y())
            destination = index.row() + (0 if before else 1)
        else:
            last = self.visualRect(model.index(model.rowCount() - 1))
            after_last = point.y() > last.bottom() or (
                self._grid and last.top() <= point.y() <= last.bottom()
                and point.x() > last.right()
            )
            if not after_last:
                return
            destination = model.rowCount()
        if destination not in (source, source + 1):
            model.moveRows(QModelIndex(), source, 1, QModelIndex(), destination)

    def wheelEvent(self, event):
        scrollbar = self.verticalScrollBar()
        pixel = event.pixelDelta().y()
        if pixel:
            # Touchpad / high-resolution wheel input is already continuous, so it
            # is applied directly instead of being re-quantised through notch
            # scaling. Re-smoothing continuous input would only make it lag.
            self._stop_wheel_scroll()
            scrollbar.setValue(scrollbar.value() - pixel)
            self._trace_wheel("pixel", pixel, float(pixel), None, None)
            event.accept()
            return
        angle = event.angleDelta().y()
        if not angle or scrollbar.isSliderDown() or scrollbar.maximum() == scrollbar.minimum():
            super().wheelEvent(event)
            return

        # The whole input model lives here: a wheel event only ever moves the
        # TARGET. The timer owns the visual position. An already-active timer is
        # never restarted - that is exactly the C.14 starvation that was fixed
        # and it must not come back.
        if not self._wheel_timer.isActive():
            # Between animations the view is at rest, so a fresh motion starts
            # from a standstill. While the timer runs, velocity is preserved -
            # that is what keeps a burst of notches one continuous motion.
            self._wheel_position = float(scrollbar.value())
            self._wheel_velocity = 0.0
        self._wheel_idle_ms = 0.0
        notches = angle / 120.0
        delta = -notches * self.WHEEL_STEP_PX
        self._accumulate_wheel_target(delta)
        self._trace_wheel("angle", angle, delta, self._wheel_position, self._wheel_target)
        if (abs(self._wheel_target - self._wheel_position) >= self.WHEEL_STOP_PX
                and not self._wheel_timer.isActive()):
            self._wheel_clock.restart()
            self._wheel_timer.start(self.WHEEL_TICK_MS)
        event.accept()

    def _accumulate_wheel_target(self, delta):
        """Push the goal position. Never touches the visual position."""
        scrollbar = self.verticalScrollBar()
        position = self._wheel_position
        remaining = self._wheel_target - position
        # Reversing direction abandons the pending distance instead of grinding
        # through it, so counter-scrolling responds immediately.
        base = self._wheel_target if remaining * delta > 0 else position
        target = base + delta
        # A backlog cap keeps a burst of notches from coasting on for seconds.
        cap = max(1.0, self.viewport().height() * self.WHEEL_MAX_BACKLOG_VIEWPORTS)
        target = max(position - cap, min(position + cap, target))
        # Clamping at the ends also means no hidden backlog can build up: once
        # the target sits on maximum/minimum a further notch in that direction
        # simply does nothing, so the opposite direction reacts immediately.
        self._wheel_target = max(float(scrollbar.minimum()),
                                 min(float(scrollbar.maximum()), target))

    def _advance_wheel_scroll(self):
        """One timer tick: advance the critically damped tracker."""
        if not self._wheel_timer.isActive():
            self._wheel_position = float(self.verticalScrollBar().value())
            self._wheel_velocity = 0.0
            return
        dt = self._wheel_clock.restart()
        if dt <= 0.0:
            dt = float(self.WHEEL_TICK_MS)
        self._wheel_idle_ms += dt
        omega = self.WHEEL_OMEGA_S / 1000.0            # per millisecond
        error = self._wheel_position - self._wheel_target
        velocity = self._wheel_velocity
        # Critically damped motion settles onto the target from rest, so a
        # velocity already aimed at the target and larger than omega * error
        # would carry the position past it and spring back. It is braked to the
        # critical boundary instead. This only binds on a fast approach; normal
        # motion is untouched, so velocity stays continuous.
        if error * velocity < 0.0 and abs(velocity) > omega * abs(error):
            velocity = math.copysign(omega * abs(error), velocity)
            self._wheel_velocity = velocity
            self._wheel_overshoot_brakes += 1
        at_rest = (abs(error) < self.WHEEL_STOP_PX
                   and abs(velocity) < self.WHEEL_STOP_VELOCITY)
        capped = self._wheel_idle_ms >= self.WHEEL_SETTLE_MS
        if at_rest or capped:
            # Visually stationary: land exactly on the goal and stop ticking.
            self._wheel_stop_reason = "rest" if at_rest else "cap"
            self._wheel_position = self._wheel_target
            self._wheel_velocity = 0.0
            self._wheel_timer.stop()
        else:
            # Exact solution of x'' + 2*omega*x' + omega^2*(x - target) = 0 for a
            # constant target across dt. Being analytic, the result does not
            # depend on tick accuracy and cannot diverge when the event loop
            # stalls, and the real dt is what makes 60/100/120 Hz feel alike.
            decay = math.exp(-omega * dt)
            slope = velocity + omega * error
            self._wheel_position = self._wheel_target + (error + slope * dt) * decay
            self._wheel_velocity = (velocity - omega * slope * dt) * decay
        self._trace_wheel("tick", None, None, self._wheel_position, self._wheel_target,
                          dt=dt, alpha=None, active=self._wheel_timer.isActive(),
                          velocity=self._wheel_velocity, reason=self._wheel_stop_reason)
        self._apply_wheel_position()
        self._trace_wheel("applied", None, None, self._wheel_position, self._wheel_target,
                          dt=dt, alpha=None, active=self._wheel_timer.isActive(),
                          velocity=self._wheel_velocity, reason=self._wheel_stop_reason)

    def _apply_wheel_position(self):
        self._wheel_applying = True
        try:
            self.verticalScrollBar().setValue(round(self._wheel_position))
        finally:
            self._wheel_applying = False

    def _trace_wheel(self, kind, raw, delta, position, target, dt=None, alpha=None,
                     active=None, velocity=None, reason=None):
        """Opt-in H.3-P2 diagnostic. Off unless BATCHZIP_WHEEL_TRACE is set."""
        if not self.WHEEL_TRACE or len(self._wheel_trace) >= 40000:
            return
        self._wheel_trace.append({
            "t": self._wheel_clock.elapsed(),
            "kind": kind,
            "raw": raw,
            "delta": delta,
            "current": position,
            "target": target,
            "dt": dt,
            "alpha": alpha,
            "active": active,
            "velocity": velocity,
            "reason": reason,
            "value": self.verticalScrollBar().value(),
        })

    def _stop_wheel_scroll(self, *_):
        self._wheel_timer.stop()
        self._wheel_position = float(self.verticalScrollBar().value())
        self._wheel_velocity = 0.0
        self._wheel_target = self._wheel_position
        self._wheel_idle_ms = 0.0

    def _sync_manual_scroll(self, _):
        if not self._wheel_applying:
            self._stop_wheel_scroll()

    def set_paused(self, paused):
        """Show or clear the global Paused presentation; task state is untouched."""
        delegate = self.itemDelegate()
        paused = bool(paused)
        if delegate.paused == paused:
            return
        delegate.paused = paused
        self.viewport().update()

    def set_queue_locked(self, locked):
        """Freeze delete and reorder interactions; scrolling and layout stay live."""
        locked = bool(locked)
        if self._queue_locked == locked:
            return
        self._queue_locked = locked
        self._set_press(-1)
        self._set_hover(-1, None)
        if locked:
            self._delete_press_task = None
            self._drag_task = None
            self._drag_origin = None
            if self._dragging:
                self._dragging = False
                self.viewport().unsetCursor()
            if self._drag_active:
                self._end_drag_visuals()
        self._apply_cursor()
        self.viewport().update()

    def set_grid_mode(self, grid):
        self._grid = bool(grid)
        self._last_width = -1
        if grid:
            self.setFlow(QListView.Flow.LeftToRight)
            self.setWrapping(True)
            self.setResizeMode(QListView.ResizeMode.Adjust)
        else:
            self.setFlow(QListView.Flow.TopToBottom)
            self.setWrapping(False)
            self.setResizeMode(QListView.ResizeMode.Adjust)
        self._update_geometry()

    def _update_geometry(self):
        width = self.viewport().width()
        if width == self._last_width:
            return
        self._last_width = width
        height = 60 if self.model().rowCount() >= 5 else 64
        if self._grid:
            columns = max(1, width // 432)
            cell_width = max(1, (width - 8 * columns) // columns)
            size = QSize(cell_width, height + 4)
            self.setSpacing(0)
        else:
            size = QSize(max(1, width), height + 2)
            self.setSpacing(0)
        if self.gridSize() != size:
            self.setGridSize(size)
        self.doItemsLayout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_geometry()

    def rowsInserted(self, parent, start, end):
        super().rowsInserted(parent, start, end)
        self._last_width = -1
        self._update_geometry()

    def rowsAboutToBeRemoved(self, parent, start, end):
        super().rowsAboutToBeRemoved(parent, start, end)
        self._last_width = -1
        self._update_geometry()

    def _update_geometry_after_remove(self, *_):
        self._last_width = -1
        self._update_geometry()
