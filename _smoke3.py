"""Temporary smoke test 3: new menu/tree structure + even CPU split + task
status linkage + project roundtrip + geometry replacement."""
import sys, os, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ["QT_LOGGING_RULES"] = "qt.qpa.windows.warning=false;qt.qpa.gl.warning=false"
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import QTimer
from app.main_window import MainWindow
from core.project_io import save_project, load_project
from ui.project_tree import TASK_ACTION_ROLE

app = QApplication(sys.argv)
w = MainWindow()
w.show()
print("DEFAULT_DARK:", w._dark_theme, "(expected False)")

gdml = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "solver", "rad4space", "axes.gdml")
w._replace_gdml(gdml)
print("GEOM_TREE_CHILDREN:", w._project_tree._geometry_root.childCount())

for _ in range(3):
    w._add_default_run_task()

tree = w._project_tree
print("TASKS_TREE:", tree._tasks_root.childCount())
first = tree._tasks_root.child(0)
print("TASK0_CHILDREN:", [first.child(i).text(0) for i in range(first.childCount())])
analysis = tree._find_child(first, "Analysis")
print("ANALYSIS_CHILDREN:", [analysis.child(i).text(0) for i in range(analysis.childCount())])

# Even CPU split (simulates the "Yes" branch of _on_run)
total = os.cpu_count() or 4
idle_tasks = [t for t in w._run_manager._tasks.values() if t.status == "idle"]
per = max(1, total // len(idle_tasks))
for t in idle_tasks:
    t.calculate.n_threads = per
    tree.update_task_threads(t.name, per)
calc_item = tree._find_child_by_data(first, TASK_ACTION_ROLE, f"calculate:{first.text(0)}")
print("THREADS_PER_TASK:", per, "| CALC_TEXT:", calc_item.text(0))

finished = []
w._run_manager.task_finished.connect(lambda n, s: finished.append((n, s)))
w._run_manager.start_all()

def check():
    print("FINISHED:", finished)
    print("TASK0_TEXT:", first.text(0))
    results = tree._find_child(first, "Results")
    print("RESULTS_CHILDREN:", [results.child(i).text(0) for i in range(results.childCount())])
    print("STATUS_BTN:", w._toolbar._status_btn.text(), "| state=", w._toolbar._status_state)

    # Project roundtrip
    tmp = os.path.join(tempfile.gettempdir(), "3drad_test.json")
    tasks_data = [{"name": t.name, "analysis_type": t.analysis_type,
                   "gdml_files": t.gdml_files,
                   "calculate": {"n_threads": t.calculate.n_threads}}
                  for t in w._run_manager._tasks.values()]
    save_project(tmp, gdml_paths=[gdml], tasks=tasks_data)
    gdml_paths2, tasks2 = load_project(tmp)
    print("ROUNDTRIP:", gdml_paths2 == [gdml], "| tasks:", len(tasks2))

    # Geometry replacement (internal, no dialog)
    w._run_manager.clear()
    tree.clear_tasks()
    w._replace_gdml(gdml)
    print("AFTER_REPLACE GEOM:", tree._geometry_root.childCount(),
          "| TASKS_TREE:", tree._tasks_root.childCount())
    app.quit()

QTimer.singleShot(6000, check)
app.exec()
print("SMOKE3_OK")
