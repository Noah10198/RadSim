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
    QDialog, QHeaderView, QHBoxLayout, QLabel, QLineEdit,
    QMenu, QMessageBox, QPushButton, QSplitter, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction, QBrush, QColor
import copy

from core.gdml_tree import GdmlNodeType
from ui.dialogs.analysis_common import (
    QuantityListPanel, HistogramListPanel, DIALOG_STYLE,
    quantity_meta, supports_histogram, fit_size_to_screen,
    histogram_parameter_conflicts,
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
        # Final default size, requested while the dialog is still hidden so
        # its native window is born at this size, and re-applied in showEvent
        # before the first paint. (A delayed resize after the first activation
        # makes the window visibly jump and briefly leaves a blank strip.)
        self._default_size = (1150, 740)
        self._size_applied = False
        self.resize(*fit_size_to_screen(self, *self._default_size))

    def showEvent(self, event):
        super().showEvent(event)
        if not getattr(self, "_size_applied", False) and self.isVisible():
            self._size_applied = True
            self.resize(*fit_size_to_screen(self, *self._default_size))

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
        self._tree.setHeaderLabels(["Logical volume", "Configured"])
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch)
        self._tree.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Fixed)
        self._tree.setColumnWidth(1, 118)
        self._tree.setMinimumWidth(230)
        # Multi-select (Ctrl/Shift): while several logical volumes are
        # selected they form a transient group - adding a row, editing one of
        # its cells (filter / bins / range / log) or deleting the row is
        # mirrored onto every selected volume at the matching row. The group
        # lasts only as long as the selection does; changing the selection
        # dissolves it and each volume goes back to being edited alone.
        self._tree.setSelectionMode(
            QTreeWidget.SelectionMode.ExtendedSelection)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        # Right-click on a volume row: wipe its full quantity/histogram
        # configuration (multi-selection wipes every selected volume).
        self._tree.setContextMenuPolicy(
            Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(
            self._on_tree_context_menu)
        lv.addWidget(self._tree, 1)
        split.addWidget(left)

        # Right: quantities + histograms
        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(4, 0, 0, 0)
        rv.setSpacing(6)

        # Elastic panels fill the dialog height. Both get the SAME stretch
        # factor and the same minimum height so the two lists grow by the
        # same amount when the dialog is resized and show a comparable
        # number of rows by default (same alignment as the probe dialog).
        self._q_panel = QuantityListPanel(stretchable=True,
                                          scroll_min_height=150)
        self._q_panel.changed.connect(self._on_config_changed)
        self._q_panel.nameEdited.connect(self._on_quantity_renamed)
        self._q_panel.userAdded.connect(
            lambda q: self._apply_added_to_selected(q, "qs"))
        self._q_panel.userRemoved.connect(
            lambda idx: self._remove_from_selected(idx, "qs"))
        rv.addWidget(self._q_panel, 1)

        self._h_panel = HistogramListPanel(stretchable=True,
                                           scroll_min_height=150)
        self._h_panel.changed.connect(self._on_config_changed)
        self._h_panel.userAdded.connect(
            lambda h: self._apply_added_to_selected(h, "hs"))
        self._h_panel.userRemoved.connect(
            lambda idx: self._remove_from_selected(idx, "hs"))
        rv.addWidget(self._h_panel, 1)

        self._summary = QLabel("No logical volume selected")
        # Word wrap: the multi-selection hint must never stretch this line
        # wide (a single unwrapped long text would force the right-hand pane
        # wider and squeeze the left geometry tree/search box).
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: #888888; font-size: 11px;")
        rv.addWidget(self._summary)

        split.addWidget(right)
        split.setSizes([350, 770])
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
        save_btn.clicked.connect(self._save)
        btns.addWidget(save_btn)
        layout.addLayout(btns)

        # The form is edited heavily with the keyboard, so Enter must never
        # activate any button here (especially Save). Saving happens only via
        # an explicit mouse click on the Save button: no default button, and
        # no button reacts to Enter when focused either (same as probe/voxel).
        for _btn in self.findChildren(QPushButton):
            _btn.setAutoDefault(False)

    # -- Geometry hierarchy tree (isomorphic to the main-window project tree:
    #    file -> World -> Volume) --

    def _populate_volumes(self):
        self._tree.clear()
        self._name_to_item.clear()
        for file_node in self._agent.get_all_file_nodes():
            # A GDML file defines each logical volume once; physical
            # placements only reference it. Walking the raw world subtree
            # would therefore list the same logical volume once per
            # placement (lhcbvelo: 59 LVs -> ~1700 tree items). Keep each
            # logical volume in the tree exactly once (first occurrence).
            self._seen_volumes = set()
            file_item = QTreeWidgetItem(self._tree, [file_node.name])
            file_item.setData(0, NAME_ROLE, "")
            self._make_container_item(file_item)
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
        self._refresh_statuses()

    def _make_container_item(self, item: QTreeWidgetItem):
        """A container row (file / world) is structural only - not a logical
        volume, so it must not be selectable/editable as a config target."""
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)

    def _build_file_tree(self, parent_item, file_node) -> int:
        count = 0
        for world in (c for c in file_node.children
                      if c.node_type == GdmlNodeType.WORLD_NODE):
            w_item = QTreeWidgetItem(parent_item, [world.name])
            w_item.setData(0, NAME_ROLE, "")
            self._make_container_item(w_item)
            # The world node itself is a pure grouping container - never a
            # selectable LV (its own volume box is not something one scores
            # on). The volume-tree builder skips WORLD_NODE and promotes its
            # subtree, so no duplicate selectable row is created.
            n = self._build_volume_tree(w_item, world)
            if n == 0:
                parent_item.removeChild(w_item)
            else:
                count += n
                w_item.setExpanded(True)
        return count

    def _build_volume_tree(self, parent_item, node) -> int:
        # Skip definition (SOLID_DEF), pure placeholder (PHYVOL_NODE) and the
        # world wrapper (WORLD_NODE) nodes and promote their children, so no
        # selectable LV row is created for the world volume itself.
        if node.node_type in (GdmlNodeType.SOLID_DEF,
                              GdmlNodeType.PHYVOL_NODE,
                              GdmlNodeType.WORLD_NODE):
            n = 0
            for child in node.children:
                n += self._build_volume_tree(parent_item, child)
            return n
        name = getattr(node, "_display_name", None) or node.name or "(unnamed)"
        if name in self._seen_volumes:
            # This logical volume is placed again here (physical instance);
            # it is already in the tree as a configurable LV, so skip the
            # whole (duplicate) subtree.
            return 0
        self._seen_volumes.add(name)
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

    # -- Configured-status column --

    def _configured_brush(self):
        return QBrush(QColor("#7bd88f" if self._dark else "#2e7d32"))

    def _unconfigured_brush(self):
        return QBrush(QColor("#6c7086" if self._dark else "#a8a8a8"))

    def _refresh_statuses(self):
        """Fill the second tree column so that one can see at a glance which
        logical volumes already have quantities/histograms configured.

        Column content:
          logical volume -> "✓ 2q 1h" when configured, empty otherwise
          container rows (file / world) -> "configured/total" summary
        """
        def walk(item):
            conf = total = 0
            lv = item.data(0, NAME_ROLE)
            if lv:
                # Every logical volume counts once towards its containers'
                # totals, regardless of whether it is configured yet.
                total = 1
                c = self._cfg.get(lv) or {}
                nq = len(c.get("qs", []))
                nh = len(c.get("hs", []))
                if nq or nh:
                    conf = 1
                    item.setText(1, f"✓ {nq}q {nh}h")
                else:
                    item.setText(1, "")
            else:
                item.setText(1, "")
            for i in range(item.childCount()):
                t, c2 = walk(item.child(i))
                total += t
                conf += c2
            # Container rows show an aggregate of their subtree
            if not lv and total:
                item.setText(1, f"{conf}/{total}")
            if conf:
                item.setForeground(1, self._configured_brush())
            else:
                item.setForeground(1, self._unconfigured_brush())
            return total, conf

        for i in range(self._tree.topLevelItemCount()):
            walk(self._tree.topLevelItem(i))

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

    def _selected_lv_names(self) -> list:
        """Logical volumes currently selected in the tree (container rows
        carry an empty NAME_ROLE and are not selectable anyway)."""
        return [it.data(0, NAME_ROLE)
                for it in self._tree.selectedItems()
                if it.data(0, NAME_ROLE)]

    def _primary_lv_name(self) -> str:
        """The logical volume whose settings the right panel edits. With a
        multi-selection this is the last clicked/current item - the one that
        owns the visible Quantity/Histogram rows. New rows are created for it
        and then replicated onto the remaining selected volumes."""
        cur = self._tree.currentItem()
        if (cur is not None and cur.isSelected()
                and cur.data(0, NAME_ROLE)):
            return cur.data(0, NAME_ROLE)
        names = self._selected_lv_names()
        return names[0] if names else ""

    def _on_selection_changed(self):
        names = self._selected_lv_names()
        if not names:
            return
        primary = self._primary_lv_name()
        if not primary:
            return
        if primary == self._current_name:
            # Selection grew/shrunk around the same primary volume: keep the
            # current editing panel, only refresh the summary/status columns.
            self._update_summary(primary)
            self._refresh_statuses()
            return
        self._load_volume(primary)

    def _apply_added_to_selected(self, snapshot: dict, key: str):
        """A row was just added on the primary volume (see _primary_lv_name).
        When several logical volumes are selected, append a deep copy of that
        row to every other selected volume - their pre-existing quantities /
        histograms are kept untouched."""
        names = self._selected_lv_names()
        if len(names) <= 1 or not self._current_name:
            return
        for n in names:
            if n == self._current_name:
                continue
            cfg = self._cfg.setdefault(n, {"qs": [], "hs": []})
            cfg.setdefault(key, []).append(copy.deepcopy(snapshot))
        self._refresh_statuses()
        self._update_summary(self._current_name)

    @staticmethod
    def _mirror_rows(target: list, source: list, id_fn) -> bool:
        """Overwrite every aligned row of `target` with its counterpart in
        `source` (same index + same identity). Rows whose identity differs
        (i.e. they were configured separately, not born from this selection
        group) and rows beyond the shared length are left untouched."""
        n = min(len(target), len(source))
        changed = False
        for i in range(n):
            if (id_fn(target[i]) == id_fn(source[i])
                    and target[i] != source[i]):
                target[i] = copy.deepcopy(source[i])
                changed = True
        return changed

    def _mirror_edits_to_selected(self):
        """Transient group edit: while several volumes are selected, a change
        made on the primary (editing filter / bins / range / log, renaming a
        row...) is mirrored onto the other selected volumes at the matching
        row. Dissolves as soon as the selection changes."""
        if not self._current_name:
            return
        others = [n for n in self._selected_lv_names()
                  if n and n != self._current_name]
        if not others:
            return
        primary = self._cfg.get(self._current_name)
        if not primary:
            return
        p_qs, p_hs = primary.get("qs", []), primary.get("hs", [])
        touched = False
        for n in others:
            cfg = self._cfg.setdefault(n, {"qs": [], "hs": []})
            qs = cfg.setdefault("qs", [])
            hs = cfg.setdefault("hs", [])
            touched |= self._mirror_rows(
                qs, p_qs, lambda q: str(q.get("name") or ""))
            touched |= self._mirror_rows(
                hs, p_hs, lambda h: str(h.get("q") or ""))
        if touched:
            self._refresh_statuses()
            self._update_summary(self._current_name)

    def _remove_from_selected(self, idx: int, key: str):
        """A row was deleted on the primary volume: drop the row at the same
        index from every other selected volume (no-op when a volume has no
        such row)."""
        if not self._current_name or idx < 0:
            return
        for n in (x for x in self._selected_lv_names()
                  if x and x != self._current_name):
            cfg = self._cfg.get(n)
            if not cfg:
                continue
            lst = cfg.get(key)
            if lst and idx < len(lst):
                del lst[idx]
        self._refresh_statuses()
        self._update_summary(self._current_name)

    # -- Tree context menu: wipe a volume's whole configuration --

    def _on_tree_context_menu(self, pos):
        item = self._tree.itemAt(pos)
        if item is None:
            return
        name = item.data(0, NAME_ROLE)
        if not name:
            return  # container rows (file / world) are not config targets
        sel = self._selected_lv_names()
        # A right-click wipes the clicked volume alone, unless that row is
        # already part of the active multi-selection (then every selected
        # volume is wiped). The selection is NOT touched here: dismissing
        # the menu or cancelling the confirmation below must leave the
        # current editing panel exactly as it was.
        if name in sel:
            targets = sel
        else:
            targets = [name]
        menu = QMenu(self)
        if len(targets) > 1:
            act = menu.addAction(
                f"Clear quantity/histogram config of "
                f"{len(targets)} selected volumes")
        else:
            act = menu.addAction(
                "Clear this volume's quantity/histogram config")
        if menu.exec(self._tree.viewport().mapToGlobal(pos)) is not act:
            return
        if not self._confirm_clear(len(targets)):
            return
        # Only a committed wipe may pull the panel over to the clicked
        # volume (i.e. when it was not part of the selection before).
        if name not in sel:
            self._tree.clearSelection()
            item.setSelected(True)
            self._tree.setCurrentItem(item)
        for n in targets:
            self._cfg.pop(n, None)
        if self._current_name in targets:
            self._load_volume(self._current_name)
        else:
            self._refresh_statuses()
            self._update_summary(self._current_name)

    def _confirm_clear(self, count: int) -> bool:
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("Clear configuration")
        box.setText(
            f"Delete ALL quantity and histogram settings on {count} "
            "logical volume(s)?\n\nThis includes settings added earlier "
            "and cannot be undone.")
        yes = box.addButton("Clear",
                            QMessageBox.ButtonRole.DestructiveRole)
        box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        return box.clickedButton() is yes

    def _load_volume(self, name: str):
        self._save_current()
        self._current_name = name
        cfg = self._cfg.get(name, {"qs": [], "hs": []})
        self._q_panel.set_quantities(cfg.get("qs", []))
        self._h_panel.set_histograms(cfg.get("hs", []))
        self._sync_qnames()
        self._update_summary(name)
        self._refresh_statuses()

    def _on_config_changed(self):
        if self._current_name:
            # Write the live panel state into _cfg first so the status column
            # immediately reflects edits made on the currently selected volume.
            self._save_current()
            self._mirror_edits_to_selected()
            self._sync_qnames()
            self._update_summary(self._current_name)
            self._refresh_statuses()

    def _sync_qnames(self):
        qs = self._q_panel.get_quantities()
        usable = []
        units = {}
        types = {}
        for q in qs:
            if supports_histogram(q["type"]):
                usable.append(q["name"])
                _, hx = quantity_meta(q["type"])
                units[q["name"]] = hx or ""
                # Lets the histogram rows suggest a per-type default range.
                types[q["name"]] = q["type"]
        self._h_panel.set_qnames(usable, units, types)

    def _on_quantity_renamed(self, old_name, new_name):
        """Follow a quantity rename in the 1D-histogram rows whose target
        equals the old name (rows stay free-form otherwise). While several
        volumes are selected the rename also propagates to the same quantity
        / histogram rows on the other selected volumes (transient group)."""
        self._h_panel.rename_target(old_name, new_name)
        if not old_name or not new_name or not self._current_name:
            return
        for n in (x for x in self._selected_lv_names()
                  if x and x != self._current_name):
            cfg = self._cfg.get(n)
            if not cfg:
                continue
            for q in cfg.get("qs", []):
                if str(q.get("name") or "") == old_name:
                    q["name"] = new_name
            for h in cfg.get("hs", []):
                if str(h.get("q") or "") == old_name:
                    h["q"] = new_name
        self._refresh_statuses()

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
        text = (f"logical volume {name}: {nq} quantities, {nh} histograms"
                + (" (not configured)" if not nq and not nh else ""))
        extra = len(self._selected_lv_names()) - 1
        if extra > 0:
            text += (f"  ·  {extra + 1} volumes selected — every add / "
                     f"edit / delete applies to all of them together "
                     f"(right-click a volume to clear its config)")
        self._summary.setText(text)

    def _save(self):
        self._save_current()
        # The same quantity type may be scored with different histogram
        # settings across logical volumes; such histograms are drawn together
        # on one chart, so warn while the form is still visible (mirrors the
        # probe dialog). histogram_parameter_conflicts accepts entries with an
        # "lv" label for realworld volumes.
        entries = [{"lv": lv, "qs": (v or {}).get("qs", []),
                    "hs": (v or {}).get("hs", [])}
                   for lv, v in self._cfg.items()]
        conflicts = histogram_parameter_conflicts(entries)
        if conflicts:
            box = QMessageBox(self)
            box.setIcon(QMessageBox.Icon.Warning)
            box.setWindowTitle("Inconsistent histogram settings")
            box.setText(
                "The same quantity type is scored with different histogram "
                "settings across logical volumes. Such histograms are drawn "
                "together on one chart, and misaligned binning makes the "
                "comparison misleading. Save anyway?")
            box.setDetailedText("\n\n".join(conflicts))
            back_btn = box.addButton("Back to edit",
                                     QMessageBox.ButtonRole.RejectRole)
            save_btn = box.addButton("Save anyway",
                                     QMessageBox.ButtonRole.AcceptRole)
            box.setDefaultButton(back_btn)
            box.exec()
            if box.clickedButton() is not save_btn:
                return
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
        # Re-brush the status column when the theme changes
        self._refresh_statuses()
