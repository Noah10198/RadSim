"""
RealWorldDialog - realworld analysis configuration (geometry hierarchy tree
on the left, quantity/histogram panel on the right)

Follows doc/realworld_ui_design.md:
  Left: geometry hierarchy tree (file -> World -> Volume, expandable and
        searchable, same structure as in the main window)
  Right: quantity settings of the selected logical volume + energy spectrum
         histograms (they follow the current selection)
Non-modal dialog - the user can keep operating the main window while configuring.
Pressing [Save Configuration] writes it into the task and closes the window.
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTreeWidget, QTreeWidgetItem, QLineEdit, QSplitter, QWidget,
)
from PyQt6.QtCore import Qt, QTimer

from core.gdml_tree import GdmlNodeType
from ui.dialogs.analysis_common import (
    QuantityListPanel, HistogramListPanel, DIALOG_STYLE,
    supports_histogram,
)

NAME_ROLE = Qt.ItemDataRole.UserRole


class RealWorldDialog(QDialog):
    """realworld analysis: configure quantities + histograms per logical
    volume."""

    CONFIG_KEY = "realworld"

    def __init__(self, parent=None, task=None, gdml_agent=None):
        super().__init__(parent)
        self._task = task
        self._agent = gdml_agent
        self._dark = False
        self._cfg: dict = {}          # LVname -> {"qs": [], "hs": []}
        self._current_name: str = ""
        self._name_to_item: dict = {}

        self.setWindowTitle("RealWorld Analysis Settings")
        self.setModal(False)          # non-modal: the main window stays usable while configuring
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        self._load_existing()
        self._build_ui()
        self._populate_volumes()
        self._apply_theme()
        # On first activation the layout shrinks the window to its sizeHint
        # (overriding the resize done before build_ui), so the default size
        # is forced back once after the first show
        self._default_size = (960, 700)
        self._size_applied = False

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_size_applied", False) and self.isVisible():
            self._size_applied = True
            QTimer.singleShot(0, lambda: self.resize(*self._default_size))

    # -- Data --

    def _load_existing(self):
        cfg = (self._task.analysis_config or {}).get(self.CONFIG_KEY, {})
        self._cfg = cfg.get("volumes", {}) if isinstance(cfg, dict) else {}

    # ── UI ──

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        title = QLabel(
            "RealWorld analysis: pick a logical volume in the geometry tree on the left, then add a quantity / histogram."
            "Non-modal; adjust settings while viewing the main window.")
        title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(title)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)

        # Left: search box + geometry hierarchy tree
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(4)
        self._search = QLineEdit()
        self._search.setPlaceholderText("🔍 Search logical volumes…")
        self._search.textChanged.connect(self._on_search)
        lv.addWidget(self._search)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setMinimumWidth(230)
        self._tree.setSelectionMode(
            QTreeWidget.SelectionMode.SingleSelection)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        lv.addWidget(self._tree, 1)
        split.addWidget(left)

        # Right: quantities + histograms
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.setSpacing(6)

        self._q_panel = QuantityListPanel()
        self._q_panel.changed.connect(self._on_config_changed)
        rv.addWidget(self._q_panel)

        self._h_panel = HistogramListPanel()
        self._h_panel.changed.connect(self._on_config_changed)
        rv.addWidget(self._h_panel)

        self._summary = QLabel("No logical volume selected")
        self._summary.setStyleSheet("color: #888888; font-size: 11px;")
        rv.addWidget(self._summary)

        split.addWidget(right)
        split.setSizes([340, 580])
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)
        layout.addWidget(split, 1)

        # Bottom buttons
        btns = QHBoxLayout()
        btns.addStretch()
        close_btn = QPushButton("✕ Close")
        close_btn.clicked.connect(self.close)
        btns.addWidget(close_btn)
        save_btn = QPushButton("✅ Save config")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

    # -- Geometry hierarchy tree (isomorphic to the main-window project tree:
    #    file -> World -> Volume) --

    def _populate_volumes(self):
        self._tree.clear()
        self._name_to_item.clear()
        for file_node in self._agent.get_all_file_nodes():
            file_item = QTreeWidgetItem(self._tree, [file_node.name])
            file_item.setData(0, NAME_ROLE, "")
            n = self._build_file_tree(file_item, file_node)
            if n == 0:
                self._tree.takeTopLevelItem(
                    self._tree.indexOfTopLevelItem(file_item))
                continue
            file_item.setExpanded(True)
        # Select the first logical volume by default
        if self._name_to_item:
            first = next(iter(self._name_to_item.values()))
            self._tree.setCurrentItem(first)

    def _build_file_tree(self, parent_item, file_node) -> int:
        count = 0
        for world in (c for c in file_node.children
                      if c.node_type == GdmlNodeType.WORLD_NODE):
            w_item = QTreeWidgetItem(parent_item, [world.name])
            w_item.setData(0, NAME_ROLE, "")
            n = self._build_volume_tree(w_item, world)
            if n == 0:
                parent_item.removeChild(w_item)
            else:
                count += n
                w_item.setExpanded(True)
        return count

    def _build_volume_tree(self, parent_item, node) -> int:
        # Skip definition (SOLID_DEF) and pure placeholder (PHYVOL_NODE) nodes
        # and promote their children
        if node.node_type in (GdmlNodeType.SOLID_DEF,
                              GdmlNodeType.PHYVOL_NODE):
            n = 0
            for child in node.children:
                n += self._build_volume_tree(parent_item, child)
            return n
        name = getattr(node, "_display_name", None) or node.name or "(unnamed)"
        item = QTreeWidgetItem(parent_item, [name])
        item.setData(0, NAME_ROLE, name)
        item.setToolTip(
            0, f"Type: {node.node_type.name}\n"
            f"Material: {node.material_name or '-'}")
        self._name_to_item[name] = item
        n = 1
        for child in node.children:
            n += self._build_volume_tree(item, child)
        return n

    def _on_search(self, text: str):
        text = text.strip().lower()
        for name, item in self._name_to_item.items():
            match = (not text) or (text in name.lower())
            item.setHidden(not match)
            if match:
                p = item.parent()
                while p is not None:
                    p.setHidden(False)
                    p.setExpanded(True)
                    p = p.parent()

    # -- Cross-widget sync --

    def _on_selection_changed(self):
        items = self._tree.selectedItems()
        if not items:
            return
        name = items[0].data(0, NAME_ROLE) or ""
        if name:
            self._load_volume(name)

    def _load_volume(self, name: str):
        self._save_current()
        self._current_name = name
        cfg = self._cfg.get(name, {"qs": [], "hs": []})
        self._q_panel.set_quantities(cfg.get("qs", []))
        self._h_panel.set_histograms(cfg.get("hs", []))
        self._sync_qnames()
        self._update_summary(name)

    def _on_config_changed(self):
        if self._current_name:
            self._sync_qnames()
            self._update_summary(self._current_name)

    def _sync_qnames(self):
        qs = self._q_panel.get_quantities()
        usable = [q["name"] for q in qs if supports_histogram(q["type"])]
        self._h_panel.set_qnames(usable)

    def _save_current(self):
        """Write the current panel state back into self._cfg for the
        corresponding logical volume."""
        if not self._current_name:
            return
        self._cfg[self._current_name] = {
            "qs": self._q_panel.get_quantities(),
            "hs": self._h_panel.get_histograms(),
        }

    def _update_summary(self, name: str):
        cfg = self._cfg.get(name, {"qs": [], "hs": []})
        nq = len(cfg.get("qs", []))
        nh = len(cfg.get("hs", []))
        self._summary.setText(
            f"logical volume {name}: {nq} quantities, {nh} histograms"
            + (" (not configured)" if not nq and not nh else ""))

    def _save(self):
        self._save_current()
        if self._task is not None:
            cfg = self._task.analysis_config or {}
            cfg[self.CONFIG_KEY] = {"volumes": self._cfg}
            self._task.analysis_config = cfg
        configured = any(q or h for q, h in self._cfg.values())
        parent = self.parent()
        from app.main_window import MainWindow
        if isinstance(parent, MainWindow):
            parent.on_analysis_saved(self._task.name, self.CONFIG_KEY,
                                     configured)
        # Close as soon as saving is done
        self.close()

    def set_dark_theme(self, dark: bool):
        self._dark = dark
        self._apply_theme()

    def _apply_theme(self):
        self.setStyleSheet(DIALOG_STYLE(self._dark))
