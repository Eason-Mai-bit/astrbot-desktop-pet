"""
主动对话服务

提供多种策略的主动对话触发功能。
"""

import asyncio
import random
from dataclasses import dataclass, field
from datetime import datetime, time as dt_time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from astrbot import logger

from .desktop_monitor import DesktopMonitorService, DesktopState


class TriggerType(Enum):
    """触发类型"""
    RANDOM = "random"           # 随机触发
    WINDOW_CHANGE = "window"    # 窗口变化触发
    SCHEDULED = "scheduled"     # 定时触发
    IDLE = "idle"               # 空闲触发


@dataclass
class TriggerEvent:
    """触发事件"""
    trigger_type: TriggerType
    desktop_state: Optional[DesktopState]
    timestamp: datetime
    context: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def has_screenshot(self) -> bool:
        """是否有截图"""
        return self.desktop_state is not None and bool(self.desktop_state.screenshot_path)


@dataclass
class ScheduledGreeting:
    """定时问候配置"""
    time: dt_time
    message_hint: str
    enabled: bool = True
    last_triggered: Optional[datetime] = None


@dataclass
class ProactiveDialogConfig:
    """主动对话配置"""
    # 随机触发
    random_enabled: bool = True
    random_probability: float = 0.3  # 30% 概率
    random_min_interval: int = 300   # 最小间隔 5 分钟
    random_max_interval: int = 900   # 最大间隔 15 分钟
    
    # 窗口变化触发
    window_change_enabled: bool = True
    window_change_cooldown: int = 60  # 冷却时间 1 分钟
    window_change_probability: float = 0.2  # 20% 概率
    
    # 定时问候
    scheduled_enabled: bool = True
    scheduled_greetings: List[ScheduledGreeting] = field(default_factory=list)
    
    # 空闲触发
    idle_enabled: bool = False
    idle_threshold: int = 300  # 空闲 5 分钟后触发
    
    def __post_init__(self):
        """初始化默认定时问候"""
        if not self.scheduled_greetings:
            self.scheduled_greetings = [
                ScheduledGreeting(
                    time=dt_time(9, 0),
                    message_hint="早上好！新的一天开始了，有什么可以帮助你的吗？"
                ),
                ScheduledGreeting(
                    time=dt_time(12, 0),
                    message_hint="中午了，记得休息一下，吃点东西哦~"
                ),
                ScheduledGreeting(
                    time=dt_time(18, 0),
                    message_hint="傍晚了，今天工作辛苦了！"
                ),
            ]


