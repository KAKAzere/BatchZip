import os
import re

from PySide6.QtCore import (
    Qt,
    QEvent,
    QSize,
    QPropertyAnimation,
    QEasingCurve,
)

from PySide6.QtGui import QCloseEvent, QColor, QGuiApplication

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QBoxLayout,
    QFileDialog,
    QMessageBox,
    QFrame,
    QSizePolicy,
    QToolButton,
    QGraphicsOpacityEffect
)

from qfluentwidgets import (
    BodyLabel,
    PushButton,
    LineEdit,
    SegmentedWidget,
    FluentIcon,
    setTheme,
    Theme
)
from qfluentwidgets import PrimaryPushButton, StrongBodyLabel, CaptionLabel, IconWidget, isDarkTheme, qconfig
from qfluentwidgets.common.style_sheet import updateStyleSheet

from ui.drop_zone import DropZone
from ui.product_ui import (SurfaceWidget, apply_button_style, accent_rgb, page_surface,
                           panel_border, panel_surface, settings_button_qss,
                           settings_icon)
from ui.native_title_bar import apply_title_bar_theme
from ui.settings_dialog import SettingsDialog
from ui.theme_preference import (load_theme_mode, save_theme_mode, theme_for_token,
                                 token_for_theme)
from ui.complete_dialog import CompleteDialog, WarningArchiveDialog
from ui.task_model import TaskQueueModel
from ui.task_queue_controller import TaskQueueController
from ui.task_queue_view import TaskQueueView

from core.task import Task
from core.compress_thread import CompressThread


class GlobalStatusBadge(BodyLabel):

    def __init__(self):
        super().__init__()
        self.setFixedHeight(19)
        qconfig.themeChanged.connect(self.refreshStyle)
        self.setText("Ready")

    def setText(self, text):
        if text == "Ready":
            # Standby, not success: this follows the BatchZip brand accent
            # (#0F5DDA / #4FA3FF, sampled from the app icon) instead of a green,
            # which read as "finished successfully".
            icon, light, dark = "●", (15, 93, 218), (79, 163, 255)
        elif "Paused" in text or text == "Cancelling...":
            icon, light, dark = "Ⅱ", (140, 90, 8), (240, 189, 101)
        elif "Compressing" in text or "%" in text:
            icon, light, dark = "◐", (15, 93, 218), (79, 163, 255)
        elif "Failed:" in text and "Failed: 0" not in text:
            icon, light, dark = "✕", (161, 42, 42), (241, 154, 154)
        elif "Warnings:" in text and "Warnings: 0" not in text:
            icon, light, dark = "⚠", (140, 90, 8), (240, 189, 101)
        elif text.startswith("Completed"):
            icon, light, dark = "✓", (35, 107, 64), (121, 201, 154)
        else:
            icon, light, dark = "○", (95, 104, 117), (191, 197, 205)

        self._statusColors = light, dark
        super().setText(f"{icon}  {text}")
        self.refreshStyle()

    def refreshStyle(self, *_):
        light, dark = self._statusColors
        r, g, b = dark if isDarkTheme() else light
        self.setStyleSheet(
            f"color:rgb({r},{g},{b});font-weight:600;"
            f"background:rgba({r},{g},{b},24);"
            f"border:1px solid rgba({r},{g},{b},55);"
            "border-radius:8px;padding:0 6px;"
        )


