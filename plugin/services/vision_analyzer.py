"""
视觉分析服务 - 使用多模态 LLM 分析桌面截图

该服务封装了多模态 LLM 调用逻辑，用于分析截图内容并返回文本描述。
支持三种识图模式：auto（自动检测）、chat（对话模型）、dedicated（独立模型）。
"""

import base64
import json
import os
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from astrbot import logger


class VisionMode(Enum):
    """识图模式枚举"""
    AUTO = "auto"           # 自动检测，优先对话模型，失败时提示配置
    CHAT = "chat"           # 强制使用对话模型
    DEDICATED = "dedicated" # 使用独立配置的识图模型


@dataclass
class SceneSnapshot:
    """
    结构化场景快照 - 用于程序化分析桌面状态
    
    包含多模态LLM分析后的结构化数据，支持下游事件检测和主动交互决策。
    """
    timestamp: datetime = field(default_factory=datetime.now)
    activity_type: str = "unknown"  # coding, browsing, meeting, media, gaming, reading, idle, etc.
    app_category: str = "unknown"   # dev, office, entertainment, system, communication, etc.
    has_error_ui: bool = False      # 是否检测到错误UI（弹窗、错误信息等）
    error_text: Optional[str] = None  # 错误文本内容
    is_idle: bool = False           # 用户是否处于空闲状态
    attention_level: float = 0.5    # 注意力水平 0.0~1.0（0表示完全分心，1表示高度专注）
    is_media_consumption: bool = False  # 是否在消费媒体（看视频、听音乐等）
    is_work_focus: bool = False     # 是否在工作专注状态
    notable_objects: List[str] = field(default_factory=list)  # 屏幕上值得注意的对象
    raw_description: str = ""       # 原始自然语言描述（兼容旧逻辑）
    confidence: float = 0.8         # 分析置信度 0.0~1.0
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "timestamp": self.timestamp.isoformat(),
            "activity_type": self.activity_type,
            "app_category": self.app_category,
            "has_error_ui": self.has_error_ui,
            "error_text": self.error_text,
            "is_idle": self.is_idle,
            "attention_level": self.attention_level,
            "is_media_consumption": self.is_media_consumption,
            "is_work_focus": self.is_work_focus,
            "notable_objects": self.notable_objects,
            "raw_description": self.raw_description,
            "confidence": self.confidence,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneSnapshot":
        """从字典创建实例"""
        try:
            timestamp_str = data.get("timestamp")
            if timestamp_str:
                timestamp = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
            else:
                timestamp = datetime.now()
        except:
            timestamp = datetime.now()
            
        return cls(
            timestamp=timestamp,
            activity_type=data.get("activity_type", "unknown"),
            app_category=data.get("app_category", "unknown"),
            has_error_ui=data.get("has_error_ui", False),
            error_text=data.get("error_text"),
            is_idle=data.get("is_idle", False),
            attention_level=float(data.get("attention_level", 0.5)),
            is_media_consumption=data.get("is_media_consumption", False),
            is_work_focus=data.get("is_work_focus", False),
            notable_objects=data.get("notable_objects", []),
            raw_description=data.get("raw_description", ""),
            confidence=float(data.get("confidence", 0.8)),
        )


@dataclass
class VisionAnalysisResult:
    """视觉分析结果"""
    success: bool
    description: str
    image_path: Optional[str] = None
    error_message: Optional[str] = None
    
    @classmethod
    def error(cls, message: str) -> "VisionAnalysisResult":
        """创建错误结果"""
        return cls(success=False, description="", error_message=message)
    
    @classmethod
    def success_result(cls, description: str, image_path: str) -> "VisionAnalysisResult":
        """创建成功结果"""
        return cls(success=True, description=description, image_path=image_path)


