"""
感知引擎 - 提供持续桌面感知和智能事件检测

基于VisionAnalyzer的结构化分析能力，实现持续监控、事件检测和主动交互决策。
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from enum import Enum

from astrbot import logger

from .vision_analyzer import VisionAnalyzer, SceneSnapshot


class EventType(Enum):
    """感知事件类型"""
    ERROR_APPEARED = "error_appeared"           # 错误出现
    ERROR_PERSISTED = "error_persisted"         # 错误持续
    PROLONGED_STUCK = "prolonged_stuck"         # 长时间卡住
    FOCUS_DRIFT = "focus_drift"                 # 注意力漂移
    IDLE_LONG = "idle_long"                     # 长时间空闲
    REPETITIVE_SWITCH = "repetitive_switch"     # 反复切换
    MEETING_START = "meeting_start"             # 会议开始
    WORK_OVERTIME = "work_overtime"             # 工作超时
    MEDIA_CONSUMPTION = "media_consumption"     # 媒体消费


class EventSeverity(Enum):
    """事件严重程度"""
    LOW = 1        # 低打扰（陪伴、记录）
    MEDIUM = 2     # 中打扰（询问、建议）
    HIGH = 3       # 高打扰（立即提醒）


@dataclass
class PerceptionEvent:
    """感知事件"""
    event_type: EventType
    severity: EventSeverity
    snapshot: SceneSnapshot
    timestamp: datetime = field(default_factory=datetime.now)
    context: Dict[str, Any] = field(default_factory=dict)
    message_hint: Optional[str] = None  # 主动交互提示
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "timestamp": self.timestamp.isoformat(),
            "context": self.context,
            "message_hint": self.message_hint,
            "snapshot": self.snapshot.to_dict(),
        }


@dataclass
class PerceptionConfig:
    """感知引擎配置"""
    enabled: bool = True
    analyze_interval: int = 30           # 分析间隔（秒）
    history_size: int = 20               # 历史快照保留数量
    min_interval_between_events: int = 60  # 事件最小间隔（秒）
    
    # 场景分析配置
    enable_error_detection: bool = True
    enable_focus_evaluation: bool = True
    enable_companion_mode: bool = True
    
    # 事件检测阈值
    error_persistence_threshold: int = 60   # 错误持续阈值（秒）
    stuck_threshold: int = 300              # 卡住阈值（秒）
    idle_threshold: int = 300               # 空闲阈值（秒）
    repetitive_switch_threshold: int = 3    # 反复切换阈值（次）
    repetitive_switch_window: int = 300     # 反复切换时间窗口（秒）
    work_overtime_threshold: int = 3600     # 工作超时阈值（秒）

    # 主动交互频率限制
    max_interactions_per_hour: int = 5      # 每小时最大主动交互次数


class SceneMemory:
    """
    场景记忆 - 管理历史快照的滑动窗口
    
    存储最近的SceneSnapshot历史，支持差分分析和事件检测。
    """
    
    def __init__(self, max_size: int = 20):
        """
        初始化场景记忆
        
        Args:
            max_size: 最大存储数量
        """
        self.max_size = max_size
        self.snapshots: List[SceneSnapshot] = []
        self._window_changes: List[datetime] = []  # 窗口变化时间记录
    
    def add_snapshot(self, snapshot: SceneSnapshot):
        """
        添加新的场景快照
        
        Args:
            snapshot: 新的场景快照
        """
        self.snapshots.append(snapshot)
        
        # 保持滑动窗口大小
        if len(self.snapshots) > self.max_size:
            self.snapshots = self.snapshots[-self.max_size:]
        
        # 记录窗口变化（如果检测到）
        if len(self.snapshots) >= 2:
            prev = self.snapshots[-2]
            curr = self.snapshots[-1]
            if prev.activity_type != curr.activity_type:
                self._window_changes.append(curr.timestamp)
                # 保持变化记录大小
                if len(self._window_changes) > 100:
                    self._window_changes = self._window_changes[-100:]
    
    def get_latest(self) -> Optional[SceneSnapshot]:
        """获取最新的快照"""
        return self.snapshots[-1] if self.snapshots else None
    
    def get_recent(self, seconds: int) -> List[SceneSnapshot]:
        """
        获取最近N秒内的快照
        
        Args:
            seconds: 时间范围（秒）
        
        Returns:
            快照列表
        """
        if not self.snapshots:
            return []
        
        cutoff_time = datetime.now() - timedelta(seconds=seconds)
        return [s for s in self.snapshots if s.timestamp >= cutoff_time]
    
    def get_error_snapshots(self, seconds: int = 300) -> List[SceneSnapshot]:
        """
        获取最近N秒内包含错误的快照
        
        Args:
            seconds: 时间范围（秒）
        
        Returns:
            包含错误的快照列表
        """
        recent = self.get_recent(seconds)
        return [s for s in recent if s.has_error_ui]
    
    def get_focus_snapshots(self, seconds: int = 300) -> List[SceneSnapshot]:
        """
        获取最近N秒内的专注快照
        
        Args:
            seconds: 时间范围（秒）
        
        Returns:
            专注快照列表
        """
        recent = self.get_recent(seconds)
        return [s for s in recent if s.is_work_focus]
    
    def get_idle_snapshots(self, seconds: int = 300) -> List[SceneSnapshot]:
        """
        获取最近N秒内的空闲快照
        
        Args:
            seconds: 时间范围（秒）
        
        Returns:
            空闲快照列表
        """
        recent = self.get_recent(seconds)
        return [s for s in recent if s.is_idle]
    
    def count_window_changes(self, seconds: int = 300) -> int:
        """
        统计最近N秒内的窗口变化次数
        
        Args:
            seconds: 时间范围（秒）
        
        Returns:
            窗口变化次数
        """
        cutoff_time = datetime.now() - timedelta(seconds=seconds)
        return sum(1 for t in self._window_changes if t >= cutoff_time)
    
    def get_activity_pattern(self, seconds: int = 300) -> Dict[str, int]:
        """
        获取最近N秒内的活动模式统计
        
        Args:
            seconds: 时间范围（秒）
        
        Returns:
            活动类型计数
        """
        recent = self.get_recent(seconds)
        pattern = {}
        for snapshot in recent:
            activity = snapshot.activity_type
            pattern[activity] = pattern.get(activity, 0) + 1
        return pattern
    
    def clear(self):
        """清空记忆"""
        self.snapshots.clear()
        self._window_changes.clear()


class EventDetector:
    """
    事件检测器 - 从场景记忆中检测语义事件
    
    基于历史快照的差分分析，检测各种用户状态事件。
    """
    
    def __init__(self, memory: SceneMemory, config: PerceptionConfig):
        """
        初始化事件检测器
        
        Args:
            memory: 场景记忆
            config: 感知配置
        """
        self.memory = memory
        self.config = config
        
        # 事件冷却时间跟踪
        self._last_event_times: Dict[EventType, datetime] = {}
    
    def _is_event_cooling_down(self, event_type: EventType) -> bool:
        """检查事件是否在冷却期"""
        last_time = self._last_event_times.get(event_type)
        if not last_time:
            return False
        
        elapsed = (datetime.now() - last_time).total_seconds()
        return elapsed < self.config.min_interval_between_events
    
    def _record_event_time(self, event_type: EventType):
        """记录事件发生时间"""
        self._last_event_times[event_type] = datetime.now()
    
    def detect_events(self) -> List[PerceptionEvent]:
        """
        检测所有可能的事件
        
        Returns:
            检测到的事件列表
        """
        events = []
        
        # 按优先级检测事件（高严重度优先）
        detection_methods = [
            self._detect_error_events,
            self._detect_stuck_events,
            self._detect_focus_drift,
            self._detect_idle_events,
            self._detect_repetitive_switch,
            self._detect_work_overtime,
        ]
        
        for detect_func in detection_methods:
            try:
                new_events = detect_func()
                events.extend(new_events)
            except Exception as e:
                logger.error(f"事件检测失败: {e}")
        
        return events
    
    def _detect_error_events(self) -> List[PerceptionEvent]:
        """检测错误相关事件"""
        events = []
        
        if not self.config.enable_error_detection:
            return events
        
        # 检测新错误出现
        if not self._is_event_cooling_down(EventType.ERROR_APPEARED):
            latest = self.memory.get_latest()
            if latest and latest.has_error_ui:
                # 检查之前是否有错误
                recent_errors = self.memory.get_error_snapshots(seconds=60)
                if len(recent_errors) <= 1:  # 只有当前这个错误
                    event = PerceptionEvent(
                        event_type=EventType.ERROR_APPEARED,
                        severity=EventSeverity.HIGH,
                        snapshot=latest,
                        context={
                            "error_text": latest.error_text,
                            "first_detection": True,
                        },
                        message_hint=f"检测到错误：{latest.error_text or '未知错误'}，需要我帮忙吗？"
                    )
                    events.append(event)
                    self._record_event_time(EventType.ERROR_APPEARED)
        
        # 检测错误持续
        if not self._is_event_cooling_down(EventType.ERROR_PERSISTED):
            error_snapshots = self.memory.get_error_snapshots(
                seconds=self.config.error_persistence_threshold
            )
            if len(error_snapshots) >= 2:
                # 检查错误是否相同
                latest = error_snapshots[-1]
                prev = error_snapshots[-2]
                
                if (latest.error_text and prev.error_text and 
                    latest.error_text == prev.error_text):
                    # 计算持续时间
                    duration = (latest.timestamp - error_snapshots[0].timestamp).total_seconds()
                    
                    event = PerceptionEvent(
                        event_type=EventType.ERROR_PERSISTED,
                        severity=EventSeverity.MEDIUM,
                        snapshot=latest,
                        context={
                            "error_text": latest.error_text,
                            "duration_seconds": duration,
                            "occurrence_count": len(error_snapshots),
                        },
                        message_hint=f"错误已持续{int(duration)}秒，是否需要进一步帮助？"
                    )
                    events.append(event)
                    self._record_event_time(EventType.ERROR_PERSISTED)
        
        return events
    
    def _detect_stuck_events(self) -> List[PerceptionEvent]:
        """检测卡住事件"""
        events = []
        
        if self._is_event_cooling_down(EventType.PROLONGED_STUCK):
            return events
        
        # 检查是否长时间在同一活动
        focus_snapshots = self.memory.get_focus_snapshots(seconds=self.config.stuck_threshold)
        if len(focus_snapshots) >= 3:
            # 检查活动类型是否相同
            activities = [s.activity_type for s in focus_snapshots]
            if len(set(activities)) == 1:  # 所有活动类型相同
                latest = focus_snapshots[-1]
                duration = (latest.timestamp - focus_snapshots[0].timestamp).total_seconds()
                
                # 检查注意力水平是否下降
                attention_levels = [s.attention_level for s in focus_snapshots]
                avg_attention = sum(attention_levels) / len(attention_levels)
                
                if avg_attention < 0.6:  # 注意力水平较低
                    event = PerceptionEvent(
                        event_type=EventType.PROLONGED_STUCK,
                        severity=EventSeverity.LOW,
                        snapshot=latest,
                        context={
                            "activity_type": latest.activity_type,
                            "duration_seconds": duration,
                            "average_attention": avg_attention,
                        },
                        message_hint=f"你已经在这个任务上花了{int(duration/60)}分钟，需要休息一下吗？"
                    )
                    events.append(event)
                    self._record_event_time(EventType.PROLONGED_STUCK)
        
        return events
    
    def _detect_focus_drift(self) -> List[PerceptionEvent]:
        """检测注意力漂移"""
        events = []
        
        if self._is_event_cooling_down(EventType.FOCUS_DRIFT):
            return events
        
        # 检查注意力水平变化
        recent = self.memory.get_recent(seconds=300)
        if len(recent) >= 3:
            # 计算最近3个快照的注意力水平
            recent_attention = [s.attention_level for s in recent[-3:]]
            earlier_attention = [s.attention_level for s in recent[:-3]] if len(recent) > 3 else recent_attention
            
            if earlier_attention:
                recent_avg = sum(recent_attention) / len(recent_attention)
                earlier_avg = sum(earlier_attention) / len(earlier_attention)
                
                # 注意力下降超过0.3
                if earlier_avg - recent_avg > 0.3:
                    latest = recent[-1]
                    event = PerceptionEvent(
                        event_type=EventType.FOCUS_DRIFT,
                        severity=EventSeverity.LOW,
                        snapshot=latest,
                        context={
                            "attention_drop": earlier_avg - recent_avg,
                            "current_attention": recent_avg,
                            "previous_attention": earlier_avg,
                        },
                        message_hint="注意力有些分散了，要不要换个任务或者休息一下？"
                    )
                    events.append(event)
                    self._record_event_time(EventType.FOCUS_DRIFT)
        
        return events
    
    def _detect_idle_events(self) -> List[PerceptionEvent]:
        """检测空闲事件"""
        events = []
        
        if self._is_event_cooling_down(EventType.IDLE_LONG):
            return events
        
        idle_snapshots = self.memory.get_idle_snapshots(seconds=self.config.idle_threshold)
        if len(idle_snapshots) >= 2:
            latest = idle_snapshots[-1]
            duration = (latest.timestamp - idle_snapshots[0].timestamp).total_seconds()
            
            if duration >= self.config.idle_threshold:
                event = PerceptionEvent(
                    event_type=EventType.IDLE_LONG,
                    severity=EventSeverity.LOW,
                    snapshot=latest,
                    context={
                        "idle_duration": duration,
                    },
                    message_hint=f"你已经休息了{int(duration/60)}分钟，需要我帮你做点什么吗？"
                )
                events.append(event)
                self._record_event_time(EventType.IDLE_LONG)
        
        return events
    
    def _detect_repetitive_switch(self) -> List[PerceptionEvent]:
        """检测反复切换事件"""
        events = []
        
        if self._is_event_cooling_down(EventType.REPETITIVE_SWITCH):
            return events
        
        # 统计窗口切换次数
        switch_count = self.memory.count_window_changes(
            seconds=self.config.repetitive_switch_window
        )
        
        if switch_count >= self.config.repetitive_switch_threshold:
            latest = self.memory.get_latest()
            if latest:
                event = PerceptionEvent(
                    event_type=EventType.REPETITIVE_SWITCH,
                    severity=EventSeverity.MEDIUM,
                    snapshot=latest,
                    context={
                        "switch_count": switch_count,
                        "window_seconds": self.config.repetitive_switch_window,
                    },
                    message_hint="你在多个应用间切换频繁，是在找什么资料吗？我可以帮你搜索。"
                )
                events.append(event)
                self._record_event_time(EventType.REPETITIVE_SWITCH)
        
        return events
    
    def _detect_work_overtime(self) -> List[PerceptionEvent]:
        """检测工作超时事件"""
        events = []
        
        if self._is_event_cooling_down(EventType.WORK_OVERTIME):
            return events
        
        focus_snapshots = self.memory.get_focus_snapshots(seconds=self.config.work_overtime_threshold)
        if len(focus_snapshots) >= 3:
            latest = focus_snapshots[-1]
            duration = (latest.timestamp - focus_snapshots[0].timestamp).total_seconds()
            
            if duration >= self.config.work_overtime_threshold:
                event = PerceptionEvent(
                    event_type=EventType.WORK_OVERTIME,
                    severity=EventSeverity.LOW,
                    snapshot=latest,
                    context={
                        "work_duration": duration,
                        "activity_type": latest.activity_type,
                    },
                    message_hint=f"你已经连续工作了{int(duration/60)}分钟，记得休息一下眼睛和身体哦。"
                )
                events.append(event)
                self._record_event_time(EventType.WORK_OVERTIME)
        
        return events


class ProactiveReasoner:
    """
    主动交互决策器 - 根据事件决定如何主动交互
    
    基于事件类型、严重程度和用户状态，决定是否主动交互以及如何表达。
    """
    
    def __init__(self, config: PerceptionConfig):
        """
        初始化主动交互决策器
        
        Args:
            config: 感知配置
        """
        self.config = config
        
        # 交互历史记录
        self._interaction_history: List[datetime] = []
        self._max_interactions_per_hour = config.max_interactions_per_hour  # 每小时最大交互次数
    
    def should_interact(self, event: PerceptionEvent) -> bool:
        """
        判断是否应该进行主动交互
        
        Args:
            event: 感知事件
        
        Returns:
            是否应该交互
        """
        # 检查交互频率限制
        if not self._check_interaction_frequency():
            logger.info("交互频率超限（每小时上限），跳过本次交互")
            return False
        
        # 根据严重程度决定
        if event.severity == EventSeverity.HIGH:
            return True
        elif event.severity == EventSeverity.MEDIUM:
            # 中等严重度，50%概率
            return random.random() < 0.5
        else:  # LOW
            # 低严重度，20%概率
            return random.random() < 0.2
    
    def _check_interaction_frequency(self) -> bool:
        """检查交互频率是否超限"""
        now = datetime.now()
        hour_ago = now - timedelta(hours=1)
        
        # 清理过期记录
        self._interaction_history = [
            t for t in self._interaction_history if t >= hour_ago
        ]
        
        # 检查是否超限
        return len(self._interaction_history) < self._max_interactions_per_hour
    
    def record_interaction(self):
        """记录一次交互"""
        self._interaction_history.append(datetime.now())
    
    def format_interaction_message(self, event: PerceptionEvent) -> str:
        """
        格式化交互消息
        
        Args:
            event: 感知事件
        
        Returns:
            格式化的消息
        """
        if event.message_hint:
            return event.message_hint
        
        # 根据事件类型生成默认消息
        messages = {
            EventType.ERROR_APPEARED: "检测到屏幕上有错误，需要帮忙吗？",
            EventType.ERROR_PERSISTED: "错误还在，需要进一步协助吗？",
            EventType.PROLONGED_STUCK: "你看起来在这个任务上卡住了，要不要换个思路？",
            EventType.FOCUS_DRIFT: "注意力有些分散了，要不要休息一下？",
            EventType.IDLE_LONG: "你已经休息了一会儿，需要我帮忙吗？",
            EventType.REPETITIVE_SWITCH: "你在多个应用间切换，是在找什么吗？",
            EventType.WORK_OVERTIME: "工作时间有点长了，记得休息哦。",
            EventType.MEDIA_CONSUMPTION: "检测到你在观看视频，享受娱乐时光吧！",
        }
        
        return messages.get(event.event_type, "我在这里陪着你呢。")
    
    def get_interaction_style(self, event: PerceptionEvent) -> str:
        """
        获取交互风格
        
        Args:
            event: 感知事件
        
        Returns:
            交互风格描述
        """
        if event.severity == EventSeverity.HIGH:
            return "urgent"      # 紧急
        elif event.severity == EventSeverity.MEDIUM:
            return "suggestive"  # 建议性
        else:
            return "gentle"      # 温和


class PerceptionEngine:
    """
    感知引擎 - 核心控制器
    
    协调SceneMemory、EventDetector和ProactiveReasoner，提供完整的桌面感知能力。
    """
    
    def __init__(
        self,
        vision_analyzer: VisionAnalyzer,
        config: Optional[PerceptionConfig] = None,
    ):
        """
        初始化感知引擎
        
        Args:
            vision_analyzer: 视觉分析器
            config: 感知配置
        """
        self.vision_analyzer = vision_analyzer
        self.config = config or PerceptionConfig()
        
        # 初始化组件
        self.memory = SceneMemory(max_size=self.config.history_size)
        self.event_detector = EventDetector(self.memory, self.config)
        self.reasoner = ProactiveReasoner(self.config)
        
        # 事件回调
        self.on_perception_event: Optional[Callable[[PerceptionEvent], Any]] = None
        
        # 运行状态
        self._is_running = False
        self._monitor_task: Optional[asyncio.Task] = None
        self._last_analysis_time: Optional[datetime] = None
        
        # 外部状态引用（由main.py设置）
        self._desktop_monitor = None
        
        logger.info("感知引擎初始化完成")
    
    def set_desktop_monitor(self, desktop_monitor):
        """设置桌面监控服务引用"""
        self._desktop_monitor = desktop_monitor
    
    async def start(self):
        """启动感知引擎"""
        if self._is_running:
            return
        
        self._is_running = True
        
        # 启动监控任务
        if self.config.enabled:
            self._monitor_task = asyncio.create_task(self._monitoring_loop())
            logger.info(f"感知引擎已启动，分析间隔: {self.config.analyze_interval}秒")
        else:
            logger.info("感知引擎已禁用")
    
    async def stop(self):
        """停止感知引擎"""
        self._is_running = False
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None
        
        logger.info("感知引擎已停止")
    
    async def _monitoring_loop(self):
        """监控循环"""
        while self._is_running:
            try:
                # 等待分析间隔
                await asyncio.sleep(self.config.analyze_interval)
                
                if not self._is_running:
                    break
                
                # 获取最新截图
                await self._analyze_current_screen()
                
                # 检测事件
                events = self.event_detector.detect_events()
                
                # 处理事件
                for event in events:
                    await self._handle_event(event)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监控循环错误: {e}")
                await asyncio.sleep(5)
    
    async def _analyze_current_screen(self):
        """分析当前屏幕"""
        if not self._desktop_monitor:
            logger.debug("桌面监控服务未设置，跳过分析")
            return
        
        # 获取最新状态
        state = self._desktop_monitor.get_last_state()
        if not state or not state.screenshot_path:
            logger.debug("没有可用的截图，跳过分析")
            return
        
        # 检查是否需要分析（避免频繁分析）
        now = datetime.now()
        if self._last_analysis_time:
            elapsed = (now - self._last_analysis_time).total_seconds()
            if elapsed < self.config.analyze_interval:
                return
        
        try:
            # 根据当前状态选择分析场景
            scene_type = self._determine_scene_type(state)
            
            # 执行结构化分析
            snapshot, result = await self.vision_analyzer.structured_analyze(
                image_path=state.screenshot_path,
                scene_type=scene_type,
            )
            
            if result.success:
                # 添加到记忆
                self.memory.add_snapshot(snapshot)
                self._last_analysis_time = now
                
                logger.debug(f"屏幕分析完成: activity={snapshot.activity_type}, "
                           f"error={snapshot.has_error_ui}, attention={snapshot.attention_level:.2f}")
            else:
                logger.warning(f"屏幕分析失败: {result.error_message}")
                
        except Exception as e:
            logger.error(f"分析当前屏幕时出错: {e}")
    
    def _determine_scene_type(self, state) -> str:
        """
        根据当前状态确定分析场景类型
        
        Args:
            state: 桌面状态
        
        Returns:
            场景类型
        """
        # 如果配置了错误检测，优先使用
        if self.config.enable_error_detection:
            # 检查是否有错误迹象（简单的规则判断）
            if state.window_title and "error" in state.window_title.lower():
                return "error_detect"
        
        # 如果配置了专注评估
        if self.config.enable_focus_evaluation:
            # 在工作时间（9-18点）使用专注评估
            hour = datetime.now().hour
            if 9 <= hour <= 18:
                return "focus_eval"
        
        # 默认使用陪伴模式
        if self.config.enable_companion_mode:
            return "companion"
        
        # 回退到默认分析
        return "companion"
    
    async def _handle_event(self, event: PerceptionEvent):
        """
        处理感知事件
        
        Args:
            event: 感知事件
        """
        logger.info(f"处理感知事件: type={event.event_type.value}, "
                   f"severity={event.severity.value}, message={event.message_hint}")
        
        # 检查是否应该交互
        if not self.reasoner.should_interact(event):
            logger.info(f"决定不进行交互（概率/频率限制）: type={event.event_type.value}")
            return
        
        # 记录交互
        self.reasoner.record_interaction()
        
        # 触发回调
        if self.on_perception_event:
            try:
                result = self.on_perception_event(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"感知事件回调执行失败: {e}")
    
    async def analyze_on_demand(self, scene_type: str = "companion") -> Optional[SceneSnapshot]:
        """
        按需分析当前屏幕
        
        Args:
            scene_type: 场景类型
        
        Returns:
            分析结果快照
        """
        if not self._desktop_monitor:
            return None
        
        state = self._desktop_monitor.get_last_state()
        if not state or not state.screenshot_path:
            return None
        
        try:
            snapshot, result = await self.vision_analyzer.structured_analyze(
                image_path=state.screenshot_path,
                scene_type=scene_type,
            )
            
            if result.success:
                # 添加到记忆
                self.memory.add_snapshot(snapshot)
                return snapshot
            else:
                return None
                
        except Exception as e:
            logger.error(f"按需分析失败: {e}")
            return None
    
    def get_status(self) -> Dict[str, Any]:
        """
        获取感知引擎状态
        
        Returns:
            状态信息字典
        """
        return {
            "enabled": self.config.enabled,
            "is_running": self._is_running,
            "analyze_interval": self.config.analyze_interval,
            "memory_size": len(self.memory.snapshots),
            "memory_max_size": self.memory.max_size,
            "last_analysis_time": self._last_analysis_time.isoformat() if self._last_analysis_time else None,
            "config": {
                "enable_error_detection": self.config.enable_error_detection,
                "enable_focus_evaluation": self.config.enable_focus_evaluation,
                "enable_companion_mode": self.config.enable_companion_mode,
                "error_persistence_threshold": self.config.error_persistence_threshold,
                "stuck_threshold": self.config.stuck_threshold,
                "idle_threshold": self.config.idle_threshold,
            }
        }
    
    def update_config(self, **kwargs):
        """
        更新配置
        
        Args:
            **kwargs: 配置参数
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                logger.info(f"感知引擎配置更新: {key}={value}")
        
        # 如果更新了关键配置，可能需要重启监控任务
        if "analyze_interval" in kwargs or "enabled" in kwargs:
            if self._is_running:
                logger.info("关键配置已更新，建议重启感知引擎")
    
    def clear_memory(self):
        """清空场景记忆"""
        self.memory.clear()
        logger.info("场景记忆已清空")