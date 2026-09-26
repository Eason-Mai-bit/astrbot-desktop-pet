"""
桌面监控服务

提供桌面状态管理和主动对话触发功能（服务端）。
从客户端接收桌面状态数据，而非在服务端本地捕获。
"""

import asyncio
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from astrbot import logger


@dataclass
class DesktopState:
    """桌面状态（服务端视角）"""
    # 会话 ID（关联客户端）
    session_id: str
    # 捕获时间
    capture_time: datetime
    # 活动窗口标题
    window_title: Optional[str] = None
    # 活动窗口进程名
    active_window: Optional[str] = None
    # 上一个窗口标题
    previous_window: Optional[str] = None
    # 窗口是否变化
    window_changed: bool = False
    # 截图数据（Base64）
    screenshot_base64: Optional[str] = None
    # 截图路径（如果保存到本地）
    screenshot_path: Optional[str] = None
    # 运行中的应用
    running_apps: Optional[list] = None
    
    @classmethod
    def from_client_state(cls, client_state: Any) -> "DesktopState":
        """从客户端上报的状态创建"""
        return cls(
            session_id=client_state.session_id,
            capture_time=datetime.fromisoformat(client_state.timestamp) if client_state.timestamp else datetime.now(),
            window_title=client_state.active_window_title,
            active_window=client_state.active_window_process,
            previous_window=client_state.previous_window_title,
            window_changed=client_state.window_changed,
            screenshot_base64=client_state.screenshot_base64,
            screenshot_path=getattr(client_state, "screenshot_path", None),
            running_apps=client_state.running_apps,
        )