class VisionAnalyzer:
    """
    视觉分析器 - 使用多模态 LLM 分析图片
    
    该类封装了调用多模态 LLM 分析图片的逻辑，
    用于将截图转换为文本描述，供主 LLM 使用。
    
    支持三种识图模式：
    - auto: 自动检测，优先尝试对话模型
    - chat: 强制使用对话模型（需确保支持多模态）
    - dedicated: 使用独立配置的多模态模型
    """
    
    # 默认分析提示词
    DEFAULT_ANALYSIS_PROMPT = """请分析这张桌面截图，描述以下内容：

1. **当前活动**：用户正在进行什么操作？（如浏览网页、编写代码、看视频等）
2. **打开的应用**：屏幕上可见哪些应用程序窗口？
3. **屏幕布局**：窗口的大致布局是怎样的？
4. **关键内容**：如果有明显的文字、图片或重要信息，请简要描述

请用简洁的中文描述，不要过于详细，重点关注用户可能关心的内容。"""

    # 结构化分析提示词模板
    PROMPT_TEMPLATES = {
        "error_detect": """你是一个专业的桌面错误检测助手。请分析这张截图，识别任何错误、异常或问题。

请严格按照以下JSON格式返回结果，不要添加任何其他文字：
{
  "has_error_ui": true/false,
  "error_text": "错误文本内容（如果有的话）",
  "error_type": "错误类型（如：程序崩溃、编译错误、运行时错误、网络错误等）",
  "severity": "严重程度（low/medium/high/critical）",
  "suggested_action": "建议的解决措施",
  "raw_description": "错误现象的详细描述"
}

重点关注：
1. 错误弹窗、异常对话框
2. 编译/运行错误信息
3. 网络连接问题
4. 系统警告或通知
5. 程序无响应或卡死迹象""",

        "focus_eval": """你是一个工作效率分析助手。请分析这张截图，评估用户的工作专注度。

请严格按照以下JSON格式返回结果，不要添加任何其他文字：
{
  "activity_type": "主要活动类型（coding/browsing/meeting/media/gaming/reading/idle）",
  "app_category": "应用类别（dev/office/entertainment/system/communication）",
  "attention_level": 0.0-1.0的数值（0完全分心，1高度专注）,
  "is_work_focus": true/false,
  "is_media_consumption": true/false,
  "is_idle": true/false,
  "focus_indicators": ["专注度指标列表"],
  "distraction_indicators": ["分心指标列表"],
  "raw_description": "专注度分析的详细描述"
}

评估指标：
1. 活动窗口类型（IDE/浏览器/视频播放器等）
2. 窗口切换频率
3. 内容相关性（工作相关vs娱乐）
4. 时间段（工作时间vs休息时间）""",

        "companion": """你是一个友好的桌面陪伴助手。请分析这张截图，了解用户当前的状态，以便提供合适的陪伴。

请严格按照以下JSON格式返回结果，不要添加任何其他文字：
{
  "activity_type": "用户当前活动",
  "mood_hint": "用户可能的情绪状态",
  "social_context": "社交场景（独自工作/视频会议/与朋友聊天等）",
  "interests": ["可能感兴趣的方面"],
  "conversation_starters": ["合适的开场白建议"],
  "raw_description": "用户状态的详细描述"
}

关注点：
1. 用户正在进行的活动
2. 可能的情绪状态
3. 是否适合主动交流
4. 话题建议""",

        "safety": """你是一个隐私和安全检查助手。请分析这张截图，检查是否存在隐私泄露或安全风险。

请严格按照以下JSON格式返回结果，不要添加任何其他文字：
{
  "privacy_risks": ["隐私风险列表"],
  "security_warnings": ["安全警告列表"],
  "sensitive_content_detected": true/false,
  "content_types": ["检测到的内容类型"],
  "recommendations": ["安全建议"],
  "raw_description": "安全检查的详细描述"
}

检查内容：
1. 敏感信息显示（密码、个人信息等）
2. 不安全的网站或应用
3. 可疑的弹窗或通知
4. 屏幕共享时的隐私保护"""
    }

    def __init__(
        self,
        context,
        vision_mode: str = "auto",
        dedicated_provider_id: Optional[str] = None,
    ):
        """
        初始化视觉分析器
        
        Args:
            context: AstrBot 上下文对象，用于调用 LLM API
            vision_mode: 识图模式，可选值: "auto" | "chat" | "dedicated"
            dedicated_provider_id: 独立识图模型的 Provider ID（dedicated 模式必填）
        """
        self.context = context
        
        # 安全解析 vision_mode
        try:
            self.vision_mode = VisionMode(vision_mode)
        except ValueError:
            logger.warning(f"VisionAnalyzer: 无效的 vision_mode '{vision_mode}'，使用默认值 'auto'")
            self.vision_mode = VisionMode.AUTO
            
        self.dedicated_provider_id = dedicated_provider_id
        
        # 配置验证
        if self.vision_mode == VisionMode.DEDICATED and not dedicated_provider_id:
            logger.warning(
                "VisionAnalyzer: vision_mode 设置为 'dedicated'，"
                "但未配置 dedicated_provider_id，将降级为 'auto' 模式"
            )
            self.vision_mode = VisionMode.AUTO
            
        logger.info(f"VisionAnalyzer 初始化完成: mode={self.vision_mode.value}, "
                   f"dedicated_provider={dedicated_provider_id or '未配置'}")
    
    async def _get_vision_provider_id(self, umo: Optional[str] = None) -> tuple[Optional[str], bool]:
        """
        根据配置的识图模式获取实际使用的 Provider ID
        
        Args:
            umo: unified_message_origin，用于获取会话关联的 provider
        
        Returns:
            tuple[Optional[str], bool]: (provider_id, is_dedicated)
            - provider_id: 实际使用的 Provider ID，可能为 None
            - is_dedicated: 是否使用独立模型
        """
        if self.vision_mode == VisionMode.DEDICATED:
            return self.dedicated_provider_id, True
        
        # AUTO 或 CHAT 模式：使用对话模型
        try:
            chat_provider_id = await self.context.get_current_chat_provider_id(umo)
            return chat_provider_id, False
        except Exception as e:
            logger.error(f"获取对话模型 Provider ID 失败: {e}")
            return None, False
    
    async def analyze_image(
        self,
        image_path: str,
        prompt: Optional[str] = None,
        provider_id: Optional[str] = None,
        umo: Optional[str] = None,
    ) -> VisionAnalysisResult:
        """
        分析图片内容
        
        Args:
            image_path: 图片文件路径
            prompt: 自定义分析提示词，如果为 None 则使用默认提示词
            provider_id: 指定的 LLM provider ID（会覆盖 vision_mode 配置）
            umo: unified_message_origin，用于获取会话关联的 provider
        
        Returns:
            VisionAnalysisResult: 分析结果
        """
        # 检查文件是否存在
        if not os.path.exists(image_path):
            return VisionAnalysisResult.error(f"图片文件不存在: {image_path}")
        
        # 用于错误处理的标志
        is_dedicated = False
        
        try:
            # 确定使用的 Provider ID
            if provider_id:
                # 显式指定了 provider_id，直接使用
                actual_provider_id = provider_id
                is_dedicated = True
            else:
                # 根据 vision_mode 获取 provider_id
                actual_provider_id, is_dedicated = await self._get_vision_provider_id(umo)
            
            if not actual_provider_id:
                return VisionAnalysisResult.error(
                    "无法获取识图模型 Provider ID，请检查配置"
                )
            
            logger.info(f"使用 Provider '{actual_provider_id}' 进行视觉分析")
            
            # 使用自定义或默认提示词
            analysis_prompt = prompt or self.DEFAULT_ANALYSIS_PROMPT
            
            # 调用多模态 LLM
            llm_response = await self.context.llm_generate(
                chat_provider_id=actual_provider_id,
                prompt=analysis_prompt,
                image_urls=[image_path],
            )
            
            if llm_response and llm_response.completion_text:
                return VisionAnalysisResult.success_result(
                    description=llm_response.completion_text,
                    image_path=image_path
                )
            else:
                return VisionAnalysisResult.error("LLM 未返回有效的分析结果")
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"视觉分析失败: {error_msg}")
            
            # AUTO 模式下，如果对话模型不支持多模态，提供友好提示
            if self.vision_mode == VisionMode.AUTO and not is_dedicated:
                error_lower = error_msg.lower()
                if any(keyword in error_lower for keyword in ["image", "vision", "multimodal", "不支持"]):
                    return VisionAnalysisResult.error(
                        "当前对话模型不支持识图功能。\n"
                        "解决方案：请在插件配置中设置 vision_mode 为 'dedicated'，"
                        "并配置一个支持多模态的 LLM Provider（如 GPT-4o、Claude 3）"
                    )
            
            return VisionAnalysisResult.error(f"分析过程出错: {error_msg}")
    
    async def analyze_desktop_screenshot(
        self,
        image_path: str,
        umo: Optional[str] = None,
        prompt: Optional[str] = None,
    ) -> VisionAnalysisResult:
        """
        专门用于分析桌面截图的方法
        
        使用针对桌面截图优化的提示词进行分析。
        
        Args:
            image_path: 截图文件路径
            umo: unified_message_origin
            prompt: 自定义提示词，为空则使用默认桌面提示词
        
        Returns:
            VisionAnalysisResult: 分析结果
        """
        desktop_prompt = prompt or """你现在看到的是用户电脑桌面的实时截图。请简洁地描述：

1. 用户当前在做什么？
2. 屏幕上有哪些主要的应用或内容？
3. 有什么值得注意的信息吗？

请用口语化的方式回答，就像你真的能"看到"用户的屏幕一样。"""
        
        return await self.analyze_image(
            image_path=image_path,
            prompt=desktop_prompt,
            umo=umo,
        )
    
    async def structured_analyze(
        self,
        image_path: str,
        scene_type: str = "companion",
        umo: Optional[str] = None,
    ) -> tuple[SceneSnapshot, VisionAnalysisResult]:
        """
        结构化分析桌面截图
        
        使用对应的提示词模板进行分析，返回结构化的SceneSnapshot。
        
        Args:
            image_path: 截图文件路径
            scene_type: 场景类型，可选值: "error_detect" | "focus_eval" | "companion" | "safety"
            umo: unified_message_origin
        
        Returns:
            tuple[SceneSnapshot, VisionAnalysisResult]: 结构化快照和原始分析结果
        """
        # 获取对应的提示词模板
        prompt_template = self.PROMPT_TEMPLATES.get(scene_type)
        if not prompt_template:
            logger.warning(f"未找到场景类型 '{scene_type}' 的提示词模板，使用默认模板")
            # 回退到默认分析
            result = await self.analyze_desktop_screenshot(image_path, umo)
            if result.success:
                snapshot = SceneSnapshot(
                    raw_description=result.description,
                    confidence=0.6
                )
                return snapshot, result
            else:
                # 创建空的快照
                snapshot = SceneSnapshot(
                    raw_description=f"分析失败: {result.error_message}",
                    confidence=0.0
                )
                return snapshot, result
        
        # 使用结构化提示词进行分析
        result = await self.analyze_image(
            image_path=image_path,
            prompt=prompt_template,
            umo=umo,
        )
        
        if not result.success:
            # 分析失败，创建空的快照
            snapshot = SceneSnapshot(
                raw_description=f"分析失败: {result.error_message}",
                confidence=0.0
            )
            return snapshot, result
        
        # 解析JSON响应
        snapshot = self._parse_json_response(result.description, scene_type)
        snapshot.raw_description = result.description
        snapshot.timestamp = datetime.now()
        
        logger.info(f"结构化分析完成: scene_type={scene_type}, activity={snapshot.activity_type}, "
                   f"error={snapshot.has_error_ui}, attention={snapshot.attention_level:.2f}")
        
        return snapshot, result
    
    def _parse_json_response(self, response_text: str, scene_type: str) -> SceneSnapshot:
        """
        解析LLM返回的JSON响应为SceneSnapshot
        
        Args:
            response_text: LLM返回的文本
            scene_type: 场景类型
        
        Returns:
            SceneSnapshot: 解析后的结构化快照
        """
        try:
            # 尝试提取JSON部分（LLM可能返回额外文本）
            json_start = response_text.find('{')
            json_end = response_text.rfind('}') + 1
            
            if json_start == -1 or json_end == 0:
                logger.warning(f"未在响应中找到JSON格式，场景类型: {scene_type}")
                return SceneSnapshot(raw_description=response_text, confidence=0.3)
            
            json_str = response_text[json_start:json_end]
            data = json.loads(json_str)
            
            # 根据场景类型解析不同的字段
            if scene_type == "error_detect":
                return SceneSnapshot(
                    has_error_ui=data.get("has_error_ui", False),
                    error_text=data.get("error_text"),
                    raw_description=data.get("raw_description", response_text),
                    confidence=0.8,
                )
            
            elif scene_type == "focus_eval":
                return SceneSnapshot(
                    activity_type=data.get("activity_type", "unknown"),
                    app_category=data.get("app_category", "unknown"),
                    attention_level=float(data.get("attention_level", 0.5)),
                    is_work_focus=data.get("is_work_focus", False),
                    is_media_consumption=data.get("is_media_consumption", False),
                    is_idle=data.get("is_idle", False),
                    raw_description=data.get("raw_description", response_text),
                    confidence=0.8,
                )
            
            elif scene_type == "companion":
                return SceneSnapshot(
                    activity_type=data.get("activity_type", "unknown"),
                    raw_description=data.get("raw_description", response_text),
                    confidence=0.7,
                )
            
            elif scene_type == "safety":
                return SceneSnapshot(
                    raw_description=data.get("raw_description", response_text),
                    confidence=0.7,
                )
            
            else:
                # 未知场景类型，使用通用解析
                return SceneSnapshot(
                    raw_description=data.get("raw_description", response_text),
                    confidence=0.5,
                )
                
        except json.JSONDecodeError as e:
            logger.warning(f"JSON解析失败: {e}，场景类型: {scene_type}")
            return SceneSnapshot(raw_description=response_text, confidence=0.2)
        except Exception as e:
            logger.error(f"解析响应时出错: {e}")
            return SceneSnapshot(raw_description=response_text, confidence=0.1)
    
    def encode_image_base64(self, image_path: str) -> Optional[str]:
        """
        将图片编码为 base64 字符串
        
        Args:
            image_path: 图片文件路径
        
        Returns:
            base64 编码的图片字符串，失败返回 None
        """
        try:
            with open(image_path, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")
        except Exception as e:
            logger.error(f"图片编码失败: {e}")
            return None
