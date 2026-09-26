"""
服务层模块

提供屏幕捕获、音频录制、桌面监控、主动对话等服务。
"""

from .desktop_monitor import DesktopMonitorService, DesktopState
from .proactive_dialog import (
    ProactiveDialogService,
    ProactiveDialogConfig,
    TriggerEvent,
    TriggerType,
)
from .perception_engine import (
    PerceptionEngine,
    PerceptionConfig,
    PerceptionEvent,
    EventType,
    EventSeverity,
)

__all__ = [
    "DesktopMonitorService",
    "DesktopState",
    "ProactiveDialogService",
    "ProactiveDialogConfig",
    "TriggerEvent",
    "TriggerType",
    "PerceptionEngine",
    "PerceptionConfig",
    "PerceptionEvent",
    "EventType",
    "EventSeverity",
]