class DesktopMonitorService:
    """
    桌面监控服务（服务端）
    
    此服务不再本地捕获桌面状态，而是接收客户端通过 WebSocket 上报的数据。
    """
    
    def __init__(
        self,
        proactive_min_interval: int = 300,
        proactive_max_interval: int = 600,
        on_state_change: Optional[Callable[[DesktopState], Any]] = None,
        on_proactive_trigger: Optional[Callable[[DesktopState], Any]] = None,
        on_window_change: Optional[Callable[[DesktopState], Any]] = None,
    ):
        """
        初始化桌面监控服务
        
        Args:
            proactive_min_interval: 主动对话最小间隔（秒）
            proactive_max_interval: 主动对话最大间隔（秒）
            on_state_change: 桌面状态变化回调
            on_proactive_trigger: 主动对话触发回调
            on_window_change: 窗口变化回调
        """
        self.proactive_min_interval = proactive_min_interval
        self.proactive_max_interval = proactive_max_interval
        self.on_state_change = on_state_change
        self.on_proactive_trigger = on_proactive_trigger
        self.on_window_change = on_window_change
        
        self._is_monitoring = False
        self._proactive_task: Optional[asyncio.Task] = None
        # 存储各客户端的最新状态: session_id -> DesktopState
        self._client_states: Dict[str, DesktopState] = {}
        self._proactive_enabled = True
        
    @property
    def is_monitoring(self) -> bool:
        """是否正在监控"""
        return self._is_monitoring
        
    @property
    def proactive_enabled(self) -> bool:
        """是否启用主动对话"""
        return self._proactive_enabled
        
    @proactive_enabled.setter
    def proactive_enabled(self, value: bool):
        """设置是否启用主动对话"""
        self._proactive_enabled = value
        
    async def start(self):
        """启动监控服务"""
        if self._is_monitoring:
            return
            
        self._is_monitoring = True
        logger.info("桌面监控服务启动中（等待客户端连接）...")
        
        # 启动主动对话循环
        if self._proactive_enabled:
            self._proactive_task = asyncio.create_task(self._proactive_loop())
            
        logger.info("桌面监控服务已启动")
            
    async def stop(self):
        """停止监控"""
        self._is_monitoring = False
        logger.info("桌面监控服务停止中...")
        
        if self._proactive_task:
            self._proactive_task.cancel()
            try:
                await self._proactive_task
            except asyncio.CancelledError:
                pass
            self._proactive_task = None
        
        logger.info("桌面监控服务已停止")
    
    async def handle_client_state(self, client_state: Any) -> Optional[DesktopState]:
        """
        处理客户端上报的桌面状态
        
        Args:
            client_state: 客户端上报的 ClientDesktopState 对象
            
        Returns:
            转换后的 DesktopState 对象
        """
        try:
            # 转换为服务端状态
            state = DesktopState.from_client_state(client_state)
            
            # 获取该客户端的上一个状态
            previous_state = self._client_states.get(state.session_id)
            
            # 更新状态
            self._client_states[state.session_id] = state
            
            # 触发状态变化回调
            if self.on_state_change:
                await self._safe_callback(self.on_state_change, state)
            
            # 检测窗口变化
            if state.window_changed and self.on_window_change:
                logger.info(f"检测到窗口变化: {state.previous_window} -> {state.window_title}")
                await self._safe_callback(self.on_window_change, state)
            
            return state
            
        except Exception as e:
            logger.error(f"处理客户端状态失败: {e}")
            return None

    async def _proactive_loop(self):
        """主动对话循环"""
        while self._is_monitoring and self._proactive_enabled:
            try:
                # 随机等待时间
                wait_time = random.randint(
                    self.proactive_min_interval,
                    self.proactive_max_interval
                )
                logger.debug(f"下次主动对话将在 {wait_time} 秒后触发")
                await asyncio.sleep(wait_time)
                
                if not self._is_monitoring or not self._proactive_enabled:
                    break
                
                # 从已连接的客户端中选择一个触发主动对话
                state = self._get_any_client_state()
                if state and self.on_proactive_trigger:
                    logger.info(f"触发主动对话，客户端: {state.session_id}, 窗口: {state.window_title}")
                    await self._safe_callback(self.on_proactive_trigger, state)
                else:
                    logger.debug("没有活跃的客户端状态，跳过主动对话")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"主动对话触发错误: {e}")
                
    def _get_any_client_state(self) -> Optional[DesktopState]:
        """获取任意一个客户端的最新状态"""
        if not self._client_states:
            return None
        # 返回最近更新的状态
        return max(self._client_states.values(), key=lambda s: s.capture_time, default=None)
    
    def get_client_state(self, session_id: str) -> Optional[DesktopState]:
        """获取指定客户端的桌面状态"""
        return self._client_states.get(session_id)
    
    def get_all_client_states(self) -> Dict[str, DesktopState]:
        """获取所有客户端的桌面状态"""
        return self._client_states.copy()

    def get_last_state(self, session_id: Optional[str] = None) -> Optional[DesktopState]:
        """获取最新的桌面状态"""
        if session_id:
            return self._client_states.get(session_id)
        return self._get_any_client_state()
            
    async def _safe_callback(self, callback: Callable, *args):
        """安全调用回调"""
        try:
            result = callback(*args)
            if asyncio.iscoroutine(result):
                await result
        except Exception as e:
            logger.error(f"回调执行错误: {e}")
            
    async def trigger_proactive_now(self, session_id: Optional[str] = None) -> Optional[DesktopState]:
        """
        立即触发一次主动对话
        
        Args:
            session_id: 指定客户端，不指定则选择任意活跃客户端
        """
        logger.info(f"手动触发主动对话: session_id={session_id}")
        
        if session_id:
            state = self._client_states.get(session_id)
        else:
            state = self._get_any_client_state()
            
        if state and self.on_proactive_trigger:
            await self._safe_callback(self.on_proactive_trigger, state)
        return state
        
    def get_connected_clients_count(self) -> int:
        """获取已连接客户端数量"""
        return len(self._client_states)
        
    def remove_client(self, session_id: str):
        """移除客户端状态（客户端断开连接时调用）"""
        if session_id in self._client_states:
            del self._client_states[session_id]
            logger.info(f"已移除客户端状态: session_id={session_id}")
