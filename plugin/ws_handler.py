"""
WebSocket 客户端管理器和消息处理模块

这个模块提供：
1. ClientManager: 管理所有已连接的桌面客户端
2. 数据类: ClientDesktopState, ScreenshotRequest, ScreenshotResponse
3. 消息处理逻辑

注意：这个模块不再包含 WebSocket 服务器逻辑，服务器功能已移至 ws_server.py
"""

import asyncio
import base64
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from astrbot.api import logger


@dataclass
class ClientDesktopState:
    """
    客户端上报的桌面状态
    
    桌面客户端会定期上报当前的桌面状态，包括：
    - 活动窗口信息（标题、进程名、PID）
    - 可选的截图数据
    - 运行中的应用列表
    """
    session_id: str                              # 客户端会话 ID
    timestamp: str                               # 状态时间戳
    active_window_title: Optional[str] = None   # 活动窗口标题
    active_window_process: Optional[str] = None # 活动窗口进程名
    active_window_pid: Optional[int] = None     # 活动窗口进程 PID
    screenshot_base64: Optional[str] = None     # 截图 Base64 数据
    screenshot_width: Optional[int] = None      # 截图宽度
    screenshot_height: Optional[int] = None     # 截图高度
    screenshot_path: Optional[str] = None       # 截图落盘路径（服务端保存后填充）
    running_apps: Optional[list] = None         # 运行中的应用列表
    window_changed: bool = False                # 窗口是否发生变化
    previous_window_title: Optional[str] = None # 上一个窗口标题
    received_at: Optional[datetime] = None      # 服务端接收时间
    
    @classmethod
    def from_dict(cls, session_id: str, data: dict) -> "ClientDesktopState":
        """从字典创建实例"""
        return cls(
            session_id=session_id,
            timestamp=data.get("timestamp", datetime.now().isoformat()),
            active_window_title=data.get("active_window_title"),
            active_window_process=data.get("active_window_process"),
            active_window_pid=data.get("active_window_pid"),
            screenshot_base64=data.get("screenshot_base64"),
            screenshot_width=data.get("screenshot_width"),
            screenshot_height=data.get("screenshot_height"),
            screenshot_path=data.get("screenshot_path"),
            running_apps=data.get("running_apps"),
            window_changed=data.get("window_changed", False),
            previous_window_title=data.get("previous_window_title"),
            received_at=datetime.now(),
        )


@dataclass
class ScreenshotRequest:
    """
    截图请求
    
    当用户发送截图命令时，会创建一个截图请求并发送给桌面客户端。
    """
    request_id: str                                     # 请求唯一 ID
    session_id: str                                     # 目标客户端会话 ID
    created_at: datetime = field(default_factory=datetime.now)  # 创建时间
    timeout: float = 30.0                               # 超时时间（秒）
    
    def is_expired(self) -> bool:
        """检查请求是否已超时"""
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed > self.timeout


@dataclass
class ScreenshotResponse:
    """
    截图响应
    
    桌面客户端执行截图后返回的结果。
    """
    request_id: str                              # 对应的请求 ID
    session_id: str                              # 客户端会话 ID
    success: bool                                # 是否成功
    image_base64: Optional[str] = None           # 图片 Base64 数据
    image_path: Optional[str] = None             # 图片保存路径
    error_message: Optional[str] = None          # 错误信息
    width: Optional[int] = None                  # 图片宽度
    height: Optional[int] = None                 # 图片高度
    timestamp: datetime = field(default_factory=datetime.now)  # 响应时间


@dataclass
class CommandRequest:
    """
    通用命令请求
    
    当 LLM 调用桌宠可执行工具时，会创建一个命令请求并发送给桌面客户端，
    等待客户端执行完毕后返回结果。
    """
    request_id: str                              # 请求唯一 ID
    session_id: str                              # 目标客户端会话 ID
    command: str                                 # 命令名（对应桌宠 AgentEngine 工具名）
    params: dict = field(default_factory=dict)   # 命令参数
    created_at: datetime = field(default_factory=datetime.now)  # 创建时间
    timeout: float = 30.0                        # 超时时间（秒）

    def is_expired(self) -> bool:
        """检查请求是否已超时"""
        elapsed = (datetime.now() - self.created_at).total_seconds()
        return elapsed > self.timeout


