"""
project_model - RadSim run task data model

Modeled on 1dRad's TaskData and trimmed for RadSim semantics:
  - a task = GDML geometry + analysis type (realworld / probe / voxel)
    + run status
  - when particle sources / physics processes / mesh parameters are
    introduced later, simply extend RunTask with new fields
"""

from dataclasses import dataclass, field


@dataclass
class CalculateSetting:
    """Calculation settings (thread count, etc.; real rad4space parameters
    to be added later)."""

    n_threads: int = 0        # 0 = unassigned; can be split evenly across CPU cores on Run
    n_events: int = 0         # reserved: number of events
    output_dir: str = ""      # reserved: output directory


@dataclass
class RunTask:
    """A single calculation task - the smallest unit that can be queued and
    executed concurrently."""

    name: str
    gdml_files: list[str] = field(default_factory=list)
    analysis_type: str = ""          # realworld / probe / voxel
    particle: dict = field(default_factory=dict)   # reserved: particle source configuration
    physics: dict = field(default_factory=dict)    # reserved: physics process configuration
    calculate: CalculateSetting = field(default_factory=CalculateSetting)

    # Snapshot of the analysis configuration (key = realworld / probe / voxel,
    # value structure is defined by the analysis dialogs)
    analysis_config: dict = field(default_factory=dict)

    # Run status (idle / queued / running / completed / failed / stopped)
    status: str = "idle"
    progress: int = 0
    run_time: str = ""

    # Absolute path of the solver console log (run.log) of the latest run.
    # Set by the run manager while a real solver process is active; never
    # persisted (project save uses an explicit field whitelist).
    run_log: str = ""
