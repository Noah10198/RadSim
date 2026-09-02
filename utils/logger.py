"""
AsyncLogger - Asynchronous Logging System

Based on cad2gdml's AsyncLogger design, provides system logging.
Implements singleton pattern with level-based logging to UI widgets.
"""

from typing import Optional
from enum import Enum
from PyQt6.QtCore import QObject, pyqtSignal, QDateTime


class LogLevel(Enum):
    """Log level enumeration"""
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3


class AsyncLogger(QObject):
    """Asynchronous Log Manager (Singleton)"""

    log_received = pyqtSignal(str, str)  # (log_type, message)

    _instance: Optional['AsyncLogger'] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        super().__init__()
        self._system_log_buffer: list = []
        self._system_log_widget = None

    def set_system_log_widget(self, text_edit):
        self._system_log_widget = text_edit
        for msg in self._system_log_buffer:
            if self._system_log_widget:
                self._system_log_widget.append(msg)
        self._system_log_buffer.clear()

    def log(self, message: str, level: LogLevel = LogLevel.INFO, log_type: str = "system"):
        timestamp = QDateTime.currentDateTime().toString("yyyy-MM-dd hh:mm:ss")
        level_str = level.name
        formatted = f"[{timestamp}] [{level_str}] {message}"
        if self._system_log_widget:
            self._system_log_widget.append(formatted)
        else:
            self._system_log_buffer.append(formatted)
        self.log_received.emit(log_type, formatted)

    def log_system(self, message: str, level: LogLevel = LogLevel.INFO):
        self.log(message, level, "system")