class ClientManager:
    """
    WebSocket 客户端管理器
    
    管理所有已连接的桌面客户端，提供：
    - 客户端连接/断开管理
    - 消息发送（单发/广播）
    - 桌面状态管理
    - 截图请求/响应处理
    - 连接健康监控
    
    这个类被 ws_server.py 中的 StandaloneWebSocketServer 使用。
    
    稳定性增强：
    - 详细的连接状态检查
    - 重试机制
    - 连接质量监控
    """
    
    # 客户端活跃超时时间（秒）- 超过此时间未收到消息则认为客户端可能断开
    CLIENT_INACTIVE_TIMEOUT = 120  # 2分钟
    
    # 截图重试配置
    SCREENSHOT_MAX_RETRIES = 2  # 最大重试次数
    SCREENSHOT_RETRY_DELAY = 1.0  # 重试延迟（秒）
    
    # 过期请求清理配置
    EXPIRED_REQUEST_CLEANUP_INTERVAL = 30  # 清理间隔（秒）
    SCREENSHOT_REQUEST_MAX_AGE = 60  # 截图请求最大存活时间（秒）
    
    def __init__(self):
        # 存储客户端的最新桌面状态: session_id -> ClientDesktopState
        self.client_states: Dict[str, ClientDesktopState] = {}
        
        # 桌面状态更新回调
        self.on_desktop_state_update: Optional[Callable[[ClientDesktopState], Any]] = None
        
        # 客户端主动截图回调（session_id, image_path）
        self.on_manual_screenshot: Optional[Callable[[str, str], Any]] = None
        
        # 桌面感知开关回调（session_id, enabled）
        self.on_awareness_change: Optional[Callable[[str, bool], Any]] = None
        
        # 断线期间的待发送消息队列: session_id -> [message, ...]
        self._pending_messages: Dict[str, list] = {}
        self._pending_messages_max = 20
        
        # 截图请求管理
        self._pending_screenshot_requests: Dict[str, ScreenshotRequest] = {}
        self._screenshot_futures: Dict[str, asyncio.Future] = {}

        # 通用命令请求管理（LLM 工具 → 桌宠执行）
        self._pending_command_requests: Dict[str, CommandRequest] = {}
        self._command_futures: Dict[str, asyncio.Future] = {}
        # 通用命令请求最大存活时间（秒）
        self.COMMAND_REQUEST_MAX_AGE = 60
        
        # 截图保存目录
        self._screenshot_save_dir = "./temp/remote_screenshots"
        os.makedirs(self._screenshot_save_dir, exist_ok=True)

        # 截图保留策略
        self._max_screenshots = 20
        self._screenshot_max_age_hours = 24
        
        # WebSocket 服务器引用（由 main.py 设置）
        self._ws_server = None
        
        # 统计信息
        self._screenshot_success_count = 0
        self._screenshot_failure_count = 0
        
        # 过期请求清理任务
        self._cleanup_task: Optional[asyncio.Task] = None
        self._running = False
    
    def set_ws_server(self, ws_server):
        """设置 WebSocket 服务器引用"""
        self._ws_server = ws_server
    
    async def start_cleanup_task(self):
        """启动过期请求清理任务"""
        if self._cleanup_task is not None:
            return
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_expired_requests_loop())
        logger.info("截图请求清理任务已启动")
    
    async def stop_cleanup_task(self):
        """停止过期请求清理任务"""
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("截图请求清理任务已停止")
    
    async def _cleanup_expired_requests_loop(self):
        """
        定期清理过期的截图请求
        
        防止请求积累过多，影响系统性能
        """
        while self._running:
            try:
                await asyncio.sleep(self.EXPIRED_REQUEST_CLEANUP_INTERVAL)
                
                if not self._running:
                    break
                
                cleaned_count = self._cleanup_expired_requests()
                cleaned_files = self._cleanup_screenshot_files()
                
                if cleaned_count > 0:
                    logger.info(f"已清理 {cleaned_count} 个过期截图请求")
                if cleaned_files > 0:
                    logger.info(f"已清理 {cleaned_files} 个过期截图文件")
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"清理过期请求时异常: {e}")
    
    def _cleanup_expired_requests(self) -> int:
        """
        清理过期的截图请求
        
        Returns:
            清理的请求数量
        """
        cleaned_count = 0

        # 遍历所有待处理请求
        expired_request_ids = []
        for request_id, request in list(self._pending_screenshot_requests.items()):
            # 检查请求是否过期（使用请求的 timeout 或最大存活时间）
            age = (datetime.now() - request.created_at).total_seconds()
            max_age = max(request.timeout, self.SCREENSHOT_REQUEST_MAX_AGE)
            
            if age > max_age:
                expired_request_ids.append(request_id)
        
        # 清理过期请求
        for request_id in expired_request_ids:
            request = self._pending_screenshot_requests.pop(request_id, None)
            future = self._screenshot_futures.pop(request_id, None)
            
            if future and not future.done():
                # 设置超时错误结果
                future.set_result(ScreenshotResponse(
                    request_id=request_id,
                    session_id=request.session_id if request else "",
                    success=False,
                    error_message="请求已过期（清理任务）"
                ))
            
            cleaned_count += 1
            logger.debug(
                f"清理过期截图请求: request_id={request_id}, "
                f"session_id={request.session_id if request else 'N/A'}"
            )

        # 清理过期的通用命令请求
        expired_command_ids = []
        for request_id, request in list(self._pending_command_requests.items()):
            age = (datetime.now() - request.created_at).total_seconds()
            max_age = max(request.timeout, self.COMMAND_REQUEST_MAX_AGE)
            if age > max_age:
                expired_command_ids.append(request_id)

        for request_id in expired_command_ids:
            request = self._pending_command_requests.pop(request_id, None)
            future = self._command_futures.pop(request_id, None)

            if future and not future.done():
                future.set_result({
                    "success": False,
                    "error": "命令请求已过期（清理任务）",
                })

            cleaned_count += 1
            logger.debug(
                f"清理过期命令请求: request_id={request_id}, "
                f"command={request.command if request else 'N/A'}, "
                f"session_id={request.session_id if request else 'N/A'}"
            )

        return cleaned_count

    def configure_screenshot_retention(
        self,
        max_screenshots: Optional[int] = None,
        max_age_hours: Optional[int] = None,
    ):
        """配置截图保留策略"""
        if max_screenshots is not None:
            try:
                self._max_screenshots = max(0, int(max_screenshots))
            except (TypeError, ValueError):
                logger.warning(f"无效的 max_screenshots 配置: {max_screenshots}")
        if max_age_hours is not None:
            try:
                self._screenshot_max_age_hours = max(0, int(max_age_hours))
            except (TypeError, ValueError):
                logger.warning(f"无效的 screenshot_max_age_hours 配置: {max_age_hours}")

    def _cleanup_screenshot_files(self) -> int:
        """清理截图文件"""
        if not os.path.isdir(self._screenshot_save_dir):
            return 0
        if self._max_screenshots <= 0 and self._screenshot_max_age_hours <= 0:
            return 0

        now = time.time()
        max_age_seconds = self._screenshot_max_age_hours * 3600
        entries = []
        for name in os.listdir(self._screenshot_save_dir):
            path = os.path.join(self._screenshot_save_dir, name)
            if not os.path.isfile(path):
                continue
            try:
                entries.append((os.path.getmtime(path), path))
            except OSError:
                continue

        removed = 0
        if self._screenshot_max_age_hours > 0:
            for mtime, path in entries:
                if now - mtime > max_age_seconds:
                    try:
                        os.remove(path)
                        removed += 1
                    except OSError as e:
                        logger.debug(f"删除截图失败: {path} ({e})")

        if self._max_screenshots > 0:
            remaining = [(mtime, path) for mtime, path in entries if os.path.exists(path)]
            if len(remaining) > self._max_screenshots:
                remaining.sort(key=lambda item: item[0])
                over_limit = len(remaining) - self._max_screenshots
                for _, path in remaining[:over_limit]:
                    try:
                        os.remove(path)
                        removed += 1
                    except OSError as e:
                        logger.debug(f"删除截图失败: {path} ({e})")

        return removed

    
    def get_active_clients_count(self) -> int:
        """获取活跃客户端数量"""
        if self._ws_server:
            return self._ws_server.get_active_clients_count()
        return 0
    
    def get_connected_client_ids(self) -> List[str]:
        """获取所有已连接客户端的 session_id 列表"""
        if self._ws_server:
            return self._ws_server.get_connected_client_ids()
        return []
    
    def is_client_connected(self, session_id: str) -> bool:
        """
        检查指定客户端是否已连接且活跃
        
        Args:
            session_id: 客户端会话 ID
            
        Returns:
            客户端是否连接且活跃
        """
        if not self._ws_server:
            return False
        
        # 使用服务器的连接状态检查
        if hasattr(self._ws_server, 'is_client_connected'):
            return self._ws_server.is_client_connected(session_id)
        
        # 回退到简单的列表检查
        return session_id in self.get_connected_client_ids()
    
    def get_client_connection_info(self, session_id: str) -> dict:
        """
        获取客户端连接详细信息
        
        Args:
            session_id: 客户端会话 ID
            
        Returns:
            包含连接状态信息的字典
        """
        info = {
            "session_id": session_id,
            "connected": False,
            "last_activity": None,
            "has_state": False,
            "heartbeat_count": 0,
            "connection_quality": "unknown",
        }
        
        if self._ws_server:
            info["connected"] = session_id in self._ws_server.get_connected_client_ids()
            
            # 获取最后活跃时间
            if hasattr(self._ws_server, 'get_client_last_activity'):
                last_activity = self._ws_server.get_client_last_activity(session_id)
                if last_activity > 0:
                    info["last_activity"] = last_activity
                    seconds_since = time.time() - last_activity
                    info["seconds_since_activity"] = seconds_since
                    
                    # 评估连接质量
                    if seconds_since < 30:
                        info["connection_quality"] = "excellent"
                    elif seconds_since < 60:
                        info["connection_quality"] = "good"
                    elif seconds_since < 120:
                        info["connection_quality"] = "fair"
                    else:
                        info["connection_quality"] = "poor"
            
            # 获取服务器统计信息
            if hasattr(self._ws_server, 'get_server_stats'):
                stats = self._ws_server.get_server_stats()
                conn_details = stats.get("connection_details", {})
                if session_id in conn_details:
                    client_stats = conn_details[session_id]
                    info["heartbeat_count"] = client_stats.get("heartbeat_count", 0)
        
        # 检查是否有桌面状态
        if session_id in self.client_states:
            info["has_state"] = True
            state = self.client_states[session_id]
            if state.received_at:
                info["state_age_seconds"] = (datetime.now() - state.received_at).total_seconds()
        
        return info
    
    async def send_message(self, session_id: str, message: dict) -> bool:
        """
        发送消息给指定客户端
        
        Args:
            session_id: 目标客户端会话 ID
            message: 要发送的消息（字典格式）
            
        Returns:
            是否发送成功
        """
        if not self._ws_server:
            logger.warning("WebSocket 服务器未初始化")
            return False
        
        ok = await self._ws_server.send_to_client(session_id, message)
        if not ok:
            # 客户端暂时断线：缓存消息，待重连后补发，避免主动回话丢失
            queue = self._pending_messages.setdefault(session_id, [])
            content = message.get("content")
            if not queue or queue[-1].get("content") != content:
                queue.append(message)
                if len(queue) > self._pending_messages_max:
                    queue.pop(0)
            logger.info(f"客户端离线，消息已缓存待重连补发: session_id={session_id}, 队列={len(queue)}")
        return ok
    
    async def flush_pending_messages(self, session_id: str) -> int:
        """客户端重连后补发缓存的消息，返回补发数量"""
        queue = self._pending_messages.pop(session_id, None)
        if not queue:
            return 0
        sent = 0
        for message in queue:
            try:
                if await self._ws_server.send_to_client(session_id, message):
                    sent += 1
            except Exception as e:
                logger.error(f"补发缓存消息失败: {e}")
        logger.info(f"客户端重连，已补发缓存消息 {sent}/{len(queue)} 条: session_id={session_id}")
        return sent
    
    async def broadcast(self, message: dict) -> int:
        """
        广播消息给所有客户端
        
        Args:
            message: 要发送的消息（字典格式）
            
        Returns:
            成功发送的客户端数量
        """
        if not self._ws_server:
            logger.warning("WebSocket 服务器未初始化")
            return 0
        
        return await self._ws_server.broadcast(message)
    
    def update_client_state(self, session_id: str, state_data: dict) -> ClientDesktopState:
        """
        更新客户端桌面状态
        
        Args:
            session_id: 客户端会话 ID
            state_data: 状态数据字典
            
        Returns:
            更新后的 ClientDesktopState 对象
        """
        state = ClientDesktopState.from_dict(session_id, state_data)
        self.client_states[session_id] = state
        logger.debug(f"客户端桌面状态已更新: session_id={session_id}, window={state.active_window_title}")
        return state

    def save_base64_image(self, base64_data: str, filename_prefix: str = "ws_upload") -> Optional[str]:
        """保存 Base64 图片到本地文件，返回文件路径"""
        if not base64_data:
            return None
        data = base64_data.strip()
        if data.startswith("data:"):
            parts = data.split(",", 1)
            if len(parts) == 2:
                data = parts[1]
        try:
            image_bytes = base64.b64decode(data)
        except Exception as e:
            logger.error(f"Base64 图片解码失败: {e}")
            return None
        # 依据文件头判断真实格式，避免扩展名与实际内容不一致
        ext = "png"
        if image_bytes[:3] == b"\xff\xd8\xff":
            ext = "jpg"
        elif image_bytes[:8] == b"\x89PNG\r\n\x1a\n":
            ext = "png"
        elif image_bytes[:4] == b"GIF8":
            ext = "gif"
        elif image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            ext = "webp"
        elif image_bytes[:2] == b"BM":
            ext = "bmp"
        filename = f"{filename_prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}.{ext}"
        filepath = os.path.join(self._screenshot_save_dir, filename)
        try:
            with open(filepath, "wb") as f:
                f.write(image_bytes)
        except Exception as e:
            logger.error(f"保存图片失败: {e}")
            return None
        return filepath
    
    def remove_client_state(self, session_id: str):
        """移除客户端状态（客户端断开时调用）"""
        self.client_states.pop(session_id, None)
        
    def get_client_state(self, session_id: str) -> Optional[ClientDesktopState]:
        """获取客户端桌面状态"""
        return self.client_states.get(session_id)
        
    def get_all_client_states(self) -> Dict[str, ClientDesktopState]:
        """获取所有客户端桌面状态"""
        return self.client_states.copy()
    
    async def request_screenshot(
        self,
        session_id: Optional[str] = None,
        timeout: float = 30.0,
        retry: bool = True
    ) -> ScreenshotResponse:
        """
        请求客户端截图（带重试机制）
        
        Args:
            session_id: 目标客户端 session_id，为 None 则选择第一个可用客户端
            timeout: 超时时间（秒）
            retry: 是否启用重试
            
        Returns:
            ScreenshotResponse 对象
        """
        # 确定目标客户端
        connected_clients = self.get_connected_client_ids()
        
        if session_id is None:
            if not connected_clients:
                logger.warning("截图请求失败: 没有已连接的桌面客户端")
                self._screenshot_failure_count += 1
                return ScreenshotResponse(
                    request_id="",
                    session_id="",
                    success=False,
                    error_message="没有已连接的桌面客户端"
                )
            # 选择连接质量最好的客户端
            session_id = self._select_best_client(connected_clients)
            logger.info(f"自动选择客户端: {session_id}")
        
        # 详细的连接状态检查
        conn_info = self.get_client_connection_info(session_id)
        
        if session_id not in connected_clients:
            logger.warning(f"截图请求失败: 客户端未连接 - {conn_info}")
            self._screenshot_failure_count += 1
            return ScreenshotResponse(
                request_id="",
                session_id=session_id,
                success=False,
                error_message=f"客户端未连接: {session_id}"
            )
        
        # 检查连接质量
        if conn_info.get("connection_quality") == "poor":
            logger.warning(f"客户端连接质量较差，可能影响截图: {conn_info}")
        
        # 额外检查：验证连接是否真正活跃
        if not self.is_client_connected(session_id):
            logger.warning(f"截图请求失败: 客户端连接状态异常 - session_id={session_id}")
            self._screenshot_failure_count += 1
            return ScreenshotResponse(
                request_id="",
                session_id=session_id,
                success=False,
                error_message=f"客户端连接状态异常: {session_id}"
            )
        
        # 执行截图请求（带重试）
        max_attempts = self.SCREENSHOT_MAX_RETRIES + 1 if retry else 1
        last_error = None
        
        for attempt in range(max_attempts):
            if attempt > 0:
                logger.info(f"截图重试第 {attempt} 次...")
                await asyncio.sleep(self.SCREENSHOT_RETRY_DELAY)
                
                # 重试前再次检查连接
                if not self.is_client_connected(session_id):
                    logger.warning(f"重试前检测到客户端已断开: {session_id}")
                    break
            
            response = await self._do_screenshot_request(session_id, timeout)
            
            if response.success:
                self._screenshot_success_count += 1
                logger.info(f"截图成功 (尝试 {attempt + 1}/{max_attempts})")
                return response
            else:
                last_error = response.error_message
                logger.warning(f"截图失败 (尝试 {attempt + 1}/{max_attempts}): {last_error}")
        
        self._screenshot_failure_count += 1
        return ScreenshotResponse(
            request_id="",
            session_id=session_id,
            success=False,
            error_message=f"截图失败（已重试 {max_attempts} 次）: {last_error}"
        )

    async def request_command(
        self,
        session_id: Optional[str] = None,
        command: str = "",
        params: Optional[dict] = None,
        timeout: float = 30.0,
    ) -> dict:
        """
        请求桌面客户端执行通用命令并等待结果。

        让 LLM 的工具调用经过桌宠执行（桌宠可展示"正在执行"状态条），
        而非由 AstrBot 后端直接执行。

        Args:
            session_id: 目标客户端 session_id，为 None 则选择第一个可用客户端
            command: 命令名（对应桌宠 AgentEngine 工具名，如 get_system_info）
            params: 命令参数
            timeout: 超时时间（秒）

        Returns:
            桌宠执行结果 dict: {"success": bool, "data"/"error": ...}
        """
        if not command:
            return {"success": False, "error": "未指定命令"}

        # 确定目标客户端
        connected_clients = self.get_connected_client_ids()
        if session_id is None:
            if not connected_clients:
                logger.warning("命令请求失败: 没有已连接的桌面客户端")
                return {"success": False, "error": "没有已连接的桌面客户端"}
            session_id = self._select_best_client(connected_clients)
            logger.info(f"自动选择客户端: {session_id}")

        if session_id not in connected_clients:
            logger.warning(f"命令请求失败: 客户端未连接 - {session_id}")
            return {"success": False, "error": f"客户端未连接: {session_id}"}

        if not self.is_client_connected(session_id):
            logger.warning(f"命令请求失败: 客户端连接状态异常 - session_id={session_id}")
            return {"success": False, "error": f"客户端连接状态异常: {session_id}"}

        # 创建请求
        request_id = str(uuid.uuid4())
        request = CommandRequest(
            request_id=request_id,
            session_id=session_id,
            command=command,
            params=params or {},
            timeout=timeout,
        )
        self._pending_command_requests[request_id] = request

        # 创建 Future 用于等待响应
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._command_futures[request_id] = future

        try:
            # 发送命令到客户端
            send_success = await self.send_message(session_id, {
                "type": "command",
                "command": command,
                "request_id": request_id,
                "params": request.params,
            })

            if not send_success:
                return {"success": False, "error": "发送命令失败"}

            logger.info(
                f"已发送命令到客户端: session_id={session_id}, "
                f"request_id={request_id}, command={command}"
            )

            # 等待响应（带超时）
            response = await asyncio.wait_for(future, timeout=timeout)
            # response 为客户端回传的完整消息，取其 data 字段（AgentEngine 结果）
            return response.get("data", response) if isinstance(response, dict) else response

        except asyncio.TimeoutError:
            logger.warning(f"命令请求超时: request_id={request_id}, command={command}")
            return {"success": False, "error": f"命令执行超时: {command}"}
        except Exception as e:
            logger.error(f"命令请求失败: {e}")
            import traceback
            traceback.print_exc()
            return {"success": False, "error": str(e)}
        finally:
            # 清理
            self._pending_command_requests.pop(request_id, None)
            self._command_futures.pop(request_id, None)

    def handle_command_response(self, session_id: str, data: dict) -> Optional[dict]:
        """
        处理客户端回传的通用命令执行结果。

        Args:
            session_id: 客户端 session_id
            data: 客户端回传的 command_result 消息（含 request_id / command / data）

        Returns:
            原始消息 dict，如果无对应请求则返回 None
        """
        request_id = data.get("request_id")
        if not request_id:
            logger.warning("命令响应缺少 request_id")
            return None

        # 检查是否有对应的等待中的请求
        if request_id not in self._command_futures:
            logger.warning(f"未找到对应的命令请求: request_id={request_id}")
            return None

        # 完成 Future
        future = self._command_futures.get(request_id)
        if future and not future.done():
            future.set_result(data)

        self._pending_command_requests.pop(request_id, None)
        self._command_futures.pop(request_id, None)
        return data

    def _select_best_client(self, client_ids: List[str]) -> str:
        """
        选择连接质量最好的客户端
        
        Args:
            client_ids: 候选客户端列表
            
        Returns:
            选中的客户端 ID
        """
        if not client_ids:
            return ""
        
        if len(client_ids) == 1:
            return client_ids[0]
        
        # 按连接质量排序
        quality_order = {"excellent": 0, "good": 1, "fair": 2, "poor": 3, "unknown": 4}
        
        def get_quality_score(client_id: str) -> int:
            info = self.get_client_connection_info(client_id)
            quality = info.get("connection_quality", "unknown")
            return quality_order.get(quality, 5)
        
        sorted_clients = sorted(client_ids, key=get_quality_score)
        return sorted_clients[0]
    
    async def _do_screenshot_request(self, session_id: str, timeout: float) -> ScreenshotResponse:
        """
        执行单次截图请求
        
        Args:
            session_id: 目标客户端 session_id
            timeout: 超时时间（秒）
            
        Returns:
            ScreenshotResponse 对象
        """
        # 创建请求
        request_id = str(uuid.uuid4())
        request = ScreenshotRequest(
            request_id=request_id,
            session_id=session_id,
            timeout=timeout
        )
        
        self._pending_screenshot_requests[request_id] = request
        
        # 创建 Future 用于等待响应
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._screenshot_futures[request_id] = future
        
        try:
            # 发送截图命令到客户端
            send_success = await self.send_message(session_id, {
                "type": "command",
                "command": "screenshot",
                "request_id": request_id,
                "params": {
                    "type": "full",  # 全屏截图
                    "timestamp": time.time()
                }
            })
            
            if not send_success:
                return ScreenshotResponse(
                    request_id=request_id,
                    session_id=session_id,
                    success=False,
                    error_message="发送截图命令失败"
                )
            
            logger.info(f"已发送截图命令到客户端: session_id={session_id}, request_id={request_id}")
            
            # 等待响应（带超时）
            response = await asyncio.wait_for(future, timeout=timeout)
            return response
            
        except asyncio.TimeoutError:
            logger.warning(f"截图请求超时: request_id={request_id}")
            return ScreenshotResponse(
                request_id=request_id,
                session_id=session_id,
                success=False,
                error_message="截图请求超时"
            )
        except Exception as e:
            logger.error(f"截图请求失败: {e}")
            import traceback
            traceback.print_exc()
            return ScreenshotResponse(
                request_id=request_id,
                session_id=session_id,
                success=False,
                error_message=str(e)
            )
        finally:
            # 清理
            self._pending_screenshot_requests.pop(request_id, None)
            self._screenshot_futures.pop(request_id, None)
    
    def handle_screenshot_response(self, session_id: str, data: dict) -> Optional[ScreenshotResponse]:
        """
        处理客户端返回的截图响应
        
        Args:
            session_id: 客户端 session_id
            data: 响应数据
            
        Returns:
            ScreenshotResponse 对象，如果无对应请求则返回 None
        """
        request_id = data.get("request_id")
        if not request_id:
            logger.warning("截图响应缺少 request_id")
            return None
        
        success = data.get("success", False)
        image_base64 = data.get("image_base64")
        error_message = data.get("error_message")
        
        # 无对应的等待请求：客户端主动发起的截图（如 manual_xxx）
        # 保存为客户端最新状态，而不是报错
        if request_id not in self._screenshot_futures:
            saved_path = None
            if success and image_base64:
                saved_path = self.save_base64_image(image_base64, "manual")
            state = self.client_states.get(session_id)
            if state is not None:
                if image_base64:
                    state.screenshot_base64 = image_base64
                if saved_path:
                    state.screenshot_path = saved_path
            logger.info(
                f"收到客户端主动截图（无等待请求）: request_id={request_id}, "
                f"saved={saved_path}"
            )
            # 触发自动分析回调（由插件适配器处理）
            if saved_path and self.on_manual_screenshot:
                try:
                    result = self.on_manual_screenshot(session_id, saved_path)
                    if asyncio.iscoroutine(result):
                        asyncio.create_task(result)
                except Exception as e:
                    logger.error(f"主动截图回调执行失败: {e}")
            return ScreenshotResponse(
                request_id=request_id,
                session_id=session_id,
                success=success,
                image_base64=image_base64,
                error_message=error_message,
                width=data.get("width"),
                height=data.get("height"),
            )
        
        response = ScreenshotResponse(
            request_id=request_id,
            session_id=session_id,
            success=success,
            image_base64=image_base64,
            error_message=error_message,
            width=data.get("width"),
            height=data.get("height")
        )
        
        # 如果成功且有图片数据，保存到文件
        if success and image_base64:
            try:
                image_data = base64.b64decode(image_base64)
                filename = f"screenshot_{request_id}_{int(time.time() * 1000)}.png"
                filepath = os.path.join(self._screenshot_save_dir, filename)
                
                with open(filepath, "wb") as f:
                    f.write(image_data)
                
                response.image_path = filepath
                logger.info(f"截图已保存: {filepath}")
            except Exception as e:
                logger.error(f"保存截图失败: {e}")
        
        # 完成 Future
        future = self._screenshot_futures.get(request_id)
        if future and not future.done():
            future.set_result(response)
        
        return response
    
    def get_screenshot_stats(self) -> dict:
        """
        获取截图统计信息
        
        Returns:
            包含成功/失败次数的字典
        """
        total = self._screenshot_success_count + self._screenshot_failure_count
        success_rate = (self._screenshot_success_count / total * 100) if total > 0 else 0
        
        return {
            "success_count": self._screenshot_success_count,
            "failure_count": self._screenshot_failure_count,
            "total_count": total,
            "success_rate": f"{success_rate:.1f}%",
            "pending_requests": len(self._pending_screenshot_requests)
        }