class ProactiveDialogService:
    """主动对话服务"""
    
    def __init__(
        self,
        desktop_monitor: DesktopMonitorService,
        config: Optional[ProactiveDialogConfig] = None,
        on_trigger: Optional[Callable[[TriggerEvent], Any]] = None,
    ):
        """
        初始化主动对话服务
        
        Args:
            desktop_monitor: 桌面监控服务
            config: 主动对话配置
            on_trigger: 触发回调函数
        """
        self.desktop_monitor = desktop_monitor
        self.config = config or ProactiveDialogConfig()
        self.on_trigger = on_trigger
        
        self._is_running = False
        self._random_task: Optional[asyncio.Task] = None
        self._scheduled_task: Optional[asyncio.Task] = None
        self._idle_task: Optional[asyncio.Task] = None
        
        # 状态追踪
        self._last_random_trigger: Optional[datetime] = None
        self._last_window_change_trigger: Optional[datetime] = None
        self._last_activity_time: datetime = datetime.now()
        
        # 注册窗口变化回调
        self.desktop_monitor.on_window_change = self._on_window_change
        
    @property
    def is_running(self) -> bool:
        """是否正在运行"""
        return self._is_running
        
    async def start(self):
        """启动主动对话服务"""
        if self._is_running:
            return
            
        self._is_running = True
        logger.info("主动对话服务启动中...")
        
        # 启动各种触发任务
        if self.config.random_enabled:
            self._random_task = asyncio.create_task(self._random_trigger_loop())
            
        if self.config.scheduled_enabled:
            self._scheduled_task = asyncio.create_task(self._scheduled_trigger_loop())
            
        if self.config.idle_enabled:
            self._idle_task = asyncio.create_task(self._idle_trigger_loop())
            
        logger.info("主动对话服务已启动")
        
    async def stop(self):
        """停止主动对话服务"""
        self._is_running = False
        logger.info("主动对话服务停止中...")
        
        tasks = [self._random_task, self._scheduled_task, self._idle_task]
        for task in tasks:
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
                    
        self._random_task = None
        self._scheduled_task = None
        self._idle_task = None
        
        logger.info("主动对话服务已停止")
        
    async def _random_trigger_loop(self):
        """随机触发循环"""
        while self._is_running:
            try:
                # 随机等待
                wait_time = random.randint(
                    self.config.random_min_interval,
                    self.config.random_max_interval
                )
                await asyncio.sleep(wait_time)
                
                if not self._is_running:
                    break
                    
                # 概率判断
                if random.random() > self.config.random_probability:
                    logger.debug("随机触发：概率未命中，跳过")
                    continue
                    
                # 获取桌面状态并触发（从客户端上报的最新状态）
                state = self.desktop_monitor.get_last_state()
                event = TriggerEvent(
                    trigger_type=TriggerType.RANDOM,
                    desktop_state=state,
                    timestamp=datetime.now(),
                    context={"reason": "random_interval"}
                )
                
                self._last_random_trigger = datetime.now()
                await self._fire_trigger(event)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"随机触发错误: {e}")
                await asyncio.sleep(10)
                
    async def _scheduled_trigger_loop(self):
        """定时触发循环"""
        while self._is_running:
            try:
                now = datetime.now()
                current_time = now.time()
                
                for greeting in self.config.scheduled_greetings:
                    if not greeting.enabled:
                        continue
                        
                    # 检查是否在触发时间窗口内（1分钟内）
                    greeting_minutes = greeting.time.hour * 60 + greeting.time.minute
                    current_minutes = current_time.hour * 60 + current_time.minute
                    
                    if abs(greeting_minutes - current_minutes) <= 1:
                        # 检查今天是否已触发
                        if greeting.last_triggered:
                            if greeting.last_triggered.date() == now.date():
                                continue
                                
                        # 获取桌面状态并触发（从客户端上报的最新状态）
                        state = self.desktop_monitor.get_last_state()
                        event = TriggerEvent(
                            trigger_type=TriggerType.SCHEDULED,
                            desktop_state=state,
                            timestamp=now,
                            context={
                                "reason": "scheduled_greeting",
                                "message_hint": greeting.message_hint,
                                "scheduled_time": greeting.time.isoformat()
                            }
                        )
                        
                        greeting.last_triggered = now
                        await self._fire_trigger(event)
                        
                # 每分钟检查一次
                await asyncio.sleep(60)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"定时触发错误: {e}")
                await asyncio.sleep(60)
                
    async def _idle_trigger_loop(self):
        """空闲触发循环"""
        while self._is_running:
            try:
                now = datetime.now()
                idle_duration = (now - self._last_activity_time).total_seconds()
                
                if idle_duration >= self.config.idle_threshold:
                    # 获取桌面状态并触发（从客户端上报的最新状态）
                    state = self.desktop_monitor.get_last_state()
                    event = TriggerEvent(
                        trigger_type=TriggerType.IDLE,
                        desktop_state=state,
                        timestamp=now,
                        context={
                            "reason": "user_idle",
                            "idle_duration": idle_duration
                        }
                    )
                    
                    await self._fire_trigger(event)
                    
                    # 重置活动时间，避免重复触发
                    self._last_activity_time = now
                    
                await asyncio.sleep(30)  # 每 30 秒检查一次
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"空闲触发错误: {e}")
                await asyncio.sleep(30)
                
    async def _on_window_change(self, state: DesktopState):
        """窗口变化回调"""
        if not self._is_running or not self.config.window_change_enabled:
            return
            
        now = datetime.now()
        
        # 检查冷却时间
        if self._last_window_change_trigger:
            cooldown = (now - self._last_window_change_trigger).total_seconds()
            if cooldown < self.config.window_change_cooldown:
                logger.debug(f"窗口变化触发：冷却中 ({cooldown:.1f}s)")
                return
                
        # 概率判断
        if random.random() > self.config.window_change_probability:
            logger.debug("窗口变化触发：概率未命中，跳过")
            return
            
        event = TriggerEvent(
            trigger_type=TriggerType.WINDOW_CHANGE,
            desktop_state=state,
            timestamp=now,
            context={
                "reason": "window_changed",
                "previous_window": state.previous_window,
                "current_window": state.window_title
            }
        )
        
        self._last_window_change_trigger = now
        await self._fire_trigger(event)
        
    async def _fire_trigger(self, event: TriggerEvent):
        """触发事件"""
        logger.info(
            f"主动对话触发: type={event.trigger_type.value}, "
            f"window={event.desktop_state.window_title if event.desktop_state else 'N/A'}"
        )
        
        if self.on_trigger:
            try:
                result = self.on_trigger(event)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"触发回调执行错误: {e}")
                
    def record_activity(self):
        """记录用户活动（用于空闲检测）"""
        self._last_activity_time = datetime.now()
        
    def update_config(self, **kwargs):
        """
        更新配置
        
        Args:
            **kwargs: 配置参数
        """
        for key, value in kwargs.items():
            if hasattr(self.config, key):
                setattr(self.config, key, value)
                
    def add_scheduled_greeting(
        self,
        hour: int,
        minute: int,
        message_hint: str,
        enabled: bool = True
    ):
        """
        添加定时问候
        
        Args:
            hour: 小时 (0-23)
            minute: 分钟 (0-59)
            message_hint: 问候提示
            enabled: 是否启用
        """
        greeting = ScheduledGreeting(
            time=dt_time(hour, minute),
            message_hint=message_hint,
            enabled=enabled
        )
        self.config.scheduled_greetings.append(greeting)
        
    def remove_scheduled_greeting(self, index: int):
        """
        移除定时问候
        
        Args:
            index: 索引
        """
        if 0 <= index < len(self.config.scheduled_greetings):
            self.config.scheduled_greetings.pop(index)
            
    def get_status(self) -> dict:
        """
        获取服务状态
        
        Returns:
            状态信息字典
        """
        return {
            "is_running": self._is_running,
            "config": {
                "random_enabled": self.config.random_enabled,
                "random_probability": self.config.random_probability,
                "window_change_enabled": self.config.window_change_enabled,
                "scheduled_enabled": self.config.scheduled_enabled,
                "idle_enabled": self.config.idle_enabled,
            },
            "last_random_trigger": self._last_random_trigger.isoformat() if self._last_random_trigger else None,
            "last_window_change_trigger": self._last_window_change_trigger.isoformat() if self._last_window_change_trigger else None,
            "scheduled_greetings_count": len(self.config.scheduled_greetings),
        }
        
    async def trigger_now(self, include_screenshot: bool = True) -> TriggerEvent:
        """
        立即触发一次主动对话
        
        Args:
            include_screenshot: 是否包含截图
            
        Returns:
            触发事件
        """
        state = None
        if include_screenshot:
            # 从客户端上报的最新状态获取
            state = self.desktop_monitor.get_last_state()
            
        event = TriggerEvent(
            trigger_type=TriggerType.RANDOM,
            desktop_state=state,
            timestamp=datetime.now(),
            context={"reason": "manual_trigger"}
        )
        
        await self._fire_trigger(event)
        return event