class MainWindow(QMainWindow):

    # --- H.4-P2 adaptive workspace layout ----------------------------------
    # The familiar stacked page is the default. Only when the queue really is
    # long does the top area collapse into a compact side-by-side strip, so the
    # Task Queue gets the room. The threshold is a product rule, not a heuristic.
    COMPACT_TASK_THRESHOLD = 15     # compact from 16 tasks: task_count > 15
    TOP_BAND_MIN_HEIGHT = 150       # compact strip is never shorter than this
    TOP_BAND_STACKED_HEIGHT = 150   # per-panel height in the narrow fallback
    TOP_BAND_STRETCH = (58, 42)     # Drop Zone : Compression
    # Measured minimumSizeHint() of each panel. Qt must never be asked to shrink
    # a panel below these, or it silently squeezes the controls inside.
    TOP_BAND_MIN_DROP = 502         # Choose Files + Choose Folder side by side
    TOP_BAND_MIN_COMPRESSION = 398  # widest row inside the compression card
    TOP_BAND_REQUIRED_WIDTH = TOP_BAND_MIN_DROP + TOP_BAND_MIN_COMPRESSION

    MODE_ORIGINAL = "original_stacked"
    MODE_COMPACT_SIDE = "compact_side_by_side"
    MODE_COMPACT_STACKED = "compact_stacked_fallback"

    def __init__(self):
        super().__init__()

        # The saved preference decides the mode; Theme.AUTO is only the fallback
        # when there is no preference yet or it cannot be trusted.
        self.themeMode = load_theme_mode()
        setTheme(self.themeMode)
        self._resolve_startup_theme()

        self.setWindowTitle("BatchZip")
        self.resize(1100, 700)
        self.setMinimumSize(680, 620)

        self.queueModel = TaskQueueModel()

        self.archiveFormat = "zip"

        self.settingsDialog = None
        self.thread = None
        self.isCompressing = False
        self.isPaused = False
        self.gridView = False

        self.initUI()

        self.queueController = TaskQueueController(self.queueModel, self.queueView)

        # Qt reports a Windows appearance change itself, on the GUI thread, so
        # following the system needs no polling and no background listener. The
        # signal only re-resolves; qconfig.theme stays the single authority.
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            self._onSystemThemeChanged)

    # =====================================================
    # UI
    # =====================================================

    @staticmethod
    def _resolve_startup_theme():
        """Resolve the theme mode and make qfluentwidgets apply it.

        qconfig.set() returns early when the config item already holds the
        requested value, so setTheme() can skip both the Theme.AUTO resolution
        and the style sheet refresh. Assigning qconfig.theme runs qfluentwidgets'
        own resolution - including AUTO, which it resolves from the system - and
        updateStyleSheet(), the same function setTheme() calls, applies the
        result to every registered widget.

        Used at startup and from the appearance selector, so both paths leave
        qfluentwidgets holding the authoritative resolved theme.
        """
        qconfig.theme = qconfig.themeMode.value
        updateStyleSheet()

    def initUI(self):

        # The page owns the one background surface of the window. SurfaceWidget
        # resolves it while painting, which does not depend on the theme signal
        # having fired before this line runs.
        page = SurfaceWidget(page_surface)
        page.setObjectName("appPage")
        self.setCentralWidget(page)

        self.mainLayout = QVBoxLayout(page)
        self.mainLayout.setContentsMargins(32, 24, 32, 24)
        self.mainLayout.setSpacing(16)

        # Global header: application-level status on the left, the global
        # settings entry on the right. Both live inside mainLayout, so they pick
        # up the same 32 px content baseline as the drop zone and the compression
        # card without a single hard-coded x.
        headerRow = QHBoxLayout()
        headerRow.setSpacing(8)
        self.statusLabel = GlobalStatusBadge()
        headerRow.addWidget(self.statusLabel)
        headerRow.addStretch(1)

        self.settingsButton = QToolButton()
        self.settingsButton.setFixedSize(32, 32)
        self.settingsButton.setIconSize(QSize(20, 20))
        self.settingsButton.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settingsButton.setToolTip("Settings")
        self.settingsButton.setAutoRaise(True)
        self.settingsButton.clicked.connect(self.onSettingsClicked)
        headerRow.addWidget(self.settingsButton)
        # _applyProductStyles only runs on themeChanged, so the initial icon and
        # interaction surface have to be applied here too.
        self._applySettingsButtonStyle()

        self.mainLayout.addLayout(headerRow)

        # 拖拽区
        self.dropZone = DropZone()
        self.dropZone.filesDropped.connect(
            self.handleFiles
        )

        self.dropZone.setFixedHeight(190)

        settings = SurfaceWidget(panel_surface)
        settings.setObjectName("compressionCard")
        # The border is theme-keyed too, so it is rebuilt with the surface on a
        # theme change; both come from product_ui.
        settings.setStyleSheet(
            "#compressionCard { border: 1px solid %s; border-radius: 12px; }"
            % panel_border())
        self.compressionCard = settings
        settingsLayout = QVBoxLayout(settings)
        # Original RC5 metrics. They are swapped for tighter ones only while the
        # compact strip is on screen.
        settingsLayout.setContentsMargins(16, 10, 16, 12)
        settingsLayout.setSpacing(5)
        self.settingsLayout = settingsLayout
        settingsHeader = QHBoxLayout()
        self.settingsHeader = settingsHeader
        settingsHeader.addWidget(StrongBodyLabel("Compression"))
        settingsHeader.addStretch()
        btnRow = QHBoxLayout()
        self.btnRow = btnRow
        btnRow.setSpacing(8)
        # Default arrangement is the original one: actions share the title row.
        settingsHeader.addLayout(btnRow)
        # Compact arrangement puts them on their own trailing row instead, which
        # is what lets the card fit a narrow column without squeezing Start.
        settingsLayout.addLayout(settingsHeader)

        # 压缩格式切换
        self.formatSelector = SegmentedWidget()
        self.formatSelector.setFixedWidth(400)

        self.formatSelector.addItem(
            routeKey="zip",
            text="ZIP",
            onClick=lambda: self.setArchiveFormat("zip")
        )

        self.formatSelector.addItem(
            routeKey="7z",
            text="7Z",
            onClick=lambda: self.setArchiveFormat("7z")
        )

        self.formatSelector.setCurrentItem("zip")

        settingsLayout.addWidget(CaptionLabel("Format"))
        formatRow = QHBoxLayout()
        self.formatRow = formatRow
        # Pivot declares QSizePolicy.Minimum and reports a ~118 px sizeHint, so a
        # trailing stretch would always leave the selector at 118 no matter what
        # minimum the caller sets. The width is therefore owned by a plain holder
        # widget - Qt never rewrites a QWidget's fixed width - and the selector
        # simply fills it. Original mode pins the holder to the RC5 width;
        # compact mode lets it track the narrower column.
        self.formatHolder = QWidget()
        holderLayout = QHBoxLayout(self.formatHolder)
        holderLayout.setContentsMargins(0, 0, 0, 0)
        holderLayout.setSpacing(0)
        self.formatSelector.setSizePolicy(QSizePolicy.Policy.Expanding,
                                          QSizePolicy.Policy.Fixed)
        holderLayout.addWidget(self.formatSelector)
        formatRow.addWidget(self.formatHolder)
        formatRow.addStretch()
        settingsLayout.addLayout(formatRow)

        # 输出路径
        outputRow = QHBoxLayout()
        outputRow.setSpacing(8)

        self.outputEdit = LineEdit()
        self.outputEdit.setPlaceholderText("Original folder")

        self.browseBtn = PushButton(
            "Browse",
            icon=FluentIcon.FOLDER
        )

        self.browseBtn.clicked.connect(
            self.chooseOutputFolder
        )

        outputRow.addWidget(self.outputEdit)
        outputRow.addWidget(self.browseBtn)

        settingsLayout.addWidget(CaptionLabel("Output folder"))
        settingsLayout.addLayout(outputRow)

        # Compact-only action row. A container widget rather than a bare layout,
        # so the very same buttons can be moved in and out without Qt warning
        # about a layout that still has a parent.
        self.actionBar = QWidget()
        actionLayout = QHBoxLayout(self.actionBar)
        actionLayout.setContentsMargins(0, 0, 0, 0)
        actionLayout.addStretch()
        self.actionBarLayout = actionLayout
        self.actionBar.setVisible(False)
        settingsLayout.addWidget(self.actionBar)

        # Compact container. It is built once and stays empty and hidden until
        # the queue is long enough to need it; the very same dropZone and
        # compressionCard instances are moved into it, so there is never a
        # second set of controls to keep in sync.
        self.topBand = QWidget()
        self.topBandLayout = QHBoxLayout(self.topBand)
        self.topBandLayout.setContentsMargins(0, 0, 0, 0)
        self.topBandLayout.setSpacing(16)
        self.topBand.setFixedHeight(self.TOP_BAND_MIN_HEIGHT)
        self.topBand.hide()

        # Default page: the original stacked layout.
        self.mainLayout.addWidget(self.dropZone)
        self.mainLayout.addWidget(settings)
        self._mountedMode = self.MODE_ORIGINAL

        self._layoutMode = None
        self._dropZoneCompact = None
        self._compressionCompact = None
        self._dropZoneDensity = 300
        # updateDensity() already funnels into the workspace policy, and it also
        # keeps the title, empty state and drop-zone density honest for changes
        # that arrive straight from the model, such as deleting a card.
        for signal in (self.queueModel.rowsInserted, self.queueModel.rowsRemoved,
                       self.queueModel.modelReset):
            signal.connect(self.updateDensity)

        # 按钮
        self.clearBtn = PushButton(
            "Clear All",
            icon=FluentIcon.DELETE
        )

        self.pauseBtn = PushButton(
            "Pause",
            icon=FluentIcon.PAUSE
        )

        self.pauseBtn.setEnabled(False)

        self.cancelBtn = PushButton("Cancel", icon=FluentIcon.CLOSE)
        self.cancelBtn.setEnabled(False)

        self.startBtn = PrimaryPushButton(
            "Start",
            icon=FluentIcon.PLAY
        )

        self.clearBtn.clicked.connect(
            self.clearTasks
        )

        self.pauseBtn.clicked.connect(
            self.togglePause
        )

        self.cancelBtn.clicked.connect(
            self.cancelCompression
        )

        self.startBtn.clicked.connect(
            self.startCompress
        )

        btnRow.addWidget(self.pauseBtn)
        btnRow.addWidget(self.cancelBtn)
        btnRow.addWidget(self.startBtn)

        # Product-UI: one shared feedback language for every action button.
        # Start reads as the primary action; Cancel carries the semantic danger
        # tint; the rest stay quiet so the primary stays dominant.
        apply_button_style(self.startBtn, "primary")
        apply_button_style(self.cancelBtn, "danger")
        apply_button_style(self.pauseBtn, "quiet")
        apply_button_style(self.clearBtn, "quiet")
        apply_button_style(self.browseBtn, "quiet")

        # ============ 任务列表：TaskQueueView（Model 为唯一顺序权威） ============
        queueHeader = QHBoxLayout()
        self.queueTitle = StrongBodyLabel("Task Queue (0)")
        queueHeader.addWidget(self.queueTitle)
        queueHeader.addStretch()
        self.viewSelector = QFrame()
        self.viewSelector.setObjectName("queueViewSelector")
        self.viewSelector.setFixedSize(66, 32)
        self.viewSelector.setStyleSheet(
            "#queueViewSelector { border: 1px solid rgba(120,120,120,55); border-radius: 7px; }"
        )
        # Selection surface. A plain child widget instead of a per-button
        # background, so it can slide between the two modes rather than jump.
        # It sits behind the buttons and ignores the mouse.
        self.viewIndicator = QFrame(self.viewSelector)
        self.viewIndicator.setObjectName("queueViewIndicator")
        self.viewIndicator.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.viewIndicator.lower()
        self.viewIndicatorAnim = QPropertyAnimation(self.viewIndicator, b"geometry", self)
        self.viewIndicatorAnim.setDuration(120)
        self.viewIndicatorAnim.setEasingCurve(QEasingCurve.Type.OutCubic)
        viewLayout = QHBoxLayout(self.viewSelector)
        viewLayout.setContentsMargins(1, 1, 1, 1)
        viewLayout.setSpacing(2)
        self.listViewButton = QToolButton()
        self.gridViewButton = QToolButton()
        for button in (self.listViewButton, self.gridViewButton):
            button.setFixedSize(30, 30)
            button.setIconSize(QSize(16, 16))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.toggled.connect(self._updateViewToggleStyle)
            viewLayout.addWidget(button)
        self.listViewButton.setToolTip("List view")
        self.gridViewButton.setToolTip("Grid view")
        self.listViewButton.clicked.connect(lambda: self.setQueueView(False))
        self.gridViewButton.clicked.connect(lambda: self.setQueueView(True))
        self.listViewButton.setChecked(True)
        qconfig.themeChanged.connect(self._updateViewToggleStyle)
        qconfig.themeChanged.connect(self._applyProductStyles)
        self._updateViewToggleStyle()
        queueHeader.addWidget(self.viewSelector)
        queueHeader.addSpacing(8)
        queueHeader.addWidget(self.clearBtn, 0, Qt.AlignmentFlag.AlignTop)
        self.mainLayout.addLayout(queueHeader)
        self.queueView = TaskQueueView(self.queueModel)

        self.queueView.setFrameShape(
            QFrame.Shape.NoFrame
        )

        self.queueView.setSelectionMode(
            TaskQueueView.SelectionMode.SingleSelection
        )

        self.queueView.setFocusPolicy(
            Qt.FocusPolicy.NoFocus
        )

        self.queueView.setStyleSheet("""
        QListView {
            background: transparent;
            border: none;
            outline: none;
        }
        QListView::item {
            background: transparent;
            border: none;
            padding: 0;
        }
        QListView::item:selected {
            background: transparent;
            border: none;
        }
        QListView::item:focus {
            outline: none;
        }
        """)

        self.mainLayout.addWidget(
            self.queueView,
            1
        )
        self.emptyState = QWidget(self.queueView.viewport())
        self.emptyState.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._emptyOpacity = QGraphicsOpacityEffect(self.emptyState)
        self._emptyOpacity.setOpacity(1.0)
        self.emptyState.setGraphicsEffect(self._emptyOpacity)
        self._emptyFade = QPropertyAnimation(self._emptyOpacity, b"opacity", self)
        self._emptyFade.setDuration(150)
        self._emptyFade.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._emptyFade.finished.connect(self._finishEmptyFade)
        self._emptyTargetVisible = True
        emptyLayout = QVBoxLayout(self.emptyState)
        emptyLayout.setContentsMargins(0, 0, 0, 0)
        emptyLayout.setSpacing(4)
        emptyLayout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        emptyIcon = IconWidget(FluentIcon.DOCUMENT)
        emptyIcon.setFixedSize(24, 24)
        self.emptyLabel = BodyLabel("No compression tasks yet")
        emptyHint = CaptionLabel("Add files or folders to get started")
        emptyLayout.addWidget(emptyIcon, 0, Qt.AlignmentFlag.AlignHCenter)
        emptyLayout.addSpacing(4)
        emptyLayout.addWidget(self.emptyLabel, 0, Qt.AlignmentFlag.AlignHCenter)
        emptyLayout.addWidget(emptyHint, 0, Qt.AlignmentFlag.AlignHCenter)
        self.queueView.viewport().installEventFilter(self)
        self.updateDensity()
        # Nothing has changed theme yet, so the caption has to be set once here.
        apply_title_bar_theme(self, isDarkTheme())

    def showEvent(self, event):
        super().showEvent(event)
        # The toggle indicator is placed from the buttons' own geometry, which
        # only exists once the layout has run. Activate it here so the selection
        # surface does not sit at the un-laid-out origin.
        if hasattr(self, "viewSelector"):
            self.viewSelector.layout().activate()
            self._place_view_indicator()

    def _place_view_indicator(self):
        """Snap the selection surface onto the checked button, without sliding."""
        if not hasattr(self, "viewIndicator"):
            return
        button = (self.gridViewButton if self.gridViewButton.isChecked()
                  else self.listViewButton)
        self.viewIndicatorAnim.stop()
        self.viewIndicator.setGeometry(button.geometry())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "emptyState"):
            self.emptyState.setGeometry(self.queueView.viewport().rect())
        self._update_workspace_layout()

    # =====================================================
    # H.4-P2 自适应工作区布局：唯一权威入口
    # =====================================================

    def _workspace_mode(self):
        """Decide the layout mode. This is the only place the policy lives."""
        count = self.queueModel.rowCount()          # authoritative task count
        if count <= self.COMPACT_TASK_THRESHOLD:
            return self.MODE_ORIGINAL
        if self._available_width() >= self.TOP_BAND_REQUIRED_WIDTH + self.topBandLayout.spacing():
            return self.MODE_COMPACT_SIDE
        return self.MODE_COMPACT_STACKED

    def _available_width(self):
        margins = self.mainLayout.contentsMargins()
        return self.centralWidget().width() - margins.left() - margins.right()

    def _update_workspace_layout(self, *_):
        """Single seam. Every trigger funnels here; it only rebuilds on change."""
        if not hasattr(self, "topBand"):
            return
        mode = self._workspace_mode()
        if mode == self._layoutMode:
            return                                   # nothing to restructure
        self._layoutMode = mode
        compact = mode != self.MODE_ORIGINAL
        self._arrange_drop_zone(compact)
        self._arrange_compression_panel(compact)
        self._mount_panels(mode)
        # Must be last: the invalidate() calls above schedule a layout pass that
        # would otherwise re-evaluate the format selector after SegmentedWidget
        # has reset its own minimum size.
        self._apply_format_width()

    def _mount_panels(self, mode):
        """Move the existing panels between the original page and the band.

        Nothing is touched unless the container has to change: re-inserting a
        panel invalidates its inner layout, which would throw away the geometry
        the original page already had.
        """
        if mode == self._mountedMode:
            return
        previous = self._mountedMode
        self._mountedMode = mode
        compact = mode != self.MODE_ORIGINAL
        was_compact = previous != self.MODE_ORIGINAL
        if compact and was_compact:
            # Same container, only the side-by-side / stacked direction changes.
            self._orient_top_band(mode)
            self._apply_format_width()
            return

        for container in (self.mainLayout, self.topBandLayout):
            container.removeWidget(self.dropZone)
            container.removeWidget(self.compressionCard)
        self.mainLayout.removeWidget(self.topBand)

        if compact:
            self.topBandLayout.addWidget(self.dropZone, self.TOP_BAND_STRETCH[0])
            self.topBandLayout.addWidget(self.compressionCard, self.TOP_BAND_STRETCH[1])
            self._orient_top_band(mode)
            self.mainLayout.insertWidget(1, self.topBand)
            self.topBand.show()
        else:
            self.topBand.hide()
            self.mainLayout.insertWidget(1, self.dropZone)
            self.mainLayout.insertWidget(2, self.compressionCard)
        self.mainLayout.invalidate()
        self.topBandLayout.invalidate()
        self._apply_format_width()

    def _orient_top_band(self, mode):
        if mode == self.MODE_COMPACT_STACKED:
            self.topBandLayout.setDirection(QBoxLayout.Direction.TopToBottom)
            self.topBandLayout.setStretch(0, 1)
            self.topBandLayout.setStretch(1, 1)
            self.topBand.setFixedHeight(self.TOP_BAND_STACKED_HEIGHT * 2
                                        + self.topBandLayout.spacing())
        else:
            self.topBandLayout.setDirection(QBoxLayout.Direction.LeftToRight)
            self.topBandLayout.setStretch(0, self.TOP_BAND_STRETCH[0])
            self.topBandLayout.setStretch(1, self.TOP_BAND_STRETCH[1])
            # Tall enough for whichever panel needs more, so the strip never
            # compresses its own contents into an overlap.
            self.topBand.setFixedHeight(max(
                self.TOP_BAND_MIN_HEIGHT,
                self.compressionCard.sizeHint().height(),
                self.dropZone.sizeHint().height(),
            ))
        self.topBandLayout.invalidate()
        self.topBand.updateGeometry()

    def _apply_format_width(self):
        """Set the selector width for the current mode.

        The width lives on the holder, which no layout pass can rewrite, so this
        runs once per mode change instead of being re-asserted after every
        layout pass.
        """
        if not hasattr(self, "formatHolder"):
            return
        if self._compressionCompact:
            self.formatHolder.setMinimumWidth(230)
            self.formatHolder.setMaximumWidth(400)
            self.formatRow.setStretch(0, 1)
            self.formatRow.setStretch(1, 0)
        else:
            self.formatHolder.setFixedWidth(400)
            self.formatRow.setStretch(0, 0)
            self.formatRow.setStretch(1, 1)
        self.formatHolder.updateGeometry()

    def _arrange_drop_zone(self, compact):
        """Swap only the metrics; the widget and its drop behaviour stay put."""
        if compact == self._dropZoneCompact:
            return
        self._dropZoneCompact = compact
        layout = self.dropZone.mainLayout
        if compact:
            self.dropZone.setMinimumHeight(130)
            self.dropZone.setMaximumHeight(16777215)
            # Product-UI: the illustrated folder is scaled instead of a font size
            # being set, so it stays crisp at either density. The macOS folder
            # proportion is taller than the old mark, so the vertical padding and
            # the gap above the title give the extra height back.
            self.dropZone.resizeTo(82, 4)
            layout.setContentsMargins(16, 6, 16, 6)
        else:
            self.dropZone.setMinimumHeight(140)
            self.dropZone.setMaximumHeight(300)
            self.dropZone.resizeTo(90, 5)
            layout.setContentsMargins(16, 7, 16, 7)
            self.animateDropZone(self._dropZoneDensity)

    def onSettingsClicked(self):
        """Open the appearance panel, reusing the instance while it lives."""
        if self.settingsDialog is None:
            self.settingsDialog = SettingsDialog(
                token_for_theme(self.themeMode), self)
            self.settingsDialog.themeModeChosen.connect(self._applyThemeToken)
        self.settingsDialog.show()
        self.settingsDialog.raise_()
        self.settingsDialog.activateWindow()

    def _applyThemeToken(self, token):
        """The one place the appearance preference changes.

        qfluentwidgets applies its own style sheets and emits themeChanged,
        which is already wired to every BatchZip surface, so this only has to
        drive that one entry point and record the choice.
        """
        mode = theme_for_token(token)
        self.themeMode = mode

        if mode is Theme.AUTO:
            # qconfig.theme's setter is where qfluentwidgets resolves AUTO from
            # the system. Resolving before setTheme() means the single refresh
            # setTheme() performs already paints the resolved theme, instead of
            # painting the stale one and needing a second full refresh.
            qconfig.theme = Theme.AUTO

        # One library refresh. qconfig.set() short-circuits when the mode already
        # matched, but setTheme() still runs updateStyleSheet() afterwards, so the
        # library sheets always land on the resolved theme here.
        setTheme(mode)

        # Custom sheets must be applied *after* that refresh. setTheme() emits
        # themeChanged before updateStyleSheet(), so anything applied from a
        # themeChanged handler is overwritten by the library sheet moments later;
        # this explicit pass is what makes the final state consistent.
        self._applyProductStyles()
        save_theme_mode(mode)

    def _onSystemThemeChanged(self, *_):
        """Follow a Windows appearance change while the System mode is active.

        A manual Light or Dark choice is left alone: only System re-resolves.
        The value itself still comes from qfluentwidgets' own AUTO resolution, so
        there is no second theme state here - this just makes it run again.

        One library refresh, then the themeChanged notification, in that order:
        the custom sheets applied by the handlers below would otherwise be
        overwritten by the library sheets that updateStyleSheet() installs.
        """
        if self.themeMode is not Theme.AUTO:
            return
        before = qconfig.theme
        qconfig.theme = Theme.AUTO
        if qconfig.theme is before:
            return
        updateStyleSheet()
        qconfig.themeChanged.emit(qconfig.theme)

    def _applySettingsButtonStyle(self):
        """Theme-keyed icon tint and interaction surface.

        The ink is chosen from the page surface this window now owns, so the
        glyph stays legible in both themes.
        """
        self.settingsButton.setIcon(settings_icon(20, page_surface()))
        self.settingsButton.setStyleSheet(settings_button_qss())

    def _applyProductStyles(self):
        """Re-apply the product visual language.

        The button style sheet is built from the active theme, so it has to be
        rebuilt whenever the theme changes.
        """
        apply_button_style(self.startBtn, "primary")
        apply_button_style(self.cancelBtn, "danger")
        apply_button_style(self.pauseBtn, "quiet")
        apply_button_style(self.clearBtn, "quiet")
        apply_button_style(self.browseBtn, "quiet")
        # The page and panel surfaces repaint themselves from product_ui, so only
        # the panel border, which is a style sheet, has to be rebuilt here.
        self.compressionCard.setStyleSheet(
            "#compressionCard { border: 1px solid %s; border-radius: 12px; }"
            % panel_border())
        self._applySettingsButtonStyle()
        self.dropZone.refreshTheme()
        # The caption is painted by DWM from the Windows appearance, not from the
        # theme this window resolved, so it has to be told explicitly.
        apply_title_bar_theme(self, isDarkTheme())
        if self.settingsDialog is not None:
            apply_title_bar_theme(self.settingsDialog, isDarkTheme())

    def _arrange_compression_panel(self, compact):
        """Move the SAME three buttons between the title row and their own row."""
        if compact == self._compressionCompact:
            return
        self._compressionCompact = compact
        buttons = (self.pauseBtn, self.cancelBtn, self.startBtn)
        for button in buttons:
            self.btnRow.removeWidget(button)
            self.actionBarLayout.removeWidget(button)
        if compact:
            self.settingsLayout.setContentsMargins(16, 8, 16, 10)
            self.settingsLayout.setSpacing(4)
            self.formatSelector.setMinimumWidth(160)
            self.formatSelector.setMaximumWidth(400)
            self.formatRow.setStretch(0, 1)
            self.formatRow.setStretch(1, 0)
            for button in buttons:
                self.actionBarLayout.addWidget(button)
            self.actionBar.setVisible(True)
        else:
            self.settingsLayout.setContentsMargins(16, 10, 16, 12)
            self.settingsLayout.setSpacing(5)
            self.formatSelector.setFixedWidth(400)
            self.formatRow.setStretch(0, 0)
            self.formatRow.setStretch(1, 1)
            for button in buttons:
                self.btnRow.addWidget(button)
            self.actionBar.setVisible(False)
        self.settingsLayout.invalidate()
        self.compressionCard.updateGeometry()

    def eventFilter(self, watched, event):
        if (
            hasattr(self, "emptyState")
            and watched is self.queueView.viewport()
            and event.type() == QEvent.Type.Resize
        ):
            self.emptyState.setGeometry(self.queueView.viewport().rect())
        return super().eventFilter(watched, event)

    def _finishEmptyFade(self):
        self.emptyState.setVisible(self._emptyTargetVisible)

    def _setEmptyStateVisible(self, visible):
        if self._emptyTargetVisible == visible:
            return
        self._emptyTargetVisible = visible
        self._emptyFade.stop()
        if visible:
            self.emptyState.show()
        self._emptyFade.setStartValue(self._emptyOpacity.opacity())
        self._emptyFade.setEndValue(1.0 if visible else 0.0)
        self._emptyFade.start()

    def _updateViewToggleStyle(self, *_):
        """Icon emphasis, hover / pressed feedback and the sliding indicator.

        All three use the BatchZip accent, so the toggle reads as one continuous
        Fluent control instead of two icons that swap colour instantly.
        """
        accent = qconfig.themeColor.value
        r, g, b = accent.red(), accent.green(), accent.blue()
        selected = QColor(r, g, b)
        inactive = QColor(145, 151, 160) if isDarkTheme() else QColor(126, 133, 143)
        hover_alpha = 30 if isDarkTheme() else 22
        press_alpha = 52 if isDarkTheme() else 40
        for button, icon in (
            (self.listViewButton, FluentIcon.MENU),
            (self.gridViewButton, FluentIcon.TILES),
        ):
            button.setIcon(icon.icon(color=selected if button.isChecked() else inactive))
            button.setStyleSheet(
                "QToolButton { background: transparent; border: none; border-radius: 6px; }"
                f"QToolButton:hover {{ background: rgba({r},{g},{b},{hover_alpha}); }}"
                f"QToolButton:pressed {{ background: rgba({r},{g},{b},{press_alpha}); }}"
            )
        self.viewIndicator.setStyleSheet(
            "#queueViewIndicator { background: rgba(%d,%d,%d,%d); border-radius: 6px; }"
            % (r, g, b, 52 if isDarkTheme() else 34)
        )
        target = (self.gridViewButton if self.gridViewButton.isChecked()
                  else self.listViewButton).geometry()
        if self.viewIndicator.geometry() == target:
            return
        if self.viewIndicator.geometry().isNull() or not self.isVisible():
            self._place_view_indicator()               # not laid out yet: no slide
            return
        # Interruptible on purpose: a second click retargets the slide from
        # wherever the surface is right now, so rapid toggling turns rather than
        # queueing one animation per click.
        self.viewIndicatorAnim.stop()
        self.viewIndicatorAnim.setStartValue(self.viewIndicator.geometry())
        self.viewIndicatorAnim.setEndValue(target)
        self.viewIndicatorAnim.start()

    def setQueueView(self, grid):
        if self.gridView == grid:
            return
        self.gridView = grid
        self.queueView.set_grid_mode(grid)

    # =====================================================
    # 压缩格式
    # =====================================================

    def setArchiveFormat(self, fmt):

        self.archiveFormat = fmt

    # =====================================================
    # 输出路径
    # =====================================================

    def chooseOutputFolder(self):

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Output Folder"
        )

        if folder:
            self.outputEdit.setText(folder)

    # =====================================================
    # 添加任务
    # =====================================================

    def handleFiles(self, paths):

        if self.isCompressing:
            return

        if len(paths) > 1 and all(os.path.isfile(path) for path in paths):
            paths = sorted(
                paths,
                key=lambda path: (
                    tuple(
                        int(part) if part.isdigit() else part
                        for part in re.split(r"(\d+)", os.path.basename(path).casefold())
                    ),
                    os.path.normcase(os.path.abspath(path)),
                ),
            )

        existing_paths = {
            os.path.normcase(os.path.abspath(task.path))
            for task in self.queueModel.ordered_tasks()
        }
        added = 0
        skipped = 0

        for path in paths:

            normalized = os.path.normcase(os.path.abspath(path))

            if not path or not os.path.exists(path) or normalized in existing_paths:
                skipped += 1
                continue

            self.queueModel.append_task(Task(path))

            existing_paths.add(normalized)
            added += 1

        self.updateDensity()

        if skipped:
            self.statusLabel.setText(
                f"Added {added} · Skipped {skipped} invalid or duplicate item(s)"
            )

    # =====================================================
    # 开始压缩（后台线程）
    # =====================================================

    def startCompress(self):

        if self.queueModel.rowCount() == 0 or self.isCompressing:
            return

        pending_tasks = [
            task
            for task in self.queueModel.ordered_tasks()
            if task.status in ("Waiting", "Failed", "Cancelled")
        ]

        if not pending_tasks:
            self.statusLabel.setText("No pending tasks")
            return

        for task in pending_tasks:
            task.status = "Waiting"
            task.progress = 0
            task.error_message = ""
            self.queueModel.notify_task_changed(task)

        self._set_session_paused(False)
        self._set_compression_session_active(True)

        self.thread = CompressThread(
            pending_tasks,
            self.outputEdit.text().strip(),
            self.archiveFormat
        )

        self.thread.taskStarted.connect(self.onTaskStarted)
        self.thread.taskProgress.connect(self.onTaskProgress)
        self.thread.taskFinished.connect(self.onTaskFinished)
        self.thread.taskCancelled.connect(self.onTaskCancelled)
        self.thread.overallStatus.connect(self.statusLabel.setText)
        self.thread.allFinished.connect(self.onAllFinished)
        self.thread.cancelled.connect(self.onCompressionCancelled)
        self.thread.error.connect(self.onWorkerError)
        self.thread.finished.connect(self.onThreadEnded)

        try:
            self.thread.start()
        except RuntimeError as exc:
            self.thread = None
            self._set_session_paused(False)
            self._set_compression_session_active(False)

            self.statusLabel.setText("Compression could not start")

            QMessageBox.critical(
                self,
                "BatchZip",
                "Unable to Start Compression\n\n"
                "What happened:\n"
                "The background compression worker could not be started.\n\n"
                f"Details:\n{exc}\n\n"
                "Suggestion:\n"
                "Try again. If the problem continues, restart BatchZip."
            )

    # =====================================================
    # Worker 信号 → TaskQueueController（按 Task identity 定位）
    # =====================================================

    def onTaskStarted(self, task):

        self.queueController.on_task_started(task)

    def onTaskProgress(self, task, percent):

        self.queueController.on_task_progress(task, percent)

    def onTaskFinished(self, task, result):

        self.queueController.on_task_finished(task, result)

    def togglePause(self):

        if not self.thread:
            return

        if self.isPaused:

            self.thread.resume()

            self.pauseBtn.setText("Pause")
            self.pauseBtn.setIcon(FluentIcon.PAUSE)

            self._set_session_paused(False)

        else:

            self.thread.pause()

            self.pauseBtn.setText("Resume")
            self.pauseBtn.setIcon(FluentIcon.PLAY)

            self._set_session_paused(True)

    def cancelCompression(self):

        if not self.thread or not self.thread.isRunning():
            return

        reply = QMessageBox.question(
            self,
            "BatchZip",
            "Cancel the current compression?\n\nThe incomplete archive will be removed.",
            QMessageBox.StandardButton.Yes |
            QMessageBox.StandardButton.No
        )

        if reply != QMessageBox.StandardButton.Yes:
            return

        self.statusLabel.setText("Cancelling...")
        self.pauseBtn.setEnabled(False)
        self.cancelBtn.setEnabled(False)
        self.thread.cancel()

    def onTaskCancelled(self, task):

        self.queueController.on_task_cancelled(task)

    def onCompressionCancelled(self):

        self._set_session_paused(False)
        self._set_compression_session_active(False)

        self.pauseBtn.setText("Pause")
        self.pauseBtn.setIcon(FluentIcon.PAUSE)
        self.statusLabel.setText("Cancelled")

    def onAllFinished(self, success, warnings, failed, folder):

        self._set_session_paused(False)
        self._set_compression_session_active(False)

        self.pauseBtn.setText("Pause")
        self.pauseBtn.setIcon(FluentIcon.PAUSE)

        self.statusLabel.setText(
            f"Completed: {success} · Warnings: {warnings} · Failed: {failed}"
        )

        warning_tasks = [
            task
            for task in self.queueModel.ordered_tasks()
            if task.status == "Completed with warnings"
        ]

        warning_actions = {}

        for task in warning_tasks:
            dialog = WarningArchiveDialog(task, self)
            dialog.exec()
            warning_actions[id(task)] = dialog.archive_action

        failed_tasks = [
            task
            for task in self.queueModel.ordered_tasks()
            if task.status == "Failed" and task.error_message
        ]

        self.showCompleteDialog(
            success,
            warnings,
            failed,
            folder,
            warning_tasks,
            failed_tasks,
            warning_actions,
        )

    def onWorkerError(self, message):

        self._set_session_paused(False)
        self._set_compression_session_active(False)

        for task in self.queueModel.ordered_tasks():
            if task.status == "Compressing":
                task.error_message = message
                self.queueController.on_task_finished(task, "Failed")

        QMessageBox.critical(
            self,
            "BatchZip",
            message
        )

    def onThreadEnded(self):

        finished_thread = self.sender()

        if finished_thread is not None:
            finished_thread.deleteLater()

        if self.thread is finished_thread:
            self.thread = None

    def setCompressionControls(self, running):

        self.startBtn.setEnabled(not running)
        self.pauseBtn.setEnabled(running)
        self.cancelBtn.setEnabled(running)
        self.clearBtn.setEnabled(not running and self.queueModel.rowCount() > 0)
        self.outputEdit.setEnabled(not running)
        self.browseBtn.setEnabled(not running)
        self.formatSelector.setEnabled(not running)
        self.dropZone.setEnabled(not running)

        self.queueView.set_queue_locked(running)

    def _set_compression_session_active(self, active):
        self.isCompressing = active
        self.setCompressionControls(active)

    def _set_session_paused(self, paused):
        self.isPaused = paused
        self.queueController.set_paused(paused)

    # =====================================================
    # 完成弹窗
    # =====================================================

    def showCompleteDialog(
        self,
        success,
        warnings,
        failed,
        folder,
        warning_tasks,
        failed_tasks,
        warning_actions,
    ):

        dialog = CompleteDialog(
            success,
            warnings,
            failed,
            folder,
            warning_tasks,
            failed_tasks,
            warning_actions,
        )

        dialog.exec()

    # =====================================================
    # 清空任务
    # =====================================================

    def clearTasks(self):

        if self.isCompressing:
            return

        self.queueModel.clear()

        self.updateDensity()

    # =====================================================
    # 拖拽区动画
    # =====================================================

    def animateDropZone(self, height):
        # Original RC5 density behaviour. In the compact strip the band owns the
        # height instead, so the hint is only recorded there.
        self._dropZoneDensity = height
        if self._layoutMode in (self.MODE_ORIGINAL, None):
            self.dropZone.setFixedHeight(190 if height >= 180 else 150)

    # =====================================================
    # 队列密度 / 空态
    # =====================================================

    def updateDensity(self):

        count = self.queueModel.rowCount()
        self.queueTitle.setText(f"Task Queue ({count})")
        self._setEmptyStateVisible(count == 0)
        self.clearBtn.setEnabled(count > 0 and not self.isCompressing)

        if count == 0:
            height = 300

        elif count < 5:
            height = 180

        else:
            height = 140

        self.dropZone.resetPrompt()

        self.animateDropZone(height)
        # The task count just changed, which is what the workspace policy keys
        # on. Funnelling it through the one seam keeps add / delete / clear and
        # batch inserts on the same rule.
        self._update_workspace_layout()

    # =====================================================
    # 关闭窗口：安全收尾后台线程
    # =====================================================

    def closeEvent(self, event: QCloseEvent):

        if self.thread and self.thread.isRunning():

            reply = QMessageBox.question(
                self,
                "BatchZip",
                "Compression is still running.\n\nStop compression and exit?",
                QMessageBox.StandardButton.Yes |
                QMessageBox.StandardButton.No
            )

            if reply == QMessageBox.StandardButton.No:
                event.ignore()
                return

            self.thread.stop()

            if not self.thread.wait(6000):
                QMessageBox.critical(
                    self,
                    "BatchZip",
                    "Unable to Close BatchZip\n\n"
                    "What happened:\nThe compression thread did not stop in time.\n\n"
                    "Suggestion:\nWait for 7-Zip to finish or stop it manually, then try again."
                )
                event.ignore()
                return

            if self.thread.stop_error:
                QMessageBox.critical(
                    self,
                    "BatchZip",
                    self.thread.stop_error
                )
                event.ignore()
                return

        event.accept()