class MessageHandler:
    """
    消息处理器
    
    处理来自桌面客户端的各种消息类型。
    这个类被 main.py 使用，作为 StandaloneWebSocketServer 的消息回调。
    """
    
    def __init__(self, client_manager: ClientManager):
        """
        初始化消息处理器
        
        Args:
            client_manager: 客户端管理器实例
        """
        self.manager = client_manager
        
        # 配置同步回调（由 main.py 设置）
        self.on_config_sync: Optional[Callable[[str, dict], Any]] = None
        # 客户端聊天消息回调（由 main.py 设置）
        self.on_chat_message: Optional[Callable[[str, dict], Any]] = None
    
    async def handle_message(self, session_id: str, data: dict):
        """
        处理客户端消息
        
        Args:
            session_id: 客户端会话 ID
            data: 消息数据
        """
        msg_type = data.get("type", "")
        
        if msg_type == "desktop_state":
            # 处理桌面状态上报
            await self._handle_desktop_state(session_id, data)
            
        elif msg_type == "awareness":
            # 处理桌面感知开关状态
            await self._handle_awareness(session_id, data)
            
        elif msg_type == "screenshot_response":
            # 处理截图响应
            response_data = data.get("data", {})
            self.manager.handle_screenshot_response(session_id, response_data)
            logger.debug(f"收到截图响应: session_id={session_id}")
            
        elif msg_type == "command_result":
            # 处理通用命令执行结果
            command = data.get("command")
            if command == "screenshot":
                response_data = data.get("data", {})
                self.manager.handle_screenshot_response(session_id, response_data)
            else:
                # 其他命令交给通用命令通道处理（request_command 的等待方）
                self.manager.handle_command_response(session_id, data)
        
        elif msg_type == "config_sync":
            # 处理客户端配置同步
            await self._handle_config_sync(session_id, data)
                
        elif msg_type == "chat_message":
            # 处理客户端聊天消息
            await self._handle_chat_message(session_id, data)
                
        elif msg_type == "state_sync":
            # 处理客户端状态同步（保留向后兼容）
            pass
        
        else:
            logger.debug(f"收到未知类型消息: type={msg_type}, session_id={session_id}")
    
    async def _handle_desktop_state(self, session_id: str, data: dict):
        """处理桌面状态上报"""
        state_data = data.get("data", {})
        state = self.manager.update_client_state(session_id, state_data)
        
        # 触发回调（如果设置）
        if self.manager.on_desktop_state_update:
            try:
                result = self.manager.on_desktop_state_update(state)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"桌面状态回调执行失败: {e}")
        
        # 发送确认
        await self.manager.send_message(session_id, {
            "type": "desktop_state_ack",
            "timestamp": state.timestamp,
        })
    
    async def _handle_awareness(self, session_id: str, data: dict):
        """处理桌面感知开关状态"""
        enabled = bool(data.get("data", {}).get("enabled", False))
        logger.info(f"收到桌面感知开关状态: session_id={session_id}, enabled={enabled}")
        # 触发回调（由插件适配器启停主动回话）
        if self.manager.on_awareness_change:
            try:
                result = self.manager.on_awareness_change(session_id, enabled)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"桌面感知开关回调执行失败: {e}")
    
    async def _handle_config_sync(self, session_id: str, data: dict):
        """
        处理客户端配置同步
        
        客户端在连接成功后会发送其保存的配置（如 TTS dual_output），
        服务端需要将这些配置应用到 AstrBot 核心。
        
        Args:
            session_id: 客户端会话 ID
            data: 配置数据
        """
        config_data = data.get("data", {})
        logger.info(f"收到客户端配置同步: session_id={session_id}, config={config_data}")
        
        # 触发配置同步回调（由 main.py 处理实际的配置应用）
        if self.on_config_sync:
            try:
                result = self.on_config_sync(session_id, config_data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"配置同步回调执行失败: {e}")
        
        # 发送确认
        await self.manager.send_message(session_id, {
            "type": "config_sync_ack",
            "success": True,
        })

    async def _handle_chat_message(self, session_id: str, data: dict):
        """
        处理客户端聊天消息

        Args:
            session_id: 客户端会话 ID
            data: 聊天数据
        """
        if self.on_chat_message:
            try:
                result = self.on_chat_message(session_id, data)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:
                logger.error(f"聊天消息回调执行失败: {e}")
    
    async def on_client_connect(self, session_id: str):
        """客户端连接回调"""
        logger.info(f"客户端已连接: session_id={session_id}")
        # 记录连接时间
        logger.debug(f"当前活跃客户端数: {self.manager.get_active_clients_count()}")
        # 补发断线期间缓存的消息（如主动回话）
        try:
            await self.manager.flush_pending_messages(session_id)
        except Exception as e:
            logger.error(f"补发缓存消息失败: {e}")
    
    def on_client_disconnect(self, session_id: str):
        """客户端断开回调"""
        logger.info(f"客户端已断开: session_id={session_id}")
        
        # 清理客户端状态
        self.manager.remove_client_state(session_id)
        
        # 取消该客户端的所有待处理截图请求
        cancelled_count = 0
        for request_id, request in list(self.manager._pending_screenshot_requests.items()):
            if request.session_id == session_id:
                future = self.manager._screenshot_futures.get(request_id)
                if future and not future.done():
                    future.set_result(ScreenshotResponse(
                        request_id=request_id,
                        session_id=session_id,
                        success=False,
                        error_message="客户端已断开连接"
                    ))
                    cancelled_count += 1
                self.manager._pending_screenshot_requests.pop(request_id, None)
                self.manager._screenshot_futures.pop(request_id, None)
        
        if cancelled_count > 0:
            logger.info(f"已取消 {cancelled_count} 个待处理的截图请求")

        # 取消该客户端的所有待处理通用命令请求
        cancelled_commands = 0
        for request_id, request in list(self.manager._pending_command_requests.items()):
            if request.session_id == session_id:
                future = self.manager._command_futures.get(request_id)
                if future and not future.done():
                    future.set_result({
                        "success": False,
                        "error": "客户端已断开连接",
                    })
                    cancelled_commands += 1
                self.manager._pending_command_requests.pop(request_id, None)
                self.manager._command_futures.pop(request_id, None)

        if cancelled_commands > 0:
            logger.info(f"已取消 {cancelled_commands} 个待处理的命令请求")
        
        logger.debug(f"剩余活跃客户端数: {self.manager.get_active_clients_count()}")
