"""
ProjectTreeWidget - the RadSim project tree

Structure (matches GUI_Design.md section 2 and the tree conventions):
  Project
  ├── Geometry              # imported GDML (with the volume hierarchy; the
                            # checkbox toggles visibility)
  └── Tasks                 # multiple tasks allowed; each task has:
      └── Run_001
          ├── Calculate Setting (N threads)
          ├── Particle Setting
          ├── Physics Process
          ├── Analysis
          │   ├── real world / probe / voxel
          └── Results        # results are attached here automatically once
                             # computation finishes
              └── xxx result

Styling matches gdmleditor: 13px font, 16px indentation, and selection/hover
colors follow the active theme.
"""

from typing import Optional, List

from PyQt6.QtWidgets import (
    QTreeWidget, QTreeWidgetItem, QWidget, QVBoxLayout, QMenu,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor

from core.gdml_tree import GdmlNode, GdmlNodeType


# Custom data roles (same convention as gdmleditor)
TREE_ITEM_DATA_ROLE = Qt.ItemDataRole.UserRole + 1  # GDML entry_id
TREE_NODE_TYPE_ROLE = Qt.ItemDataRole.UserRole + 2  # GdmlNodeType value
TASK_ACTION_ROLE = Qt.ItemDataRole.UserRole + 3     # task action payload
TASK_CTX_ROLE = Qt.ItemDataRole.UserRole + 4        # right-click menu context type

# task status prefix (tree node text)
TASK_STATUS_EMOJI = {
    "idle": "", "queued": "⏳", "running": "🔄",
    "completed": "✅", "failed": "❌", "stopped": "⏹",
}

# right-click menu context categories
CTX_TASKS = "tasks"          # Tasks root node
CTX_TASK = "task"            # task node
CTX_ANALYSIS = "analysis"    # Analysis child
CTX_RESULT = "result"        # result item


class ProjectTreeWidget(QWidget):
    """RadSim Project Tree - Geometry / Tasks, two-level roots."""

    node_selected = pyqtSignal(str)               # a GDML node was selected (entry_id)
    visibility_changed = pyqtSignal(str, bool)    # GDML checkbox toggled visibility
    task_action = pyqtSignal(str)                 # "action:task[:extra]" (double click)
    task_context = pyqtSignal(str, str)           # (action, payload) right-click menu

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setColumnCount(1)
        self._tree.setMinimumWidth(180)
        self._tree.setEditTriggers(QTreeWidget.EditTrigger.NoEditTriggers)
        self._tree.setSelectionBehavior(QTreeWidget.SelectionBehavior.SelectRows)
        self._tree.setAnimated(True)
        self._tree.setIndentation(16)
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self._tree)

        # -- Root --
        self._project_root = QTreeWidgetItem(self._tree, ["Project"])
        font = self._project_root.font(0)
        font.setBold(True)
        self._project_root.setFont(0, font)
        self._project_root.setExpanded(True)
        self._project_root.setFlags(
            self._project_root.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)

        # -- Geometry group (GDML parse tree) --
        self._geometry_root = QTreeWidgetItem(self._project_root, ["Geometry"])
        self._geometry_root.setExpanded(True)
        self._geometry_root.setFlags(
            self._geometry_root.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)

        # -- Tasks group (multiple tasks) --
        self._tasks_root = QTreeWidgetItem(self._project_root, ["Tasks"])
        self._tasks_root.setExpanded(True)
        self._tasks_root.setFlags(
            self._tasks_root.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        self._tasks_root.setData(0, TASK_CTX_ROLE, CTX_TASKS)

        self.set_dark_theme(False)

        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemChanged.connect(self._on_item_changed)
        self._tree.itemDoubleClicked.connect(self._on_item_double_clicked)

    # ==================== Theme ====================

    def set_dark_theme(self, is_dark: bool):
        if is_dark:
            tree_bg, tree_fg = "#1e1e2e", "#cdd6f4"
            sel_bg, sel_fg = "#313244", "#cdd6f4"
            hover_bg = "#282840"
            group_fg = "#a6adc8"
        else:
            tree_bg, tree_fg = "#ffffff", "#2c2c2c"
            sel_bg, sel_fg = "#d0e4f6", "#2c2c2c"
            hover_bg = "#e8f0fe"
            group_fg = "#555555"

        self.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {tree_bg};
                color: {tree_fg};
                border: none;
                font-size: 13px;
                outline: none;
            }}
            QTreeWidget::item {{
                padding: 4px 2px;
                border: none;
            }}
            QTreeWidget::item:selected {{
                background-color: {sel_bg};
                color: {sel_fg};
            }}
            QTreeWidget::item:hover {{
                background-color: {hover_bg};
            }}
            QTreeWidget::item:disabled {{
                color: {tree_fg};
            }}
        """)
        self._style_groups(group_fg)

    def _style_groups(self, fg: str):
        from PyQt6.QtGui import QColor
        for grp in (self._geometry_root, self._tasks_root):
            grp.setForeground(0, QColor(fg))
            f = grp.font(0)
            f.setBold(True)
            grp.setFont(0, f)

    # ==================== GDML tree ====================

    def clear_geometry(self):
        self._geometry_root.takeChildren()

    def build_from_node_tree(self, root_node: GdmlNode, progress_cb=None):
        """Build the Geometry group from the GDML parse tree (same file ->
        Solids/World structure as in gdmleditor).

        progress_cb: optional callable(done_items:int), used while rebuilding
        large geometry to keep the UI responsive (callback fired roughly every
        128 tree nodes).
        """
        self._tree_progress_cb = progress_cb
        self._tree_progress_done = 0
        try:
            self.clear_geometry()
            for file_node in root_node.children:
                if file_node.node_type != GdmlNodeType.GDML_FILE:
                    continue
                file_item = self._create_tree_item(file_node)
                self._geometry_root.addChild(file_item)
                self._build_file_tree(file_item, file_node)
            self._geometry_root.setExpanded(True)
        finally:
            self._tree_progress_cb = None

    def _build_file_tree(self, file_item: QTreeWidgetItem, file_node: GdmlNode):
        solid_nodes: List[GdmlNode] = []
        self._collect_solid_nodes(file_node, solid_nodes)
        if solid_nodes:
            solids_item = QTreeWidgetItem(file_item, ["Solids"])
            solids_item.setFlags(solids_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            for sn in solid_nodes:
                si = self._create_tree_item(sn)
                si.setFlags(si.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
                solids_item.addChild(si)
        world_node = next(
            (c for c in file_node.children if c.node_type == GdmlNodeType.WORLD_NODE),
            None)
        if world_node:
            world_item = QTreeWidgetItem(file_item, ["World"])
            world_item.setFlags(world_item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
            self._build_world_tree(world_item, world_node)

    @staticmethod
    def _collect_solid_nodes(node: GdmlNode, result: List[GdmlNode]):
        if node.node_type == GdmlNodeType.SOLID_DEF and node not in result:
            result.append(node)
        for child in node.children:
            ProjectTreeWidget._collect_solid_nodes(child, result)

    def _build_world_tree(self, parent_item: QTreeWidgetItem, node: GdmlNode):
        if node.node_type in (GdmlNodeType.SOLID_DEF, GdmlNodeType.PHYVOL_NODE):
            for child in node.children:
                self._build_world_tree(parent_item, child)
            return
        child_item = self._create_tree_item(node)
        parent_item.addChild(child_item)
        for child in node.children:
            self._build_world_tree(child_item, child)

    def _create_tree_item(self, node: GdmlNode) -> QTreeWidgetItem:
        item = QTreeWidgetItem()
        display_name = getattr(node, "_display_name", None) or node.name or "(unnamed)"
        if node.node_type == GdmlNodeType.SOLID_DEF and node.gdml_tag and node.gdml_tag != "box":
            display_name += f" [{node.gdml_tag}]"
        item.setText(0, display_name)
        item.setData(0, TREE_ITEM_DATA_ROLE, node.entry_id)
        item.setData(0, TREE_NODE_TYPE_ROLE, node.node_type.value)
        item.setData(0, Qt.ItemDataRole.ToolTipRole, self._get_tooltip(node))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
        item.setCheckState(0, Qt.CheckState.Checked if node.visible else Qt.CheckState.Unchecked)
        cb = getattr(self, "_tree_progress_cb", None)
        if cb is not None:
            self._tree_progress_done += 1
            if self._tree_progress_done % 128 == 0:
                cb(self._tree_progress_done)
        return item

    def _get_tooltip(self, node: GdmlNode) -> str:
        lines = [f"Name: {node.name}",
                 f"Type: {node.node_type.name}",
                 f"GDML Tag: {node.gdml_tag}",
                 f"Material: {node.material_name}"]
        if node.solid_params:
            parts = [f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}"
                     for k, v in node.solid_params.items()
                     if isinstance(v, (int, float, str))]
            if parts:
                lines.append(f"Params: {', '.join(parts)}")
        if node.placement:
            p = node.placement
            lines.append(f"Position: ({p.x:.2f}, {p.y:.2f}, {p.z:.2f})")
        return "\n".join(lines)

    # ==================== Tasks ====================

    def add_task(self, task_name: str, analysis_type: str = "default",
                 n_threads: int = 0) -> QTreeWidgetItem:
        """Create a task node plus its children
        (Calculate/Particle/Physics/Analysis/Results)."""
        existing = self._find_task_item(task_name)
        if existing is not None:
            return existing
        item = QTreeWidgetItem(self._tasks_root, [task_name])
        item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsUserCheckable)
        item.setData(0, Qt.ItemDataRole.UserRole, task_name)
        item.setData(0, TASK_CTX_ROLE, CTX_TASK)
        item.setExpanded(True)

        calc = QTreeWidgetItem(item, ["Calculate Setting"])
        calc.setData(0, TASK_ACTION_ROLE, f"calculate:{task_name}")
        if n_threads:
            calc.setText(0, f"Calculate Setting ({n_threads} threads)")

        particle = QTreeWidgetItem(item, ["Particle Setting"])
        particle.setData(0, TASK_ACTION_ROLE, f"particle:{task_name}")

        physics = QTreeWidgetItem(item, ["Physics Process"])
        physics.setData(0, TASK_ACTION_ROLE, f"physics:{task_name}")

        analysis = QTreeWidgetItem(item, ["Analysis"])
        analysis.setExpanded(True)
        for kind in ("real world", "probe", "voxel"):
            ai = QTreeWidgetItem(analysis, [kind])
            ai.setData(0, TASK_ACTION_ROLE, f"analysis:{task_name}:{kind}")
            ai.setData(0, TASK_CTX_ROLE, CTX_ANALYSIS)

        results = QTreeWidgetItem(item, ["Results"])
        results.setData(0, TASK_ACTION_ROLE, f"results:{task_name}")
        results.setData(0, TASK_CTX_ROLE, CTX_RESULT)
        return item

    def update_task_threads(self, task_name: str, n_threads: int):
        item = self._find_task_item(task_name)
        if item is None:
            return
        calc = self._find_child_by_data(
            item, TASK_ACTION_ROLE, f"calculate:{task_name}")
        if calc:
            calc.setText(0, f"Calculate Setting ({n_threads} threads)")

    def set_task_status(self, task_name: str, status: str):
        """Update the status prefix of a task node (running / completed /
        failed ...)."""
        item = self._find_task_item(task_name)
        if item is None:
            return
        base = item.data(0, Qt.ItemDataRole.UserRole) or task_name
        emoji = TASK_STATUS_EMOJI.get(status, "")
        item.setText(0, f"{emoji} {base}".strip())

    def add_task_result(self, task_name: str, label: str):
        """Attach a computation result under the task's Results child node.
        Re-running a task refreshes an existing item with the same label
        instead of stacking duplicates."""
        item = self._find_task_item(task_name)
        if item is None:
            return
        results = self._find_child(item, "Results")
        if results is None:
            return
        for i in range(results.childCount()):
            if results.child(i).text(0) == label:
                results.removeChild(results.child(i))
                break
        res_item = QTreeWidgetItem(results, [label])
        res_item.setData(0, TASK_ACTION_ROLE, f"result:{task_name}:{label}")
        res_item.setData(0, TASK_CTX_ROLE, CTX_RESULT)
        results.setExpanded(True)
        item.setExpanded(True)

    def remove_task_result(self, task_name: str, label: str) -> None:
        """Remove a single (leaf) result child by label, silently if absent.
        Only plain leaf items are removed, never a result group."""
        item = self._find_task_item(task_name)
        if item is None:
            return
        results = self._find_child(item, "Results")
        if results is None:
            return
        for i in range(results.childCount()):
            child = results.child(i)
            if child.text(0) == label and child.childCount() == 0:
                results.removeChild(child)
                return

    def clear_task_results(self, task_name: str) -> None:
        """Remove every result entry (leaves and groups) under the task's
        Results child. Used to rebuild the Results subtree deterministically
        from the run directory on re-run / project load."""
        item = self._find_task_item(task_name)
        if item is None:
            return
        results = self._find_child(item, "Results")
        if results is None:
            return
        while results.childCount():
            results.removeChild(results.child(0))

    def add_task_result_group(self, task_name: str, group_label: str,
                              children) -> None:
        """Attach a grouped result (one parent node + child nodes) under the
        task's Results child. children is a list of (text, action). A group
        with the same label is refreshed instead of stacked (matches
        add_task_result)."""
        item = self._find_task_item(task_name)
        if item is None:
            return
        results = self._find_child(item, "Results")
        if results is None:
            return
        for i in range(results.childCount()):
            if results.child(i).text(0) == group_label:
                results.removeChild(results.child(i))
                break
        group = QTreeWidgetItem(results, [group_label])
        group.setData(0, TASK_CTX_ROLE, CTX_RESULT)
        for text, action in children:
            child = QTreeWidgetItem(group, [text])
            child.setData(0, TASK_ACTION_ROLE, action)
            child.setData(0, TASK_CTX_ROLE, CTX_RESULT)
        group.setExpanded(True)
        results.setExpanded(True)
        item.setExpanded(True)

    def add_task_result_tree(self, task_name: str, root_label: str,
                             children) -> None:
        """Attach a NESTED result tree under the task's Results child: a root
        node (root_label) whose children can recursively be groups or leaves.
        A node is ('group', text, children) or ('leaf', text, action) -
        leaves carry the action payload, groups only the right-click context
        role. A tree with the same root label is refreshed instead of
        stacked, exactly like add_task_result_group."""
        item = self._find_task_item(task_name)
        if item is None:
            return
        results = self._find_child(item, "Results")
        if results is None:
            return
        for i in range(results.childCount()):
            if results.child(i).text(0) == root_label:
                results.removeChild(results.child(i))
                break
        root = QTreeWidgetItem(results, [root_label])
        root.setData(0, TASK_CTX_ROLE, CTX_RESULT)

        def _fill(parent, nodes):
            for node in nodes:
                kind, text = node[0], node[1]
                child = QTreeWidgetItem(parent, [text])
                child.setData(0, TASK_CTX_ROLE, CTX_RESULT)
                if kind == "group":
                    child.setExpanded(True)
                    _fill(child, node[2])
                else:
                    child.setData(0, TASK_ACTION_ROLE, node[2])

        _fill(root, children)
        root.setExpanded(True)
        results.setExpanded(True)
        item.setExpanded(True)

    def remove_task(self, task_name: str) -> bool:
        item = self._find_task_item(task_name)
        if item is None:
            return False
        self._tasks_root.removeChild(item)
        return True

    def rename_task(self, old_name: str, new_name: str) -> bool:
        item = self._find_task_item(old_name)
        if item is None:
            return False
        base = item.data(0, Qt.ItemDataRole.UserRole) or old_name
        item.setData(0, Qt.ItemDataRole.UserRole, new_name)
        emoji = "" 
        # Keep the status prefix: extract the already shown status emoji from
        # the current text
        cur_text = item.text(0)
        for em, _st in TASK_STATUS_EMOJI.items():
            if em and cur_text.startswith(em):
                item.setText(0, f"{em} {new_name}".strip())
                break
        else:
            item.setText(0, new_name)
        # Update the task name inside each child node's payload
        for i in range(item.childCount()):
            child = item.child(i)
            act = child.data(0, TASK_ACTION_ROLE) or ""
            if act:
                parts = act.split(":")
                if len(parts) >= 2 and parts[1] == old_name:
                    parts[1] = new_name
                    child.setData(0, TASK_ACTION_ROLE, ":".join(parts))
        return True

    def set_analysis_configured(self, task_name: str, kind: str,
                                configured: bool):
        """Mark whether an analysis child (real world / probe / voxel) is
        configured."""
        item = self._find_task_item(task_name)
        if item is None:
            return
        analysis = self._find_child(item, "Analysis")
        if analysis is None:
            return
        for i in range(analysis.childCount()):
            ai = analysis.child(i)
            if ai.text(0) == kind:
                fg = QColor("#2e7d32") if configured else QColor("#888888")
                ai.setForeground(0, fg)
                break

    def set_particle_configured(self, task_name: str, configured: bool):
        """Mark the task's "Particle Setting" child as configured (green)."""
        item = self._find_task_item(task_name)
        if item is None:
            return
        for i in range(item.childCount()):
            child = item.child(i)
            act = child.data(0, TASK_ACTION_ROLE) or ""
            if act.startswith("particle:"):
                fg = QColor("#2e7d32") if configured else QColor("#888888")
                child.setForeground(0, fg)
                break

    def set_physics_configured(self, task_name: str, configured: bool):
        """Mark the task's "Physics Process" child as configured (green)."""
        item = self._find_task_item(task_name)
        if item is None:
            return
        for i in range(item.childCount()):
            child = item.child(i)
            act = child.data(0, TASK_ACTION_ROLE) or ""
            if act.startswith("physics:"):
                fg = QColor("#2e7d32") if configured else QColor("#888888")
                child.setForeground(0, fg)
                break

    def clear_tasks(self):
        self._tasks_root.takeChildren()

    # ==================== Helpers ====================

    def _find_task_item(self, task_name: str) -> Optional[QTreeWidgetItem]:
        """Find a task node by its base name (the original name stored in
        UserRole)."""
        for i in range(self._tasks_root.childCount()):
            item = self._tasks_root.child(i)
            if item.data(0, Qt.ItemDataRole.UserRole) == task_name:
                return item
        return None

    @staticmethod
    def _find_child(parent: QTreeWidgetItem, text: str):
        for i in range(parent.childCount()):
            if parent.child(i).text(0) == text:
                return parent.child(i)
        return None

    @staticmethod
    def _find_child_by_data(parent: QTreeWidgetItem, role: int, value):
        for i in range(parent.childCount()):
            if parent.child(i).data(0, role) == value:
                return parent.child(i)
        return None

    def select_item_by_entry_id(self, entry_id: str):
        item = self._find_item_by_entry_id(self._tree.invisibleRootItem(), entry_id)
        if item:
            self._tree.setCurrentItem(item)
            p = item.parent()
            while p:
                p.setExpanded(True)
                p = p.parent()

    def _find_item_by_entry_id(self, parent: QTreeWidgetItem, entry_id: str) -> Optional[QTreeWidgetItem]:
        for i in range(parent.childCount()):
            child = parent.child(i)
            if child.data(0, TREE_ITEM_DATA_ROLE) == entry_id:
                return child
            result = self._find_item_by_entry_id(child, entry_id)
            if result:
                return result
        return None

    # ==================== Signal handlers ====================

    def _on_item_clicked(self, item: QTreeWidgetItem, column: int):
        """Single click: only GDML geometry nodes trigger selection sync;
        task nodes have no effect (they open on double click)."""
        if item is self._geometry_root or item is self._tasks_root:
            return
        if item.data(0, TASK_ACTION_ROLE):
            return  # task nodes: single click has no effect
        entry_id = item.data(0, TREE_ITEM_DATA_ROLE)
        if entry_id:
            self.node_selected.emit(entry_id)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        """Double click: task nodes open the matching config dialog / result
        viewer."""
        action = item.data(0, TASK_ACTION_ROLE)
        if action:
            self.task_action.emit(action)
            return
        # Double-clicking a GDML node also selects it (for quick locating)
        entry_id = item.data(0, TREE_ITEM_DATA_ROLE)
        if entry_id:
            self.node_selected.emit(entry_id)

    def _on_context_menu(self, pos):
        """Right-click menu: Tasks root -> new task; task -> rename/duplicate/
        delete; analysis -> configure; result -> view."""
        item = self._tree.itemAt(pos)
        if item is None:
            return
        ctx = item.data(0, TASK_CTX_ROLE)
        menu = QMenu(self)

        if ctx == CTX_TASKS:
            menu.addAction("➕ Add Task",
                           lambda: self.task_context.emit("add_task", ""))
        elif ctx == CTX_TASK:
            task_name = item.data(0, Qt.ItemDataRole.UserRole) or item.text(0)
            menu.addAction("✏️ Rename Task",
                           lambda: self.task_context.emit("rename_task", task_name))
            menu.addAction("📋 Duplicate Task",
                           lambda: self.task_context.emit("duplicate_task", task_name))
            menu.addAction("❌ Delete Task",
                           lambda: self.task_context.emit("delete_task", task_name))
        elif ctx == CTX_ANALYSIS:
            action = item.data(0, TASK_ACTION_ROLE) or ""
            menu.addAction("⚙️ Configure...",
                           lambda: self.task_context.emit("configure_analysis", action))
        elif ctx == CTX_RESULT:
            action = item.data(0, TASK_ACTION_ROLE) or ""
            if action.startswith("result:"):
                menu.addAction("👁 View Result",
                               lambda: self.task_context.emit("view_result", action))

        if menu.actions():
            menu.exec(self._tree.viewport().mapToGlobal(pos))

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if column != 0 or item is self._geometry_root:
            return
        if item.data(0, TREE_ITEM_DATA_ROLE) is None:
            return
        state = item.checkState(0)
        if state == Qt.CheckState.PartiallyChecked:
            return
        if item.childCount() > 0:
            self._tree.blockSignals(True)
            self._cascade_check_state(item, state)
            self._tree.blockSignals(False)
        self._emit_visibility_for_leaves(item, state)

    def _cascade_check_state(self, parent_item: QTreeWidgetItem, state: Qt.CheckState):
        for i in range(parent_item.childCount()):
            child = parent_item.child(i)
            child.setCheckState(0, state)
            self._cascade_check_state(child, state)

    def _emit_visibility_for_leaves(self, item: QTreeWidgetItem, state: Qt.CheckState):
        eid = item.data(0, TREE_ITEM_DATA_ROLE)
        nt = item.data(0, TREE_NODE_TYPE_ROLE)
        if eid and nt in (6, 9):  # VOLUME_NODE / WORLD_NODE
            self.visibility_changed.emit(eid, state == Qt.CheckState.Checked)
        for i in range(item.childCount()):
            self._emit_visibility_for_leaves(item.child(i), state)
