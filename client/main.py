import datetime
import json
import math
import os
import random
import sys
import time
import re
from typing import Any, Dict, Optional, List
from urllib.parse import unquote
import argparse
import shutil
import winreg

# 台词↔日文语音：场景化语音映射加载模块
import jp_voice

# 兼容 Anaconda Python 无法写入 site-packages 的情况：回退到系统 Python 安装的包
import site
if not os.path.isdir(site.getusersitepackages()):
    # 通用回退：按当前用户动态解析（不再硬编码用户名）
    _up = os.environ.get("USERPROFILE", "")
    if _up:
        for _cand in (
            os.path.join(_up, "AppData", "Roaming", "Python", "Python313", "site-packages"),
            os.path.join(_up, ".astrbot", "data", "site-packages"),
        ):
            if os.path.isdir(_cand):
                site.addsitedir(_cand)

# 将桌面临时依赖目录添加到搜索路径
_deps_path = os.path.join(os.environ.get("USERPROFILE", ""), "Desktop", "py_deps")
if os.path.isdir(_deps_path):
    sys.path.insert(0, _deps_path)

import queue
import logging
import functools
import concurrent.futures
import traceback

# FileHandler 预导入，避免首次发送时阻塞
try:
    from file_handler import FileHandler
except Exception:
    FileHandler = None

# 精进功能数据层：日程 / 主动陪伴
from smart_features import ScheduleManager, ProactiveEngine, parse_schedule_nl

# ── 日志配置 ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    filename=os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet.log"),
    filemode="a",
    encoding="utf-8",
)
logger = logging.getLogger("DesktopPet")

# ── 配置管理 ──
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pet_config.json")

# 缩放档位：80% / 90% / 100% / 110% / 120%
SCALE_STEPS = [0.8, 0.9, 1.0, 1.1, 1.2]
SCALE_LABELS = {0.8: "80%", 0.9: "90%", 1.0: "100%", 1.1: "110%", 1.2: "120%"}

# ── 主题系统 ──
THEME_PRESETS = {
    "dark": {
        "name": "深空",           # 墨蓝中性 + 靛青主色（调和梯度）
        "tint": (26, 18, 168, 20),   # ABGR 亚克力着色（偏蓝墨）
        "bg": "rgba(18, 20, 28, 0.55)",
        "bg_secondary": "rgba(32, 36, 48, 0.68)",
        "fg": "#F3F6FC",
        "fg_muted": "rgba(233, 240, 252, 0.56)",
        "accent": "#3B82F6",
        "accent_hover": "#60A5FA",
        "accent_glow": "rgba(59, 130, 246, 0.40)",
        "gradient_start": "#3B82F6",
        "gradient_end": "#7DB3FF",
        "user_bubble": "rgba(52, 74, 130, 0.96)",
        "user_bubble_2": "rgba(38, 56, 100, 0.96)",
        "user_fg": "#ffffff",
        "bot_bubble": "rgba(233, 240, 252, 0.12)",
        "bot_bubble_border": "rgba(233, 240, 252, 0.20)",
        "border": "rgba(233, 240, 252, 0.14)",
        "border_light": "rgba(233, 240, 252, 0.28)",
        "scrollbar": "rgba(233, 240, 252, 0.12)",
        "scrollbar_handle": "rgba(233, 240, 252, 0.38)",
        "shadow": "rgba(4, 8, 22, 0.55)",
        "card_bg": "rgba(34, 38, 50, 0.92)",
        "status_running_bg": "rgba(48, 40, 14, 0.85)",
        "status_running_fg": "#F5C542",
        "status_running_border": "rgba(245, 197, 66, 0.5)",
        "status_done_bg": "rgba(14, 50, 36, 0.85)",
        "status_done_fg": "#34D399",
        "status_done_border": "rgba(52, 211, 153, 0.5)",
        "input_bg": "rgba(233, 240, 252, 0.13)",
        "input_border": "rgba(233, 240, 252, 0.22)",
        "btn_primary": "rgba(59, 130, 246, 0.92)",
        "btn_primary_hover": "rgba(96, 165, 250, 0.95)",
        "btn_secondary": "rgba(233, 240, 252, 0.16)",
        "btn_secondary_hover": "rgba(233, 240, 252, 0.26)",
        "btn_danger": "#DC4C5A",
        "btn_danger_hover": "#E86B77",
        "code_bg": "rgba(6, 10, 22, 0.45)",
        "code_fg": "#F5C542",
        "code_inline_bg": "rgba(6, 10, 22, 0.40)",
        "code_inline_fg": "#FFB84D",
        "connected": "#34D399",
        "disconnected": "#F0525F",
    },
    "light": {
        "name": "云白",           # 冷调云白 + 靛蓝主色
        "tint": (244, 246, 250, 246),
        "bg": "rgba(244, 246, 250, 0.50)",
        "bg_secondary": "rgba(255, 255, 255, 0.66)",
        "fg": "#171A21",
        "fg_muted": "rgba(50, 57, 74, 0.62)",
        "accent": "#2563EB",
        "accent_hover": "#3B82F6",
        "accent_glow": "rgba(37, 99, 235, 0.26)",
        "gradient_start": "#2563EB",
        "gradient_end": "#3B82F6",
        "user_bubble": "rgba(48, 62, 102, 0.97)",
        "user_bubble_2": "rgba(34, 46, 78, 0.97)",
        "user_fg": "#ffffff",
        "bot_bubble": "rgba(255, 255, 255, 0.66)",
        "bot_bubble_border": "rgba(15, 23, 42, 0.08)",
        "border": "rgba(15, 23, 42, 0.10)",
        "border_light": "rgba(255, 255, 255, 0.95)",
        "scrollbar": "rgba(15, 23, 42, 0.08)",
        "scrollbar_handle": "rgba(50, 57, 74, 0.30)",
        "shadow": "rgba(10, 18, 40, 0.20)",
        "card_bg": "rgba(255, 255, 255, 0.90)",
        "status_running_bg": "rgba(255, 246, 214, 0.92)",
        "status_running_fg": "#9A5B00",
        "status_running_border": "rgba(154, 91, 0, 0.35)",
        "status_done_bg": "rgba(220, 250, 234, 0.92)",
        "status_done_fg": "#15803D",
        "status_done_border": "rgba(21, 128, 61, 0.35)",
        "input_bg": "rgba(255, 255, 255, 0.80)",
        "input_border": "rgba(15, 23, 42, 0.12)",
        "btn_primary": "rgba(37, 99, 235, 0.93)",
        "btn_primary_hover": "rgba(59, 130, 246, 0.95)",
        "btn_secondary": "rgba(50, 57, 74, 0.14)",
        "btn_secondary_hover": "rgba(50, 57, 74, 0.22)",
        "btn_danger": "#D13B4A",
        "btn_danger_hover": "#E05664",
        "code_bg": "rgba(238, 241, 248, 0.95)",
        "code_fg": "#854D0E",
        "code_inline_bg": "rgba(238, 241, 248, 0.95)",
        "code_inline_fg": "#B45309",
        "connected": "#16A34A",
        "disconnected": "#DC2626",
    },
    "aurora": {
        "name": "霓虹",           # 深海墨蓝 + 青金主色
        "tint": (30, 14, 168, 8),
        "bg": "rgba(10, 18, 34, 0.55)",
        "bg_secondary": "rgba(22, 34, 58, 0.68)",
        "fg": "#EAF4FF",
        "fg_muted": "rgba(198, 232, 255, 0.56)",
        "accent": "#22B8F0",
        "accent_hover": "#5AD1FF",
        "accent_glow": "rgba(34, 184, 240, 0.40)",
        "gradient_start": "#22B8F0",
        "gradient_end": "#6ECBFF",
        "user_bubble": "rgba(30, 86, 124, 0.96)",
        "user_bubble_2": "rgba(20, 64, 96, 0.96)",
        "user_fg": "#ffffff",
        "bot_bubble": "rgba(170, 226, 255, 0.13)",
        "bot_bubble_border": "rgba(170, 226, 255, 0.24)",
        "border": "rgba(170, 226, 255, 0.16)",
        "border_light": "rgba(190, 236, 255, 0.35)",
        "scrollbar": "rgba(170, 226, 255, 0.14)",
        "scrollbar_handle": "rgba(170, 226, 255, 0.40)",
        "shadow": "rgba(2, 24, 52, 0.50)",
        "card_bg": "rgba(24, 36, 60, 0.92)",
        "status_running_bg": "rgba(48, 42, 14, 0.85)",
        "status_running_fg": "#F5C542",
        "status_running_border": "rgba(245, 197, 66, 0.5)",
        "status_done_bg": "rgba(12, 50, 38, 0.85)",
        "status_done_fg": "#34D399",
        "status_done_border": "rgba(52, 211, 153, 0.5)",
        "input_bg": "rgba(170, 226, 255, 0.12)",
        "input_border": "rgba(170, 226, 255, 0.25)",
        "btn_primary": "rgba(20, 150, 210, 0.92)",
        "btn_primary_hover": "rgba(34, 184, 240, 0.95)",
        "btn_secondary": "rgba(170, 226, 255, 0.14)",
        "btn_secondary_hover": "rgba(170, 226, 255, 0.24)",
        "btn_danger": "#E05266",
        "btn_danger_hover": "#EE7082",
        "code_bg": "rgba(4, 16, 34, 0.55)",
        "code_fg": "#5AD8FF",
        "code_inline_bg": "rgba(4, 30, 56, 0.5)",
        "code_inline_fg": "#8AE6FF",
        "connected": "#34D399",
        "disconnected": "#F0525F",
    },
    "sakura": {
        "name": "粉樱",           # 暖调米白 + 绛樱主色
        "tint": (244, 240, 250, 253),
        "bg": "rgba(253, 243, 248, 0.50)",
        "bg_secondary": "rgba(255, 251, 253, 0.66)",
        "fg": "#441D2E",
        "fg_muted": "rgba(118, 56, 82, 0.62)",
        "accent": "#E11D4E",
        "accent_hover": "#F43F6B",
        "accent_glow": "rgba(225, 29, 78, 0.26)",
        "gradient_start": "#E11D4E",
        "gradient_end": "#F43F6B",
        "user_bubble": "rgba(186, 82, 118, 0.95)",
        "user_bubble_2": "rgba(150, 60, 96, 0.95)",
        "user_fg": "#ffffff",
        "bot_bubble": "rgba(255, 255, 255, 0.58)",
        "bot_bubble_border": "rgba(233, 150, 180, 0.85)",
        "border": "rgba(170, 50, 92, 0.14)",
        "border_light": "rgba(255, 255, 255, 0.95)",
        "scrollbar": "rgba(170, 50, 92, 0.12)",
        "scrollbar_handle": "rgba(170, 50, 92, 0.32)",
        "shadow": "rgba(150, 30, 76, 0.18)",
        "card_bg": "rgba(255, 250, 252, 0.92)",
        "status_running_bg": "rgba(255, 246, 214, 0.92)",
        "status_running_fg": "#9A5B00",
        "status_running_border": "rgba(154, 91, 0, 0.35)",
        "status_done_bg": "rgba(220, 250, 234, 0.92)",
        "status_done_fg": "#15803D",
        "status_done_border": "rgba(21, 128, 61, 0.35)",
        "input_bg": "rgba(255, 255, 255, 0.82)",
        "input_border": "rgba(170, 50, 92, 0.18)",
        "btn_primary": "rgba(225, 29, 78, 0.92)",
        "btn_primary_hover": "rgba(244, 63, 107, 0.95)",
        "btn_secondary": "rgba(170, 50, 92, 0.12)",
        "btn_secondary_hover": "rgba(170, 50, 92, 0.20)",
        "btn_danger": "#C81E45",
        "btn_danger_hover": "#DC3B5E",
        "code_bg": "rgba(252, 236, 242, 0.95)",
        "code_fg": "#9F1239",
        "code_inline_bg": "rgba(252, 236, 242, 0.95)",
        "code_inline_fg": "#BE123C",
        "connected": "#16A34A",
        "disconnected": "#DC2626",
    },
}

DEFAULT_THEME = "light"

def load_config() -> dict:
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


DEFAULT_POMODORO_CONFIG = {
    "work_min": 25,
    "break_min": 5,
    "completed_count": 0,
    "state": "idle",  # idle, work, break
    "remaining_seconds": 0,
}

def save_config(cfg: dict) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存配置失败: {e}")

def get_current_theme() -> str:
    cfg = load_config()
    return cfg.get("theme", DEFAULT_THEME)

# ── 设计常量（统一圆角 / 阴影 / 字体）──
RADIUS_CARD = 12        # 控件圆角（按钮 / 输入框 / 小卡片）
RADIUS_BUBBLE = 16      # 消息气泡大圆角
RADIUS_BUBBLE_SIDE = 6  # 气泡靠发送侧的小圆角（不对称收尾，替代尖角尾巴）
RADIUS_CAPSULE = 20     # 胶囊按钮 / 胶囊标签（Qt 忽略 > min(w,h)/2 的圆角，用 20 保证）
RADIUS_PILL = 12        # 状态标签圆角：Qt 会忽略超过 min(w,h)/2 的圆角而退化为直角，999 实测失效，统一 12px 与气泡一致

# 玻璃面不透明度两档：可读面（文字压得住）/ 幽灵面（次要底）；禁用态单独一档
GLASS_ALPHA_SOLID = 190
GLASS_ALPHA_GHOST = 150
GLASS_ALPHA_DISABLED = 110
SHADOW_BLUR = 32        # 柔和阴影模糊（0 8px 32px）
SHADOW_OFFSET_Y = 8     # 阴影下偏移
SHADOW_ALPHA = 0.10     # 阴影浓度 10% 黑
FONT_STACK = '"Segoe UI", "Microsoft YaHei UI", "PingFang SC", "Roboto", sans-serif'

# ── 字号层级（5 级）：标题 / 分区 / 正文 / 辅助 / 代码 ──
FONT_TITLE = 24       # 主标题（气泡标题、面板标题）
FONT_SECTION = 20     # 分区标题（卡片头、对话框标题）
FONT_BODY = 19        # 正文与控件默认字号
FONT_CAPTION = 16     # 辅助文字（标签、副标题、状态药丸）
FONT_CODE = 15        # 代码块与行内代码

# 各主题可选键的兜底值（QSS 生成时统一使用，保证无 KeyError）
_THEME_DEFAULTS = {
    "btn_danger": "#d64545",
    "btn_danger_hover": "#e06060",
    "card_bg": "#ffffff",
}

def get_theme_colors() -> dict:
    theme_name = get_current_theme()
    base = THEME_PRESETS.get(theme_name, THEME_PRESETS[DEFAULT_THEME])
    return {**_THEME_DEFAULTS, **base}


# ── Windows 亚克力毛玻璃（iOS Liquid Glass 效果）──
def _apply_win_accent(widget, enable: bool = True) -> None:
    """通过 SetWindowCompositionAttribute 为窗口启用系统级亚克力模糊。

    在 Win10/11 上提供真正的毛玻璃背景（模糊桌面 + 着色），
    配合半透明 QSS 即得到 iOS 26 Liquid Glass 观感。
    """
    try:
        import ctypes

        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [
                ("AccentState", ctypes.c_int),
                ("AccentFlags", ctypes.c_int),
                ("GradientColor", ctypes.c_uint),
                ("AnimationId", ctypes.c_int),
            ]

        class WINCOMPATTRDATA(ctypes.Structure):
            _fields_ = [
                ("Attribute", ctypes.c_int),
                ("DataSize", ctypes.c_ulong),
                ("Data", ctypes.c_void_p),
            ]

        if not widget.winId():
            return
        hwnd = int(widget.winId())
        c = get_theme_colors()
        tint = c.get("tint", (168, 18, 18, 20))  # (A, R, G, B)
        accent = ACCENT_POLICY()
        accent.AccentState = 3 if enable else 0  # 3 = ACCENT_ENABLE_ACRYLICBLURBEHIND
        accent.AccentFlags = 2
        a, r, g, b = tint
        accent.GradientColor = (a << 24) | (b << 16) | (g << 8) | r
        data = WINCOMPATTRDATA()
        data.Attribute = 19  # WCA_ACCENT_POLICY
        data.DataSize = ctypes.sizeof(accent)
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
    except Exception:
        pass


def _hex_to_qcolor(value):
    """将 '#RRGGBB' / 'rgba(r,g,b,a)' 字符串转为 QColor（已为 QColor 时原样返回）"""
    if isinstance(value, QColor):
        return value
    value = str(value).strip()
    if value.startswith("#"):
        return QColor(value)
    m = re.match(r"rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?\)", value)
    if m:
        r, g, b = int(float(m.group(1))), int(float(m.group(2))), int(float(m.group(3)))
        a = int(float(m.group(4)) * 255) if m.group(4) else 255
        return QColor(r, g, b, a)
    return QColor(value)


def make_rounded_pixmap(pixmap, size: int, radius: int | None = None):
    """将图片裁剪为圆角（透明角）缩略图；radius 默认取圆形（size//2）"""
    try:
        if pixmap.isNull():
            return QPixmap()
        if radius is None:
            radius = size // 2
        radius = max(1, min(int(radius), size // 2))
        rounded = QPixmap(size, size)
        rounded.fill(Qt.transparent)
        p = QPainter(rounded)
        p.setRenderHint(QPainter.Antialiasing, True)
        path = QPainterPath()
        path.addRoundedRect(0, 0, size, size, radius, radius)
        p.setClipPath(path)
        p.drawPixmap(0, 0, pixmap.scaled(size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        p.end()
        return rounded
    except Exception:
        return QPixmap(pixmap)


def _disable_dwm_transitions(widget) -> None:
    """禁用窗口的 DWM 过渡动画，消除拖动/移动时的黑底闪烁"""
    try:
        import ctypes
        hwnd = int(widget.winId())
        if not hwnd:
            return
        # DWMWA_TRANSITIONS_FORCEDISABLED = 3
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 3, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


# ── iOS 26 Liquid Glass 卡片绘制 ──
# 窗口四周预留的透明边距，用于绘制外阴影与玻璃高光（避免 QGraphicsEffect 叠加崩溃）
GLASS_MARGIN = 26
GLASS_RADIUS = 16          # 玻璃面板圆角（卡片 16 / 控件 12 / 胶囊全圆）


def _clear_bubble_effect(bubble) -> None:
    """淡入动画结束后移除 QGraphicsOpacityEffect，避免特效长期驻留拖慢重绘；
    若气泡持有柔和投影（_shadow_effect）则恢复之（投影在动画期间被临时替换）"""
    try:
        if not sip.isdeleted(bubble):
            bubble.setGraphicsEffect(None)
            shadow = getattr(bubble, "_shadow_effect", None)
            if shadow is not None:
                bubble.setGraphicsEffect(shadow)
    except Exception:
        pass


# ── 玻璃微噪点纹理（进程内生成一次，平铺进玻璃卡面模拟真实玻璃颗粒） ──
_GLASS_NOISE = None  # QPixmap，首次使用时生成


def _glass_noise() -> "QPixmap":
    global _GLASS_NOISE
    if _GLASS_NOISE is None:
        import random as _rnd
        n, img = 48, QImage(48, 48, QImage.Format_ARGB32)
        for y in range(n):
            for x in range(n):
                a = _rnd.randint(0, 26)
                img.setPixel(x, y, qRgba(255, 255, 255, a))
        _GLASS_NOISE = QPixmap.fromImage(img)
    return _GLASS_NOISE


def _theme_rgba(key: str, alpha: int) -> str:
    """主题色 + 固定 alpha → QSS rgba(...)，用于软悬停/选中面"""
    col = _hex_to_qcolor(get_theme_colors().get(key, "#888888"))
    return f"rgba({col.red()}, {col.green()}, {col.blue()}, {max(0, min(255, int(alpha)))})"


def paint_liquid_glass(painter, rect, radius=GLASS_RADIUS, tier: str = "full") -> None:
    """在给定矩形内绘制 iOS 26 Liquid Glass 卡片。

    tier 分层（一屏只该有一个最亮的主角）：
      full  — 气泡主舞台：外阴影 + 渐变 + 高光 + 扫掠 + 噪点 全开
      panel — 设置/菜单等次级面：去对角扫掠、外阴影更轻、噪点更淡
    调用方需为 WA_TranslucentBackground 窗口，并在 paintEvent 中调用。
    """
    try:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)
        c = get_theme_colors()
        is_full = tier != "panel"
        # 1) 柔和外阴影：向下偏移的多层半透明圆角，模拟真实投影
        shadow = _hex_to_qcolor(c.get("shadow", "rgba(0,0,0,0.45)"))
        layers = 5 if is_full else 3
        alpha_k = 0.10 if is_full else 0.06
        for i in range(layers, 0, -1):
            spread = i * 2
            col = QColor(shadow)
            col.setAlphaF(max(0.0, alpha_k - i * 0.012))
            painter.setBrush(col)
            painter.setPen(Qt.NoPen)
            sr = rect.adjusted(-spread, -spread + 6, spread, spread + 8)
            painter.drawRoundedRect(sr, radius + spread, radius + spread)
        # 2) 玻璃本体：顶部高光 -> 主体 -> 底部微深 的垂直渐变
        top = _hex_to_qcolor(c.get("bg_secondary", c["bg"]))
        base = _hex_to_qcolor(c["bg"])
        grad = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        hl = QColor(top)
        hl.setAlpha(min(255, int(hl.alpha() * 1.2) + 6))
        grad.setColorAt(0.0, hl)
        grad.setColorAt(0.5, top)
        grad.setColorAt(1.0, base)
        painter.setBrush(grad)
        pen = QPen(_hex_to_qcolor(c["border"]))
        pen.setWidth(1)
        painter.setPen(pen)
        painter.drawRoundedRect(rect, radius, radius)
        # 3) 顶部高光描边（Liquid 边缘提亮）
        light = _hex_to_qcolor(c.get("border_light", "rgba(255,255,255,0.35)"))
        painter.setPen(QPen(light, 1))
        painter.drawLine(QPointF(rect.left() + radius // 2, rect.top() + 1),
                         QPointF(rect.right() - radius // 2, rect.top() + 1))
        # 4) 底部内阴影，增加玻璃层次感
        body = QPainterPath()
        body.addRoundedRect(rect, radius, radius)
        painter.save()
        painter.setClipPath(body)
        bottom_grad = QLinearGradient(QPointF(0, rect.bottom()),
                                      QPointF(0, rect.bottom() - 44))
        bottom_grad.setColorAt(0.0, QColor(0, 0, 0, 26 if is_full else 16))
        bottom_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(bottom_grad)
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(rect, radius, radius)
        # 5) 对角高光扫掠：仅 full（主角专属反光带）
        if is_full:
            sweep = QLinearGradient(rect.topLeft(), rect.bottomRight())
            sweep.setColorAt(0.0, QColor(255, 255, 255, 44))
            sweep.setColorAt(0.22, QColor(255, 255, 255, 14))
            sweep.setColorAt(0.48, QColor(255, 255, 255, 0))
            sweep.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setBrush(sweep)
            painter.drawRoundedRect(rect, radius, radius)
        # 6) 微噪点颗粒（真实玻璃质感，透明度极低不干扰内容）
        painter.setOpacity(0.045 if is_full else 0.022)
        painter.drawTiledPixmap(rect, _glass_noise())
        painter.setOpacity(1.0)
        painter.restore()
        painter.restore()
    except Exception:
        try:
            painter.restore()
        except Exception:
            pass

from PyQt5.QtCore import (
    QAbstractAnimation,
    QEasingCurve,
    QPoint,
    QPointF,
    QPropertyAnimation,
    QRect,
    QRectF,
    QSize,
    Qt,
    QTimer,
    QVariantAnimation,
    pyqtSignal,
    QObject,
    QUrl,
    QUrlQuery,
    QEvent,
)
from PyQt5.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    qRgba,
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PyQt5.QtWebSockets import QWebSocket
from PyQt5 import sip
from PyQt5.QtWidgets import (
    QAction,
    QApplication,
    QCheckBox,
    QButtonGroup,
    QComboBox,
    QDialog,
    QFrame,
    QGraphicsOpacityEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
    QFileDialog,
    QSizePolicy,
    QGraphicsDropShadowEffect,
    QTextBrowser,
    QGraphicsBlurEffect,
    QGridLayout,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
)

# ── 番茄钟定时器 ──
class PomodoroTimer(QObject):
    """番茄钟：工作/休息倒计时、语音提醒、完成计数持久化"""
    tick_signal = pyqtSignal(int, str)  # (剩余秒数, 模式)
    finished_signal = pyqtSignal(str)   # 完成时的模式

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._on_tick)

        self._work_minutes = 25
        self._break_minutes = 5
        self._remaining_seconds = 0
        self._mode = "idle"  # "work" / "break" / "idle"
        self._paused = False
        self._completed_count = 0

    def load_config(self, cfg: dict) -> None:
        self._work_minutes = cfg.get("pomodoro_work_minutes", 25)
        self._break_minutes = cfg.get("pomodoro_break_minutes", 5)
        self._completed_count = cfg.get("pomodoro_completed_today", 0)

    def save_config(self, cfg: dict) -> None:
        cfg["pomodoro_work_minutes"] = self._work_minutes
        cfg["pomodoro_break_minutes"] = self._break_minutes
        cfg["pomodoro_completed_today"] = self._completed_count

    def set_work_minutes(self, minutes: int) -> None:
        self._work_minutes = max(1, minutes)

    def set_break_minutes(self, minutes: int) -> None:
        self._break_minutes = max(1, minutes)

    def start_work(self) -> None:
        self._mode = "work"
        self._remaining_seconds = self._work_minutes * 60
        self._paused = False
        self._timer.start()
        self.tick_signal.emit(self._remaining_seconds, "work")

    def start_break(self) -> None:
        self._mode = "break"
        self._remaining_seconds = self._break_minutes * 60
        self._paused = False
        self._timer.start()
        self.tick_signal.emit(self._remaining_seconds, "break")

    def pause(self) -> None:
        if self._mode != "idle" and not self._paused:
            self._paused = True
            self._timer.stop()

    def resume(self) -> None:
        if self._mode != "idle" and self._paused:
            self._paused = False
            self._timer.start()

    def reset(self) -> None:
        self._timer.stop()
        self._mode = "idle"
        self._remaining_seconds = 0
        self._paused = False
        self.tick_signal.emit(0, "idle")

    def _on_tick(self) -> None:
        self._remaining_seconds -= 1
        if self._remaining_seconds <= 0:
            self._timer.stop()
            if self._mode == "work":
                self._completed_count += 1
                self.finished_signal.emit("work")
                # 自动开始休息
                self.start_break()
            else:
                self.finished_signal.emit("break")
                self._mode = "idle"
                self._remaining_seconds = 0
                self.tick_signal.emit(0, "idle")
        else:
            self.tick_signal.emit(self._remaining_seconds, self._mode)

    def get_remaining_seconds(self) -> int:
        return self._remaining_seconds

    def get_mode(self) -> str:
        return self._mode

    def is_running(self) -> bool:
        return self._mode != "idle" and not self._paused

    def is_paused(self) -> bool:
        return self._mode != "idle" and self._paused

    def get_completed_count(self) -> int:
        return self._completed_count

    def format_time(self, seconds: int) -> str:
        m = seconds // 60
        s = seconds % 60
        return f"{m:02d}:{s:02d}"


# ── 后台线程回主线程的自定义事件：桌面状态上报 ──
class _DesktopStateEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, title: str, process: str, screenshot_base64: str = None) -> None:
        super().__init__(self.EVENT_TYPE)
        self.title = title
        self.process = process
        self.screenshot_base64 = screenshot_base64

# ── 主题感知样式工具 ──
class ChatInput(QPlainTextEdit):
    """多行输入区：回车发送、Shift+回车换行、随内容自动长高（44→160px）"""
    send_requested = pyqtSignal()

    _MIN_H = 44
    _MAX_H = 300

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("composerInput")
        self.setPlaceholderText("输入要对桌宠说的话...")
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(self._MIN_H)
        self.textChanged.connect(self._auto_grow)

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        # 中文输入法组字中，回车用于确认候选词，不触发发送
        try:
            from PyQt5.QtGui import QGuiApplication
            if QGuiApplication.inputMethod().isComposing():
                super().keyPressEvent(event)
                return
        except Exception:
            pass
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and \
                not (event.modifiers() & Qt.ShiftModifier):
            self.send_requested.emit()
            return
        super().keyPressEvent(event)

    def _auto_grow(self) -> None:
        """内容变多时增高输入区（超过上限出内部滚动条）"""
        try:
            # documentLayout 反映换行后的真实像素高度；再与逐行估算取大，
            # 规避快速输入时布局尚未刷新导致的增长滞后
            lay = self.document().documentLayout()
            doc_h = int(lay.documentSize().height())
            fm = self.fontMetrics()
            lines = self.document().blockCount()
            est_h = lines * fm.height()
            h = max(self._MIN_H, min(self._MAX_H, max(doc_h, est_h) + 16))
            if abs(h - self.height()) > 2:
                self.setFixedHeight(h)
        except Exception:
            pass


def theme_stylesheet() -> str:
    """生成全局主题样式表（iOS 26 Liquid Glass）：
    5 级字号体系（标题23/分区19/正文17/辅助15/代码14）· 卡片16 圆角 · 控件12 圆角 · primary/secondary/danger 按钮"""
    c = get_theme_colors()
    return f"""
    #chatBubble, #secretaryPanel {{
        /* 玻璃卡片由 paintEvent 自绘（避免 QGraphicsEffect + windowOpacity 崩溃） */
        background: transparent;
        border: none;
    }}
    #chatBubble QWidget#historyWidget, #secretaryPanel QWidget#gridWidget {{
        background: transparent;
    }}
    QFrame#headerSeparator {{
        background: {c["border"]};
        border: none;
        max-height: 1px;
    }}
    QLabel {{
        color: {c["fg"]};
        font-size: {FONT_BODY}px;
        font-family: {FONT_STACK};
    }}
    QLabel#panelTitle {{
        font-size: {FONT_TITLE}px;
        font-weight: 600;
    }}
    QLineEdit {{
        color: {c["fg"]};
        background: {c["input_bg"]};
        border: 1px solid {c["input_border"]};
        /* 注意：QLineEdit 上 999px 超大圆角会被 Qt 忽略而显示为直角，用 20px 保证圆角 */
        border-radius: {RADIUS_CAPSULE}px;
        padding: 10px 16px;
        font-size: 20px;
        selection-background-color: {c["accent_glow"]};
    }}
    QLineEdit:focus {{
        border: 1px solid {c["accent"]};
        background: {c["input_bg"]};
    }}
    QLineEdit::placeholder {{ color: {c["fg_muted"]}; }}
    QPushButton {{
        color: #ffffff;
        background: {c["btn_primary"]};
        /* border:none 时 QPushButton 会忽略 border-radius（实测成直角）；
           用与背景同色的边框触发圆角裁剪，视觉上无痕 */
        border: 1px solid {c["btn_primary"]};
        /* 圆角必须 ≤ min(宽,高)/2，否则 Qt 退化为直角（实测 20px 在 33px 高按钮上失效）；
           统一用 RADIUS_CARD 与消息气泡一致 */
        border-radius: {RADIUS_CARD}px;
        padding: 9px 20px;
        font-size: {FONT_BODY}px;
        font-weight: 600;
    }}
    QPushButton:hover {{ background: {c["btn_primary_hover"]}; }}
    QPushButton:pressed {{ background: {c["accent"]}; }}
    QPushButton:disabled {{ background: {c["btn_secondary"]}; color: {c["fg_muted"]}; }}
    QPushButton[primary="true"] {{ /* primary：实心主色（默认同款，显式标记） */
        color: #ffffff;
        background: {c["btn_primary"]};
        border: 1px solid {c["btn_primary"]};
        border-radius: {RADIUS_CARD}px;
    }}
    QPushButton[primary="true"]:hover {{ background: {c["btn_primary_hover"]}; }}
    QPushButton[secondary="true"] {{ /* outline：描边透明底 */
        color: {c["fg"]};
        background: transparent;
        border: 1px solid {c["border"]};
        border-radius: {RADIUS_CARD}px;
    }}
    QPushButton[secondary="true"]:hover {{ background: {c["btn_secondary_hover"]}; }}
    QPushButton[danger="true"] {{ /* danger：删除危险红 */
        color: #ffffff;
        background: {c["btn_danger"]};
        border: 1px solid {c["btn_danger"]};
        border-radius: {RADIUS_CARD}px;
    }}
    QPushButton[danger="true"]:hover {{ background: {c["btn_danger_hover"]}; }}
    QPushButton[glass="true"] {{
        color: {c["fg"]};
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_CARD}px;
    }}
    QPushButton[glass="true"]:hover {{ background: {c["btn_secondary"]}; }}
    QPushButton[segment="true"] {{
        color: {c["fg_muted"]};
        background: transparent;
        border: none;
        border-radius: {RADIUS_CAPSULE}px;
        padding: 6px 16px;
        font-size: {FONT_BODY}px;
    }}
    QPushButton[segment="true"]:hover {{ color: {c["fg"]}; background: {c["btn_secondary"]}; }}
    QPushButton[segment="true"]:checked {{
        color: #ffffff;
        background: {c["btn_primary"]};
        font-weight: 600;
    }}
    QComboBox {{
        color: {c["fg"]};
        background: {c["input_bg"]};
        border: 1px solid {c["input_border"]};
        border-radius: {RADIUS_CARD}px;
        padding: 7px 14px;
        font-size: {FONT_BODY}px;
    }}
    QComboBox:hover {{ border: 1px solid {c["accent"]}; }}
    QComboBox:focus {{ border: 1px solid {c["accent"]}; background: {c["input_bg"]}; }}
    QComboBox::drop-down {{ border: none; width: 26px; }}
    QComboBox::down-arrow {{
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {c["fg_muted"]};
        width: 0; height: 0; margin-right: 8px;
    }}
    QComboBox QAbstractItemView {{
        background: {c["bg_secondary"]};
        border: 1px solid {c["border"]};
        border-radius: {RADIUS_CARD}px;
        selection-background-color: {c["accent_glow"]};
        selection-color: {c["fg"]};
        color: {c["fg"]};
        outline: 0;
    }}
    QCheckBox {{
        color: {c["fg"]};
        font-size: {FONT_BODY}px;
        spacing: 8px;
        background: transparent;
        border: none;
    }}
    QCheckBox::indicator {{
        width: 20px; height: 20px;
        border-radius: 6px;
        border: 1px solid {c["input_border"]};
        background: {c["input_bg"]};
    }}
    QCheckBox::indicator:hover {{ border: 1px solid {c["accent"]}; }}
    QCheckBox::indicator:checked {{ background: {c["accent"]}; border: 1px solid {c["accent"]}; }}
    QSpinBox {{
        color: {c["fg"]};
        background: {c["input_bg"]};
        border: 1px solid {c["input_border"]};
        border-radius: {RADIUS_CARD}px;
        padding: 6px 12px;
        font-size: {FONT_BODY}px;
    }}
    QSpinBox:focus {{ border: 1px solid {c["accent"]}; }}
    QSpinBox::up-button, QSpinBox::down-button {{
        subcontrol-origin: border;
        width: 22px;
        border: none;
        background: transparent;
    }}
    QSpinBox::up-button {{ subcontrol-position: top right; border-left: 1px solid {c["border"]}; }}
    QSpinBox::down-button {{ subcontrol-position: bottom right; border-left: 1px solid {c["border"]}; border-top: 1px solid {c["border"]}; }}
    QSpinBox::up-arrow {{
        width: 0; height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 5px solid {c["fg_muted"]};
    }}
    QSpinBox::down-arrow {{
        width: 0; height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid {c["fg_muted"]};
    }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{
        background: transparent;
        width: 6px;
        margin: 6px;
    }}
    QScrollBar::handle:vertical {{
        background: {c["scrollbar_handle"]};
        border-radius: 3px;
        min-height: 32px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {c["accent"]}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QMenu {{
        background: {c["bg_secondary"]};
        border: 1px solid {c["border"]};
        border-top: 1px solid {c["border_light"]};
        border-radius: {RADIUS_CARD}px;
        padding: 8px;
    }}
    QMenu::item {{
        padding: 10px 30px 10px 18px;
        border-radius: {RADIUS_CARD}px;
        color: {c["fg"]};
        font-size: {FONT_CAPTION}px;
        font-weight: 500;
    }}
    QMenu::item:selected {{
        background: {c["accent_glow"]};
    }}
    QMenu::item:disabled {{ color: {c["fg_muted"]}; }}
    QMenu::separator {{
        height: 1px;
        background: {c["border"]};
        margin: 7px 14px;
    }}
    QToolTip {{
        background: {c["bg_secondary"]};
        border: 1px solid {c["border"]};
        border-radius: {RADIUS_CARD}px;
        color: {c["fg"]};
        padding: 7px 12px;
        font-size: {FONT_BODY}px;
    }}
    QStatusBar {{ background: transparent; }}
    QTabWidget::pane {{
        background: transparent;
        border: 1px solid {c["border"]};
        border-radius: {RADIUS_CARD}px;
        padding: 4px;
    }}
    QTabWidget::tab-bar {{ alignment: center; }}
    QTabBar::tab {{
        color: {c["fg_muted"]};
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_CAPSULE}px;
        padding: 9px 20px;
        font-size: {FONT_BODY}px;
        font-weight: 600;
        margin: 2px 3px;
    }}
    QTabBar::tab:hover {{ color: {c["fg"]}; background: {c["btn_secondary"]}; }}
    QTabBar::tab:selected {{
        color: #ffffff;
        background: {c["btn_primary"]};
        border: 1px solid {c["btn_primary"]};
    }}
    QListWidget {{
        color: {c["fg"]};
        background: {c["card_bg"]};
        border: 1px solid {c["border"]};
        border-radius: {RADIUS_CARD}px;
        padding: 6px;
        font-size: {FONT_BODY}px;
        outline: 0;
    }}
    QListWidget::item {{
        padding: 9px 12px;
        border-radius: {RADIUS_CARD}px;
    }}
    QListWidget::item:selected {{
        background: {c["accent_glow"]};
        color: {c["fg"]};
    }}
    QListWidget::item:hover {{ background: {c["btn_secondary"]}; }}
    QTableWidget {{
        color: {c["fg"]};
        background: {c["card_bg"]};
        border: 1px solid {c["border"]};
        border-radius: {RADIUS_CARD}px;
        gridline-color: {c["border"]};
        font-size: {FONT_BODY}px;
        selection-background-color: {c["accent_glow"]};
    }}
    QTableWidget::item {{ padding: 7px 10px; }}
    QHeaderView::section {{
        background: {c["bg_secondary"]};
        color: {c["fg_muted"]};
        border: none;
        border-bottom: 1px solid {c["border"]};
        padding: 9px 10px;
        font-size: {FONT_CAPTION}px;
        font-weight: 600;
    }}
    QHeaderView::section:first {{ border-top-left-radius: {RADIUS_CARD}px; }}
    QHeaderView::section:last {{ border-top-right-radius: {RADIUS_CARD}px; }}
    /* ── 输入区 composer：单行胶囊容器（图标 + 输入框一体） ── */
    QFrame#composer {{
        background: {c["input_bg"]};
        border: 1px solid {c["input_border"]};
        border-radius: {RADIUS_CAPSULE}px;
    }}
    QPlainTextEdit#composerInput {{
        background: transparent;
        border: none;
        padding: 6px 6px;
        font-size: 20px;
        color: {c["fg"]};
        selection-background-color: {c["accent_glow"]};
    }}
    /* ── 扁平图标按钮（composer 内）：默认透明，悬停玻璃底 ── */
    QPushButton[flat="true"] {{
        background: transparent;
        border: 1px solid transparent;
        border-radius: {RADIUS_CARD}px;
    }}
    QPushButton[flat="true"]:hover {{ background: {c["btn_secondary"]}; }}
    QPushButton[flat="true"]:pressed {{ background: {c["btn_secondary_hover"]}; }}
    QPushButton[flat="true"][active="true"] {{
        background: {c["accent_glow"]};
        border: 1px solid {c["accent"]};
    }}
    """


def glass_menu_stylesheet() -> str:
    """现代玻璃质感菜单样式（右键菜单 / 托盘菜单共用）"""
    c = get_theme_colors()
    return f"""
    QMenu {{
        background: {c["bg_secondary"]};
        border: 1px solid {c["border"]};
        border-top: 1px solid {c["border_light"]};
        border-radius: {GLASS_RADIUS}px;
        padding: 8px 6px;
        font-family: {FONT_STACK};
    }}
    QMenu::item {{
        padding: 11px 16px 11px 16px;
        border-radius: {RADIUS_CARD}px;
        color: {c["fg"]};
        font-size: {FONT_BODY}px;
        font-weight: 400;
        margin: 2px 6px;
    }}
    QMenu::item:selected {{
        background: {c["accent_glow"]};
        color: {c["fg"]};
    }}
    QMenu::item:disabled {{
        color: {c["fg_muted"]};
        font-size: {FONT_CAPTION}px;
        font-weight: 600;
        padding: 8px 16px 4px 16px;
        letter-spacing: 0.5px;
    }}
    QMenu::separator {{
        height: 1px;
        background: {c["border"]};
        margin: 6px 16px;
    }}
    QMenu::right-arrow {{
        image: none;
        width: 8px;
        height: 8px;
        margin-right: 8px;
    }}
    QMenu::indicator {{
        width: 16px;
        height: 16px;
        margin-left: 4px;
        margin-right: 6px;
    }}
    QMenu::item:checked {{
        background: {c["accent_glow"]};
    }}
    """


class IconGridMenu(QWidget):
    """iPhone Control Center 风格的图标网格菜单：液态玻璃背景，图标默认无文字，悬停显示标签动画。
    支持子菜单：点击有子菜单的图标时，展开子菜单列表。
    用法：
        menu = IconGridMenu(parent_widget)
        menu.add_item("文字", icon_emoji, callback)
        submenu = menu.add_submenu("文字", icon_emoji)
        submenu.add_item(...)
        menu.popup(global_pos)
    """

    _ICON_SIZE = 52
    _CELL_SIZE = 94
    _GRID_PAD = 8
    _SECTION_H = 30
    _SEP_H = 6
    _TOOLTIP_H = 30
    _TOOLTIP_PAD = 8
    _COLS = 4
    _SUBITEM_H = 42
    _SUBITEM_PAD = 6

    closed = pyqtSignal()

    def __init__(self, parent=None, mode="grid"):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setStyleSheet("background:transparent;")
        self._items: list = []
        self._hover_idx = -1
        self._hover_scale: dict = {}
        self._tooltip_alpha: dict = {}
        self._ready = False
        self.setMouseTracking(True)
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_anim)
        self._open_submenu = None
        self._submenu_widget = None
        self._parent_menu = None
        self._mode = mode  # "grid" for main menu, "list" for submenus
        self._ITEM_H = 44
        self._H_PAD = 10
        # 首开：有子菜单的格子跑一道微光波（全进程仅一次）
        self._intro_wave_t = -1.0
        self._intro_wave_done = False

    def showEvent(self, event):
        super().showEvent(event)
        self._ready = False
        # hideEvent 会清空动画字典，重新展示时按 items 回填
        for i, it in enumerate(self._items):
            if it.get("kind") == "item":
                self._hover_scale.setdefault(i, 1.0)
                self._tooltip_alpha.setdefault(i, 0.0)
        if (self._mode == "grid" and not self._intro_wave_done
                and any(it.get("_submenu") for it in self._items if it.get("kind") == "item")):
            self._intro_wave_t = 0.0
            self._intro_wave_done = True
            if not self._anim_timer.isActive():
                self._anim_timer.start()
        QTimer.singleShot(120, lambda: setattr(self, '_ready', True))

    def add_item(self, text, icon="", callback=None, checkable=False, checked=False, enabled=True):
        it = {"kind": "item", "text": text, "icon": icon, "cb": callback,
              "checkable": checkable, "checked": checked, "enabled": enabled}
        self._items.append(it)
        idx = len(self._items) - 1
        self._hover_scale[idx] = 1.0
        self._tooltip_alpha[idx] = 0.0
        return it

    def add_submenu(self, text, icon=""):
        sub = IconGridMenu(self.window(), mode="list")
        sub._parent_menu = self
        it = {"kind": "item", "text": text, "icon": icon, "cb": None,
              "checkable": False, "checked": False, "enabled": True, "_submenu": sub}
        self._items.append(it)
        idx = len(self._items) - 1
        self._hover_scale[idx] = 1.0
        self._tooltip_alpha[idx] = 0.0
        return sub

    def add_section(self, text):
        self._items.append({"kind": "section", "text": text})

    def add_separator(self):
        self._items.append({"kind": "sep"})

    def _layout_grid(self):
        rows_items = []
        current_row = []
        row_kind = None
        for i, it in enumerate(self._items):
            kind = it.get("kind", "item")
            if kind == "item":
                if row_kind and row_kind != "item" and current_row:
                    rows_items.append(("row", current_row))
                    current_row = []
                current_row.append((i, it))
                row_kind = "item"
            else:
                if current_row:
                    rows_items.append(("row", current_row))
                    current_row = []
                row_kind = kind
                rows_items.append((kind, it))
        if current_row:
            rows_items.append(("row", current_row))
        return rows_items

    def _calc_size(self):
        layout = self._layout_grid()
        w = self._GRID_PAD * 2 + self._COLS * self._CELL_SIZE if self._items else 200
        h = self._GRID_PAD
        for kind, data in layout:
            if kind == "row":
                h += self._CELL_SIZE
            elif kind == "section":
                h += self._SECTION_H
            elif kind == "sep":
                h += self._SEP_H
        h += self._GRID_PAD + 4
        self._total_w = w
        self._total_h = h

    def popup(self, global_pos):
        if self._mode == "grid":
            self._calc_size()
        else:
            self._calc_list_size()
        self.setFixedWidth(self._total_w)
        self.setFixedHeight(self._total_h)
        self.move(global_pos)
        QApplication.instance().installEventFilter(self)
        self.show()
        self.raise_()
        self.activateWindow()
        self._anim_timer.start()

    def _calc_list_size(self):
        fm = self.fontMetrics()
        max_w = 140
        for it in self._items:
            if it.get("kind") == "item":
                tw = fm.horizontalAdvance(it.get("text", ""))
                aw = 16 if it.get("_submenu") else 0
                max_w = max(max_w, tw + aw + self._H_PAD * 2 + 24)
        self._total_w = max_w
        h = 8
        for it in self._items:
            kind = it.get("kind", "item")
            if kind == "item":
                h += self._ITEM_H
            elif kind == "section":
                h += 22
            elif kind == "sep":
                h += 8
        h += 8
        self._total_h = h

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            c = get_theme_colors()
            rect = self.rect().adjusted(2, 2, -2, -2)
            paint_liquid_glass(painter, rect, radius=GLASS_RADIUS, tier="panel")

            if self._mode == "grid":
                self._paint_grid(painter, rect, c)
            else:
                self._paint_list(painter, rect, c)
            painter.end()
        except Exception as e:
            logger.error(f"IconGridMenu.paintEvent 异常: {e}")

    def _paint_grid(self, painter, rect, c):
        layout = self._layout_grid()
        x_start = self._GRID_PAD
        y = self._GRID_PAD
        item_idx = 0
        for kind, data in layout:
            if kind == "row":
                for col_idx, (fi, it) in enumerate(data):
                    cx = x_start + col_idx * self._CELL_SIZE + self._CELL_SIZE // 2
                    cy = y + self._CELL_SIZE // 2
                    scale = self._hover_scale.get(fi, 1.0)
                    alpha = self._tooltip_alpha.get(fi, 0.0)
                    self._draw_icon_cell(painter, cx, cy, it, fi, scale, alpha)
                    item_idx += 1
                y += self._CELL_SIZE
            elif kind == "section":
                r = QRect(x_start + 4, y, self._total_w - self._GRID_PAD * 2 - 4, self._SECTION_H)
                painter.setPen(QPen(_hex_to_qcolor(c["fg_muted"]), 1))
                f = painter.font()
                f.setPixelSize(15)
                f.setWeight(600)
                painter.setFont(f)
                painter.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, data["text"])
                y += self._SECTION_H
            elif kind == "sep":
                painter.setPen(QPen(_hex_to_qcolor(c["border"]), 1))
                painter.drawLine(x_start + 12, y + self._SEP_H // 2,
                                 self._total_w - self._GRID_PAD - 12, y + self._SEP_H // 2)
                y += self._SEP_H

    def _paint_list(self, painter, rect, c):
        y = 8
        for i, it in enumerate(self._items):
            kind = it.get("kind", "item")
            if kind == "section":
                r = QRect(self._H_PAD + 4, y, rect.width() - self._H_PAD * 2 - 4, 22)
                painter.setPen(QPen(_hex_to_qcolor(c["fg_muted"]), 1))
                f = painter.font()
                f.setPixelSize(15)
                f.setWeight(600)
                painter.setFont(f)
                painter.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, it["text"])
                y += 22
            elif kind == "sep":
                painter.setPen(QPen(_hex_to_qcolor(c["border"]), 1))
                painter.drawLine(rect.left() + 14, y + 4, rect.right() - 14, y + 4)
                y += 8
            else:
                item_rect = QRect(self._H_PAD, y, rect.width() - self._H_PAD * 2, self._ITEM_H)
                self._draw_list_item(painter, item_rect, it, i)
                y += self._ITEM_H

    def _draw_list_item(self, painter, rect, it, idx):
        c = get_theme_colors()
        is_hover = idx == self._hover_idx
        enabled = it.get("enabled", True)
        h = self._ITEM_H

        if is_hover and enabled:
            anim = self._hover_scale.get(idx, 0.0)
            glow = _hex_to_qcolor(c["accent_glow"])
            glow.setAlphaF(0.15 + 0.25 * anim)
            painter.setBrush(glow)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(rect, RADIUS_CARD, RADIUS_CARD)

        f = painter.font()
        f.setPixelSize(FONT_BODY)
        f.setWeight(500 if enabled else 400)
        painter.setFont(f)

        # 子菜单列表：纯文字（标准菜单词汇，最自明）
        text_rect = QRect(rect.left() + 12, rect.top(), rect.width() - 24, h)
        painter.setPen(_hex_to_qcolor(c["fg"] if enabled else c["fg_muted"]))
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft, it.get("text", ""))

        if it.get("checkable") and it.get("checked"):
            painter.setPen(QPen(_hex_to_qcolor(c["accent"]), 2))
            cx = rect.right() - 26
            painter.drawText(QRect(cx, rect.top(), 22, h), Qt.AlignCenter, "✓")

        if it.get("_submenu"):
            arrow_x = rect.right() - 18
            painter.setPen(_hex_to_qcolor(c["fg_muted"]))
            af = painter.font()
            af.setPixelSize(15)
            painter.setFont(af)
            painter.drawText(QRect(arrow_x, rect.top(), 14, h), Qt.AlignCenter, "▸")

    def _draw_icon_cell(self, painter, cx, cy, it, idx, scale, tooltip_alpha):
        c = get_theme_colors()
        enabled = it.get("enabled", True)
        is_hover = idx == self._hover_idx
        has_submenu = it.get("_submenu") is not None
        tile = int(self._ICON_SIZE * scale)
        half = tile // 2
        # 悬停时图标微上移 + 下方标签淡入；静止时图标居中（无文字）
        hover_t = max(0.0, min(1.0, (scale - 1.0) / 0.15)) if scale > 1.0 else 0.0
        ty = int(round(cy - 10 * hover_t))
        icon_rect = QRect(cx - half, ty - half, tile, tile)
        if is_hover and enabled:
            anim = self._hover_scale.get(idx, 1.0)
            glow = _hex_to_qcolor(c["accent_glow"])
            boost = max(0.0, (anim - 1.0) / 0.15) if anim > 1.0 else 0.0
            glow.setAlphaF(0.18 + 0.32 * boost)
            painter.setBrush(glow)
            painter.setPen(Qt.NoPen)
            painter.drawRoundedRect(icon_rect.adjusted(-4, -4, 4, 4), 15, 15)
        bg = _hex_to_qcolor(c["bg_secondary"])
        bg.setAlpha(GLASS_ALPHA_SOLID if enabled else GLASS_ALPHA_DISABLED)
        painter.setBrush(bg)
        painter.setPen(QPen(_hex_to_qcolor(c["border"]), 1))
        painter.drawRoundedRect(icon_rect, RADIUS_CARD, RADIUS_CARD)
        # 首开微光波：子菜单格跑一道 accent 描边（约 600ms）
        if has_submenu and enabled and self._intro_wave_t >= 0.0:
            phase = self._intro_wave_t
            wave = max(0.0, 1.0 - abs(phase - 0.5) * 2.0)
            if wave > 0.02:
                wg = _hex_to_qcolor(c["accent_glow"])
                wg.setAlphaF(0.55 * wave)
                painter.setPen(QPen(wg, 2))
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(icon_rect.adjusted(-1, -1, 1, 1),
                                        RADIUS_CARD + 1, RADIUS_CARD + 1)
        # 矢量图标（统一体系，替代 emoji）
        pad = max(9, int(tile * 0.22))
        draw_rect = icon_rect.adjusted(pad, pad, -pad, -pad)
        icon_col = c["fg"] if enabled else c["fg_muted"]
        if is_hover and enabled:
            icon_col = c["accent"]
        _draw_icon_path(painter, it.get("icon", ""), draw_rect, icon_col,
                        stroke=1.9 * 20.0 / max(1, draw_rect.width()))
        if has_submenu and enabled:
            painter.setPen(_hex_to_qcolor(c["fg_muted"]))
            af = painter.font()
            af.setPixelSize(int(13 * scale))
            painter.setFont(af)
            arrow_x = cx + half - 5
            arrow_y = ty + half - 3
            painter.drawText(QRect(int(arrow_x), int(arrow_y), 10, 10), Qt.AlignCenter, "▸")
        if it.get("checkable") and it.get("checked"):
            painter.setPen(QPen(_hex_to_qcolor(c["accent"]), 2))
            painter.drawText(QRect(cx + half - 13, ty - half - 2, 15, 15), Qt.AlignCenter, "✓")
        # 标签仅悬停淡入（静止无文字）
        tip_text = it.get("text", "")
        if tip_text and tooltip_alpha > 0.03:
            lab_f = painter.font()
            lab_f.setPixelSize(FONT_CAPTION)
            lab_f.setWeight(600 if is_hover else 500)
            painter.setFont(lab_f)
            lab_color = _hex_to_qcolor(c["fg"] if enabled else c["fg_muted"])
            if is_hover and enabled:
                lab_color = _hex_to_qcolor(c["accent"])
            lab_color.setAlphaF(tooltip_alpha)
            painter.setPen(lab_color)
            lab_rect = QRect(cx - self._CELL_SIZE // 2 + 2, ty + half + 4,
                             self._CELL_SIZE - 4, 20)
            painter.drawText(lab_rect, Qt.AlignHCenter | Qt.AlignVCenter, tip_text)

    def _item_at(self, pos):
        if self._mode == "grid":
            return self._item_at_grid(pos)
        else:
            return self._item_at_list(pos)

    def _item_at_grid(self, pos):
        layout = self._layout_grid()
        x_start = self._GRID_PAD
        y = self._GRID_PAD
        item_idx = 0
        for kind, data in layout:
            if kind == "row":
                for col_idx, (fi, it) in enumerate(data):
                    cell = QRect(x_start + col_idx * self._CELL_SIZE + 2,
                                 y + 2, self._CELL_SIZE - 4, self._CELL_SIZE - 4)
                    if cell.contains(pos):
                        if it.get("enabled", True):
                            return fi
                        return -1
                    item_idx += 1
                y += self._CELL_SIZE
            elif kind == "section":
                y += self._SECTION_H
            elif kind == "sep":
                y += self._SEP_H
        return -1

    def _item_at_list(self, pos):
        y = 8
        for i, it in enumerate(self._items):
            kind = it.get("kind", "item")
            if kind == "item":
                if y <= pos.y() < y + self._ITEM_H and it.get("enabled", True):
                    return i
                y += self._ITEM_H
            elif kind == "section":
                y += 22
            elif kind == "sep":
                y += 8
        return -1

    def mouseMoveEvent(self, event):
        old = self._hover_idx
        self._hover_idx = self._item_at(event.pos())
        if self._hover_idx != old:
            if not self._anim_timer.isActive():
                self._anim_timer.start()
            self.update()

    def _tick_anim(self):
        changed = False
        if self._intro_wave_t >= 0.0:
            self._intro_wave_t += 16 / 600.0
            if self._intro_wave_t >= 1.0:
                self._intro_wave_t = -1.0
            else:
                changed = True
        for idx in list(self._hover_scale.keys()):
            target_scale = 1.15 if idx == self._hover_idx else 1.0
            cur = self._hover_scale.get(idx, 1.0)
            new_val = cur + (target_scale - cur) * 0.28
            if abs(new_val - target_scale) < 0.005:
                new_val = target_scale
            else:
                changed = True
            self._hover_scale[idx] = new_val
            target_alpha = 1.0 if idx == self._hover_idx else 0.0
            cur_alpha = self._tooltip_alpha.get(idx, 0.0)
            new_alpha = cur_alpha + (target_alpha - cur_alpha) * 0.22
            if abs(new_alpha - target_alpha) < 0.01:
                new_alpha = target_alpha
            else:
                changed = True
            self._tooltip_alpha[idx] = new_alpha
        self.update()
        if not changed:
            self._anim_timer.stop()

    def mousePressEvent(self, event):
        idx = self._item_at(event.pos())
        if idx >= 0:
            it = self._items[idx]
            sub = it.get("_submenu")
            if sub:
                self._show_submenu(sub, idx)
                return
            if it.get("cb"):
                it["cb"]()
            if it.get("checkable"):
                it["checked"] = not it.get("checked", False)
            self._close_tree()
        else:
            self.close_menu()

    def _show_submenu(self, sub, idx):
        if self._submenu_widget and self._submenu_widget.isVisible():
            self._submenu_widget.close_menu()
        self._submenu_widget = sub
        
        if self._mode == "grid":
            layout = self._layout_grid()
            x_start = self._GRID_PAD
            y = self._GRID_PAD
            item_idx = 0
            for kind, data in layout:
                if kind == "row":
                    for col_idx, (fi, it) in enumerate(data):
                        if fi == idx:
                            cx = x_start + col_idx * self._CELL_SIZE + self._CELL_SIZE // 2
                            cy = y + self._CELL_SIZE // 2
                            sub_pos = self.mapToGlobal(QPoint(cx + self._CELL_SIZE // 2, cy - 10))
                            sub.popup(sub_pos)
                            return
                        item_idx += 1
                    y += self._CELL_SIZE
                elif kind == "section":
                    y += self._SECTION_H
                elif kind == "sep":
                    y += self._SEP_H
        else:
            y = 8
            for i, it in enumerate(self._items):
                kind = it.get("kind", "item")
                if kind == "item":
                    if i == idx:
                        sub_pos = self.mapToGlobal(QPoint(self.width() - 4, y))
                        sub.popup(sub_pos)
                        return
                    y += self._ITEM_H
                elif kind == "section":
                    y += 22
                elif kind == "sep":
                    y += 8

    def leaveEvent(self, event):
        if self._hover_idx != -1:
            self._hover_idx = -1
            if not self._anim_timer.isActive():
                self._anim_timer.start()
            self.update()

    def focusOutEvent(self, event):
        pass

    def eventFilter(self, obj, event):
        if self.isVisible() and event.type() == QEvent.MouseButtonPress:
            gp = event.globalPos()
            # 点击链上任一菜单内 → 不关；点外部才关整树
            node = self
            inside = False
            while node is not None:
                if node.geometry().contains(node.mapFromGlobal(gp)):
                    inside = True
                    break
                node = node._submenu_widget
            if not inside:
                self._close_tree()
                return False
        return False

    def close_menu(self):
        if self._submenu_widget and self._submenu_widget.isVisible():
            self._submenu_widget.close_menu()
        self._submenu_widget = None
        QApplication.instance().removeEventFilter(self)
        self._anim_timer.stop()
        self.hide()
        self.closed.emit()

    def _close_tree(self):
        root = self
        while root._parent_menu is not None:
            root = root._parent_menu
        root.close_menu()

    def hideEvent(self, event):
        self._hover_idx = -1
        self._hover_scale.clear()
        self._tooltip_alpha.clear()


class _MenuFadeFilter(QObject):
    """事件过滤器：为 QMenu 添加淡入动画"""
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Show and isinstance(obj, obj.__class__):
            obj.setWindowOpacity(0.0)
            anim = QPropertyAnimation(obj, b"windowOpacity", obj)
            anim.setDuration(150)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            obj._fade_anim = anim
        return False


class StyledBubble(QLabel):
    """现代对话气泡：靠发送侧小圆角收尾（替代尖角尾巴），用户=墨调，Bot=毛玻璃"""
    def __init__(self, text: str, is_user: bool, parent=None):
        super().__init__(parent)
        self._text = text
        self._is_user = is_user
        self._tail_side = "right" if is_user else "left"
        self._anim_progress = 0.0
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setContentsMargins(16, 11, 16, 11)
        self._setup_style()
        self._apply_text(text)

    def _setup_style(self):
        c = get_theme_colors()
        # 柔和投影（0 8px 32px 10% 黑）：淡入动画期间被透明度特效临时替换，
        # 动画结束后由 _clear_bubble_effect 恢复
        self._shadow_effect = QGraphicsDropShadowEffect(self)
        self._shadow_effect.setBlurRadius(SHADOW_BLUR)
        self._shadow_effect.setOffset(0, SHADOW_OFFSET_Y)
        self._shadow_effect.setColor(QColor(0, 0, 0, int(255 * SHADOW_ALPHA)))
        self.setGraphicsEffect(self._shadow_effect)
        # 不对称圆角：靠发送侧收小（右收 = 用户，左收 = Bot）
        near = RADIUS_BUBBLE_SIDE
        far = RADIUS_BUBBLE
        if self._is_user:
            # 用户气泡：墨调渐变 + 顶部高光描边 + 左上/右上/左下大圆角、右下收小
            self.setStyleSheet(f"""
                QLabel {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                        stop:0 {c["user_bubble"]}, stop:1 {c["user_bubble_2"]});
                    color: {c["user_fg"]};
                    border: 1px solid rgba(255, 255, 255, 0.14);
                    border-top-left-radius: {far}px;
                    border-top-right-radius: {far}px;
                    border-bottom-left-radius: {far}px;
                    border-bottom-right-radius: {near}px;
                    padding: 11px 16px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QLabel {{
                    background: {c["bot_bubble"]};
                    border: 1px solid {c["bot_bubble_border"]};
                    color: {c["fg"]};
                    border-top-left-radius: {near}px;
                    border-top-right-radius: {far}px;
                    border-bottom-left-radius: {far}px;
                    border-bottom-right-radius: {far}px;
                    padding: 11px 16px;
                }}
            """)

    def _apply_text(self, text: str):
        # 简单的 Markdown 渲染：代码块、行内代码、粗体、斜体
        html = self._markdown_to_html(text)
        self.setTextFormat(Qt.RichText)
        self.setText(html)

    def _markdown_to_html(self, text: str) -> str:
        c = get_theme_colors()
        code_fg = c.get("code_fg", "#fbbf24")
        code_bg = c.get("code_bg", "#1e293b")
        inline_bg = c.get("code_inline_bg", "#334155")
        inline_fg = c.get("code_inline_fg", "#fbbf24")
        link_fg = c.get("accent", "#0A84FF")
        # 转义 HTML
        text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        # 代码块
        text = re.sub(r"```(\w+)?\n([\s\S]*?)```",
                      lambda m: f'<pre style="background:{code_bg};color:{code_fg};padding:10px;border-radius:10px;font-family:Consolas,Menlo,monospace;font-size:{FONT_CODE}px;"><code>{m.group(2)}</code></pre>',
                      text)
        # 行内代码
        text = re.sub(r"`([^`]+)`",
                      f'<code style="background:{inline_bg};color:{inline_fg};padding:2px 6px;border-radius:5px;font-family:Consolas,Menlo,monospace;font-size:{FONT_CODE}px;">\\1</code>',
                      text)
        # 链接
        text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)",
                      f'<a href="\\2" style="color:{link_fg};text-decoration:none;">\\1</a>',
                      text)
        self.setOpenExternalLinks(True)
        # 粗体
        text = re.sub(r"\*\*([^*]+)\*\*", r'<b>\1</b>', text)
        # 斜体
        text = re.sub(r"\*([^*]+)\*", r'<i>\1</i>', text)
        # 换行
        text = text.replace("\n", "<br>")
        return text

    def paintEvent(self, event):
        # 不对称圆角已表达发送方向，无需自绘尾巴
        try:
            super().paintEvent(event)
        except Exception as e:
            logger.error(f"StyledBubble.paintEvent 异常: {e}")

    def set_tail_side(self, side: str):
        self._tail_side = side
        self.update()

class TypingIndicator(QWidget):
    """iOS 风格打字指示器（三点呼吸动画）"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(56, 28)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(30)

    def showEvent(self, event):  # type: ignore[override]
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event):  # type: ignore[override]
        super().hideEvent(event)
        self._timer.stop()

    def _tick(self):
        self._phase += 0.09
        self.update()

    def paintEvent(self, event):
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing)
            c = get_theme_colors()
            accent = _hex_to_qcolor(c["accent"])
            base = _hex_to_qcolor(c["fg_muted"])
            for i in range(3):
                # 依次上浮 + 放大再回落（iOS 打字动画）
                t = (self._phase + i * 0.35) % 1.0
                bounce = math.sin(t * math.pi)
                radius = 3.0 + bounce * 2.0
                y = 14 - bounce * 4
                x = 10 + i * 18
                color = QColor(accent)
                color = QColor(
                    int(accent.red() * bounce + base.red() * (1 - bounce)),
                    int(accent.green() * bounce + base.green() * (1 - bounce)),
                    int(accent.blue() * bounce + base.blue() * (1 - bounce)),
                    int(120 + 135 * bounce),
                )
                painter.setBrush(QBrush(color))
                painter.setPen(Qt.NoPen)
                painter.drawEllipse(QPointF(x, y), radius, radius)
        except Exception as e:
            logger.error(f"TypingIndicator.paintEvent 异常: {e}")


class GradientTitleLabel(QLabel):
    """渐变标题：QPainter 线性渐变文字（accent 起 → 强调色收）"""
    def __init__(self, text: str = "", size: int = 16,
                 align=Qt.AlignCenter, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet("border: none; background: transparent;")
        self.setAlignment(align)
        f = self.font()
        f.setPointSizeF(size)
        f.setBold(True)
        self.setFont(f)

    def paintEvent(self, event):  # type: ignore[override]
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.Antialiasing, True)
            painter.setFont(self.font())
            c = get_theme_colors()
            grad = QLinearGradient(self.rect().topLeft(), self.rect().topRight())
            grad.setColorAt(0.0, _hex_to_qcolor(c.get("gradient_start", c["fg"])))
            grad.setColorAt(1.0, _hex_to_qcolor(c.get("gradient_end", c["accent"])))
            painter.setPen(QPen(QBrush(grad), 0))
            painter.drawText(self.rect(), int(self.alignment()), self.text())
        except Exception as e:
            logger.error(f"GradientTitleLabel.paintEvent 异常: {e}")


def _draw_icon_path(painter: QPainter, kind: str, rect, color, stroke: float = 1.7) -> None:
    """在 rect 内以统一笔画风格绘制线性图标（clip/camera/eye/palette）"""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    color = _hex_to_qcolor(color) if isinstance(color, str) else color
    pen = QPen(color)
    pen.setWidthF(stroke)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    # 归一化到 20x20 画布再缩放到目标 rect
    sx = rect.width() / 20.0
    sy = rect.height() / 20.0
    painter.translate(rect.x(), rect.y())
    painter.scale(sx, sy)

    if kind == "clip":
        # 纸夹：外环 + 内钩（几何拟合）
        p = QPainterPath()
        p.moveTo(7.2, 13.5)
        p.cubicTo(4.2, 10.5, 4.4, 6.0, 8.4, 4.8)
        p.cubicTo(12.4, 3.6, 15.6, 6.6, 14.8, 10.6)
        p.lineTo(14.4, 14.2)
        p.cubicTo(13.9, 17.2, 10.0, 17.6, 9.4, 14.6)
        p.cubicTo(9.1, 13.0, 11.0, 12.4, 11.7, 13.8)
        painter.drawPath(p)
    elif kind == "camera":
        body = QRectF(2.5, 6.0, 15.0, 11.0)
        painter.drawRoundedRect(body, 2.6, 2.6)
        p = QPainterPath()
        p.moveTo(7.2, 6.0)
        p.lineTo(8.4, 3.8)
        p.lineTo(14.0, 3.8)
        p.lineTo(15.2, 6.0)
        painter.drawPath(p)
        painter.drawEllipse(QPointF(10.0, 11.5), 3.1, 3.1)
    elif kind == "eye":
        lens = QPainterPath()
        lens.moveTo(1.8, 10.0)
        lens.cubicTo(5.0, 4.6, 15.0, 4.6, 18.2, 10.0)
        lens.cubicTo(15.0, 15.4, 5.0, 15.4, 1.8, 10.0)
        painter.drawPath(lens)
        painter.drawEllipse(QPointF(10.0, 10.0), 2.6, 2.6)
        painter.setBrush(_hex_to_qcolor(color))
        painter.drawEllipse(QPointF(10.0, 10.0), 1.1, 1.1)
    elif kind == "palette":
        # 调色盘：缺口圆环 + 三色点 + 拇指孔
        painter.drawArc(QRectF(2.6, 2.6, 14.8, 14.8), int(40 * 16), int(-290 * 16))
        painter.setBrush(_hex_to_qcolor(color))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QPointF(7.2, 7.4), 1.3, 1.3)
        painter.drawEllipse(QPointF(11.4, 5.9), 1.3, 1.3)
        painter.drawEllipse(QPointF(14.6, 8.4), 1.3, 1.3)
    elif kind == "refresh":
        # 新话题：环形箭头（缺口 + 箭头）
        painter.drawArc(QRectF(4.5, 4.5, 11.0, 11.0), int(80 * 16), int(-300 * 16))
        head = QPainterPath()
        head.moveTo(8.4, 3.4)
        head.lineTo(11.1, 4.7)
        head.lineTo(10.2, 7.3)
        painter.drawPath(head)
    elif kind == "arrow_up":
        # 发送：上箭头
        p = QPainterPath()
        p.moveTo(10.0, 16.4)
        p.lineTo(10.0, 4.6)
        painter.drawPath(p)
        head = QPainterPath()
        head.moveTo(5.6, 9.2)
        head.lineTo(10.0, 4.6)
        head.lineTo(14.4, 9.2)
        painter.drawPath(head)
    elif kind == "x":
        # 关闭：叉号
        p = QPainterPath()
        p.moveTo(5.4, 5.4)
        p.lineTo(14.6, 14.6)
        p.moveTo(14.6, 5.4)
        p.lineTo(5.4, 14.6)
        painter.drawPath(p)
    elif kind == "timer":
        # 计时器：圆环 + 顶钮 + 指针
        painter.drawEllipse(QRectF(3.6, 5.6, 12.8, 12.8))
        p = QPainterPath()
        p.moveTo(10.0, 2.8)
        p.lineTo(10.0, 5.2)
        p.moveTo(7.4, 2.8)
        p.lineTo(12.6, 2.8)
        painter.drawPath(p)
        p2 = QPainterPath()
        p2.moveTo(10.0, 10.0)
        p2.lineTo(10.0, 6.9)
        p2.moveTo(10.0, 10.0)
        p2.lineTo(12.9, 11.5)
        painter.drawPath(p2)
    elif kind == "chat":
        # 对话气泡：圆角框 + 尾巴
        painter.drawRoundedRect(QRectF(2.4, 4.2, 15.2, 10.4), 3.2, 3.2)
        p = QPainterPath()
        p.moveTo(6.6, 14.6)
        p.lineTo(5.2, 17.6)
        p.lineTo(10.0, 14.6)
        painter.drawPath(p)
    elif kind == "play":
        # 试听：实心三角（右键同款线体系中的填充动作图标）
        path = QPainterPath()
        path.moveTo(7.4, 5.0)
        path.lineTo(15.6, 10.0)
        path.lineTo(7.4, 15.0)
        path.closeSubpath()
        painter.setBrush(pen.color())
        painter.drawPath(path)
        painter.setBrush(Qt.NoBrush)
    elif kind == "sparkle":
        # 助手：四角星芒
        p = QPainterPath()
        p.moveTo(10.0, 2.6)
        p.lineTo(11.7, 8.3)
        p.lineTo(17.4, 10.0)
        p.lineTo(11.7, 11.7)
        p.lineTo(10.0, 17.4)
        p.lineTo(8.3, 11.7)
        p.lineTo(2.6, 10.0)
        p.lineTo(8.3, 8.3)
        p.closeSubpath()
        painter.drawPath(p)
    elif kind == "gear":
        # 齿轮：外圈齿 + 内圈
        painter.drawEllipse(QRectF(5.6, 5.6, 8.8, 8.8))
        painter.drawEllipse(QRectF(8.4, 8.4, 3.2, 3.2))
        import math as _m
        cx, cy = 10.0, 10.0
        for i in range(8):
            a = _m.radians(i * 45)
            x1 = cx + _m.cos(a) * 6.4
            y1 = cy + _m.sin(a) * 6.4
            x2 = cx + _m.cos(a) * 8.8
            y2 = cy + _m.sin(a) * 8.8
            p = QPainterPath()
            p.moveTo(x1, y1)
            p.lineTo(x2, y2)
            painter.drawPath(p)
    elif kind == "sliders":
        # 滑杆：三行 + 滑块（行为/调节）
        for y, kx in ((5.4, 7.0), (10.0, 13.4), (14.6, 8.8)):
            p = QPainterPath()
            p.moveTo(3.0, y)
            p.lineTo(17.0, y)
            painter.drawPath(p)
        painter.setBrush(_hex_to_qcolor(color))
        painter.setPen(QPen(_hex_to_qcolor(color), 1.2))
        painter.drawEllipse(QPointF(7.0, 5.4), 1.9, 1.9)
        painter.drawEllipse(QPointF(13.4, 10.0), 1.9, 1.9)
        painter.drawEllipse(QPointF(8.8, 14.6), 1.9, 1.9)
    elif kind == "power":
        # 电源：顶部缺口圆弧 + 竖线
        painter.drawArc(QRectF(4.0, 4.0, 12.0, 12.0), int(60 * 16), int(-300 * 16))
        p = QPainterPath()
        p.moveTo(10.0, 2.6)
        p.lineTo(10.0, 9.4)
        painter.drawPath(p)
    elif kind == "monitor":
        # 显示器：屏 + 支架（系统）
        painter.drawRoundedRect(QRectF(2.4, 4.0, 15.2, 10.0), 1.8, 1.8)
        p = QPainterPath()
        p.moveTo(10.0, 14.0)
        p.lineTo(10.0, 16.6)
        p.moveTo(6.4, 17.2)
        p.lineTo(13.6, 17.2)
        painter.drawPath(p)
    elif kind == "calendar":
        # 日历：框 + 顶栏 + 两钩 + 日点
        painter.drawRoundedRect(QRectF(2.6, 4.4, 14.8, 13.2), 2.2, 2.2)
        p = QPainterPath()
        p.moveTo(2.6, 8.8)
        p.lineTo(17.4, 8.8)
        p.moveTo(6.6, 2.6)
        p.lineTo(6.6, 6.0)
        p.moveTo(13.4, 2.6)
        p.lineTo(13.4, 6.0)
        painter.drawPath(p)
        painter.setBrush(_hex_to_qcolor(color))
        painter.setPen(Qt.NoPen)
        for dx, dy in ((6.6, 11.8), (10.0, 11.8), (13.4, 11.8),
                       (6.6, 15.0), (10.0, 15.0)):
            painter.drawEllipse(QPointF(dx, dy), 1.0, 1.0)
    elif kind == "edge":
        # 吸附边：竖线 + 箭头指向（QPainter 需 QPointF/int，float 会抛 TypeError 打断整帧）
        painter.drawLine(QPointF(5.5, 3.0), QPointF(5.5, 17.0))
        painter.drawLine(QPointF(5.5, 10.0), QPointF(14.0, 10.0))
        p = QPainterPath()
        p.moveTo(10.5, 6.0)
        p.lineTo(14.5, 10.0)
        p.lineTo(10.5, 14.0)
        painter.drawPath(p)
    elif kind == "person":
        # 秘书舰：头 + 肩
        painter.drawEllipse(QPointF(10.0, 6.8), 3.4, 3.4)
        p = QPainterPath()
        p.moveTo(4.0, 17.4)
        p.cubicTo(4.8, 12.6, 15.2, 12.6, 16.0, 17.4)
        painter.drawPath(p)
    painter.restore()


class IconButton(QPushButton):
    """自绘线性图标按钮：主题联动、悬停换色、active 态呼吸发光（感知开关等）"""

    def __init__(self, kind: str, tooltip: str = "", size: int = 40,
                 filled: bool = False, parent=None):
        super().__init__(parent)
        self._kind = kind
        self._active = False
        self._filled = filled
        self._glow = 0.0
        self.setFixedSize(size, size)
        self.setCursor(Qt.PointingHandCursor)
        self.setProperty("flat", "true")
        if tooltip:
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip)
        # active 呼吸发光动画（0→1→0，1.6s 循环）
        self._breath = QVariantAnimation(self)
        self._breath.setDuration(1600)
        self._breath.setStartValue(0.0)
        self._breath.setEndValue(1.0)
        self._breath.setEasingCurve(QEasingCurve.SineCurve)
        self._breath.setLoopCount(-1)
        self._breath.valueChanged.connect(self._on_breath)

    def set_active(self, on: bool) -> None:
        """感知开关等激活态：accent 描边 + 呼吸发光"""
        self._active = bool(on)
        self.setProperty("active", "true" if self._active else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        if self._active:
            self._breath.start()
        else:
            self._breath.stop()
            self._glow = 0.0
        self.update()

    def is_active(self) -> bool:
        return self._active

    def _on_breath(self, v) -> None:
        self._glow = float(v)
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        try:
            c = get_theme_colors()
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            r = self.rect()
            hot = self.underMouse() or self.isDown()
            if self._filled:
                # 实底主操作（发送）：圆形 accent，悬停提亮
                if self.isDown():
                    bg = _hex_to_qcolor(c.get("gradient_end", c["accent"]))
                elif hot:
                    bg = _hex_to_qcolor(c["accent_hover"])
                else:
                    bg = _hex_to_qcolor(c["accent"])
                p.setPen(Qt.NoPen)
                p.setBrush(bg)
                rad = min(r.width(), r.height()) // 2
                p.drawRoundedRect(r, rad, rad)
                icon_color = "#ffffff"
            elif self._active:
                # accent 玻璃底 + 呼吸高光叠加
                base = _hex_to_qcolor(c["accent_glow"])
                p.setPen(Qt.NoPen)
                p.setBrush(base)
                p.drawRoundedRect(r, RADIUS_CARD, RADIUS_CARD)
                breath = _hex_to_qcolor(c["accent"])
                breath.setAlphaF(0.10 + 0.22 * self._glow)
                p.setBrush(breath)
                p.drawRoundedRect(r, RADIUS_CARD, RADIUS_CARD)
                icon_color = c["accent"]
            else:
                if hot:
                    p.setPen(Qt.NoPen)
                    p.setBrush(_hex_to_qcolor(c["btn_secondary"]))
                    p.drawRoundedRect(r, RADIUS_CARD, RADIUS_CARD)
                icon_color = c["fg"] if hot else c["fg_muted"]
            if not self.isEnabled():
                icon_color = c["fg_muted"]
            pad = 9
            _draw_icon_path(p, self._kind, r.adjusted(pad, pad, -pad, -pad),
                            icon_color, stroke=1.7)
            p.end()
        except Exception as e:
            logger.error(f"IconButton.paintEvent 异常: {e}")


# ── 秘书舰轮换规则 ──
# 基准日期：2026-09-13 → 企业（索引 0）
# 固定 10 人闭环顺序（每 10 天一个循环）：
#   0 企业 → 1 翔鹤 → 2 贝尔法斯特 → 3 新泽西 → 4 胡德
#   5 瑞鹤 → 6 埃塞克斯 → 7 大凤 → 8 约克城 → 9 鞍山
# 计算公式：(today - base).days % 10；pet_config.json 的 "secretary" 键可覆盖轮换
SECRETARY_BASE = datetime.date(2026, 9, 13)
SECRETARY_NAMES = [
    "enterprise",   # 0
    "shoukaku",     # 1
    "belfast",      # 2
    "newjersey",    # 3
    "hood",         # 4
    "zuikaku",      # 5
    "essex",        # 6
    "taihou",       # 7
    "yorktown2",    # 8
    "anshan",       # 9
]

# 各舰娘皮肤名（与 jp voice_map 的 skin 字段对齐），按 _current_skin_idx 取
SECRETARY_SKIN_NAMES = {
    "anshan": ["原皮", "改造", "夕照伊人"],
    "belfast": ["原皮", "彩云之玫瑰", "倾城之华扇"],
}

# 源立绘（不透明）相对路径，按 _current_skin_idx；皮肤切换时与主立绘同步切换
SOURCE_ARTWORK = {
    "anshan": [
        "skins/source/anshan_default.jpg",
        "skins/source/anshan_mod.jpg",
        "skins/source/anshan_skin2.jpg",
    ],
}


def get_source_artwork(secretary: str, idx: int) -> Optional[str]:
    """返回当前皮肤的源立绘绝对路径（若存在），否则 None。"""
    paths = SOURCE_ARTWORK.get(secretary)
    if not paths or not (0 <= idx < len(paths)):
        return None
    rel = paths[idx]
    if getattr(sys, "frozen", False):
        base = sys._MEIPASS
    else:
        base = os.path.dirname(os.path.abspath(__file__))
    p = os.path.join(base, rel)
    return p if os.path.isfile(p) else None


# ── 皮肤清单（skins/skins_manifest.json，用户可增删皮肤）──
def _proj_root() -> str:
    """项目根：开发态为脚本目录，打包态为 _MEIPASS。"""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def _manifest_path() -> str:
    return os.path.join(_proj_root(), "skins", "skins_manifest.json")


def load_skin_manifest() -> dict:
    """返回 {secretary: [{name, png, source, jp_skin}]}。不存在时按现有文件与默认名引导。"""
    path = _manifest_path()
    m: dict = {}
    if os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                m = json.load(f)
            if isinstance(m, dict):
                return _reconcile_skin_manifest(m)
        except Exception:
            pass
    m = {}
    for sec in SECRETARY_NAMES:
        skins = get_available_skins(sec)
        names = SECRETARY_SKIN_NAMES.get(sec, [])
        srcs = SOURCE_ARTWORK.get(sec, [])
        entries = []
        for i, png in enumerate(skins):
            rel = os.path.relpath(png, _proj_root()).replace(os.sep, "/")
            name = names[i] if i < len(names) else f"皮肤{i + 1}"
            src = srcs[i] if i < len(srcs) else ""
            entries.append({"name": name, "png": rel, "source": src, "jp_skin": name})
        m[sec] = entries
    return _reconcile_skin_manifest(m)


def _skin_entry_name_from_path(sec: str, png_abs: str, index: int) -> str:
    """磁盘皮肤文件 → 清单显示名/jp_skin（优先固定表，其次 皮肤N）"""
    names = SECRETARY_SKIN_NAMES.get(sec, [])
    if 0 <= index < len(names):
        return names[index]
    stem = os.path.splitext(os.path.basename(png_abs))[0]
    if stem == sec:
        return "原皮"
    # shoukaku_3 → 皮肤3；shoukaku_2 → 皮肤2
    if stem.startswith(sec + "_"):
        suffix = stem[len(sec) + 1:]
        if suffix.isdigit():
            return f"皮肤{suffix}"
    return stem or f"皮肤{index + 1}"


def _reconcile_skin_manifest(m: dict) -> dict:
    """清单与磁盘对齐：索引严格 = get_available_skins 顺序，补进未登记立绘，剔除缺失文件。"""
    try:
        if not isinstance(m, dict):
            m = {}
        old_by_png: dict = {}
        for sec, entries in list(m.items()):
            if not isinstance(entries, list):
                continue
            for e in entries:
                if isinstance(e, dict) and e.get("png"):
                    old_by_png[(sec, str(e["png"]).replace("\\", "/"))] = e

        new_m: dict = {}
        changed = False
        for sec in SECRETARY_NAMES:
            names = SECRETARY_SKIN_NAMES.get(sec, [])
            srcs = SOURCE_ARTWORK.get(sec, [])
            entries = []
            for i, png in enumerate(get_available_skins(sec)):
                rel = os.path.relpath(png, _proj_root()).replace(os.sep, "/")
                old = old_by_png.get((sec, rel)) or {}
                name = (old.get("name")
                        or (names[i] if i < len(names) else "")
                        or _skin_entry_name_from_path(sec, png, i))
                src = old.get("source") or (srcs[i] if i < len(srcs) else "")
                jp = old.get("jp_skin") or name
                entries.append({
                    "name": name,
                    "png": rel,
                    "source": src or "",
                    "jp_skin": jp,
                })
            new_m[sec] = entries

        # 保留清单里其它键（非标准秘书舰）
        for sec, entries in m.items():
            if sec not in new_m:
                new_m[sec] = entries

        # 与磁盘顺序/成员不一致则写回（修复翔鹤只有 1 条清单的问题）
        for sec in SECRETARY_NAMES:
            old_e = m.get(sec) if isinstance(m.get(sec), list) else []
            if [e.get("png") for e in old_e if isinstance(e, dict)] != \
               [e["png"] for e in new_m.get(sec, [])]:
                changed = True
                break
        if changed:
            save_skin_manifest(new_m)
        return new_m
    except Exception as e:
        logger.error(f"皮肤清单对账失败: {e}")
        return m if isinstance(m, dict) else {}


def save_skin_manifest(m: dict) -> None:
    path = _manifest_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(m, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存皮肤清单失败: {e}")


def skin_names_for(sec: str) -> list:
    return [e.get("name", "皮肤") for e in load_skin_manifest().get(sec, [])]


def jp_skin_for(sec: str, idx: int) -> str:
    """返回第 idx 个皮肤在 jp voice_map 中的 skin 名（用于语音查找）。"""
    entries = load_skin_manifest().get(sec, [])
    if 0 <= idx < len(entries):
        return entries[idx].get("jp_skin") or entries[idx].get("name", "")
    names = SECRETARY_SKIN_NAMES.get(sec, [])
    if 0 <= idx < len(names):
        return names[idx]
    return ""


def source_for(sec: str, idx: int) -> Optional[str]:
    """返回第 idx 个皮肤的源立绘绝对路径（若存在）。"""
    entries = load_skin_manifest().get(sec, [])
    if 0 <= idx < len(entries):
        s = entries[idx].get("source", "")
        if s:
            p = os.path.join(_proj_root(), s) if not os.path.isabs(s) else s
            return p if os.path.isfile(p) else None
    return None


def add_secretary_skin(sec: str, name: str, png_src: str, source_src: Optional[str] = None,
                       jp_skin: Optional[str] = None) -> Optional[dict]:
    """新增一个皮肤：拷贝立绘（支持 PNG/JPG/JPEG，及可选源立绘）到 skins/，写入清单。"""
    try:
        m = load_skin_manifest()
        entries = m.setdefault(sec, [])
        idx = len(entries)
        suffix = "" if idx == 0 else f"_{idx + 1}"
        ext = os.path.splitext(png_src)[1].lower() or ".png"
        target_png = os.path.join(_proj_root(), "skins", f"{sec}{suffix}{ext}")
        os.makedirs(os.path.dirname(target_png), exist_ok=True)
        shutil.copyfile(png_src, target_png)
        entry = {"name": name, "png": f"skins/{sec}{suffix}{ext}", "source": "", "jp_skin": jp_skin or name}
        if source_src and os.path.isfile(source_src):
            ext = os.path.splitext(source_src)[1]
            target_src = os.path.join(_proj_root(), "skins", "source", f"{sec}{suffix}{ext}")
            os.makedirs(os.path.dirname(target_src), exist_ok=True)
            shutil.copyfile(source_src, target_src)
            entry["source"] = f"skins/source/{sec}{suffix}{ext}"
        entries.append(entry)
        m[sec] = entries
        save_skin_manifest(m)
        return entry
    except Exception as e:
        logger.error(f"添加皮肤失败: {e}")
        return None


def renumber_secretary_skins(sec: str) -> None:
    """删除皮肤后把剩余皮肤文件重排为连续编号，并同步清单路径。"""
    m = load_skin_manifest()
    entries = m.get(sec, [])
    base = _proj_root()
    tmp_map = []
    for e in entries:
        png = e.get("png", "")
        p = os.path.join(base, png) if not os.path.isabs(png) else png
        tmp = p + ".tmp_ren"
        if os.path.isfile(p):
            shutil.move(p, tmp)
        tmp_map.append((e, tmp))
        # 源立绘也先移走
        s = e.get("source", "")
        if s:
            sp = os.path.join(base, s) if not os.path.isabs(s) else s
            stmp = sp + ".tmp_ren"
            if os.path.isfile(sp):
                shutil.move(sp, stmp)
            e["_stmp"] = stmp
    for i, (e, tmp) in enumerate(tmp_map):
        suffix = "" if i == 0 else f"_{i + 1}"
        # 扩展名取自清单中的原始皮肤路径（tmp 带 .tmp_ren 后缀会截断出错误扩展名）
        orig_ext = os.path.splitext(e.get("png", ""))[1].lower()
        ext = orig_ext if orig_ext in (".png", ".jpg", ".jpeg") else ".png"
        target = os.path.join(base, "skins", f"{sec}{suffix}{ext}")
        if os.path.isfile(tmp):
            shutil.move(tmp, target)
        e["png"] = f"skins/{sec}{suffix}{ext}"
        stmp = e.pop("_stmp", None)
        if stmp and os.path.isfile(stmp):
            old = os.path.basename(stmp).replace(".tmp_ren", "")
            ext = os.path.splitext(old)[1]
            target_src = os.path.join(base, "skins", "source", f"{sec}{suffix}{ext}")
            os.makedirs(os.path.dirname(target_src), exist_ok=True)
            shutil.move(stmp, target_src)
            e["source"] = f"skins/source/{sec}{suffix}{ext}"
    m[sec] = entries
    save_skin_manifest(m)


def delete_secretary_skin(sec: str, idx: int) -> None:
    """删除第 idx 个皮肤：仅移除立绘与清单条目并重排编号。

    解绑原则：皮肤只是对语音池的引用；音频与文字始终成对保留，不随皮肤删除。
    """
    m = load_skin_manifest()
    entries = m.get(sec, [])
    if not (0 <= idx < len(entries)):
        return
    e = entries[idx]
    base = _proj_root()
    png = e.get("png", "")
    p = os.path.join(base, png) if not os.path.isabs(png) else png
    if os.path.isfile(p):
        try:
            os.remove(p)
        except Exception:
            pass
    s = e.get("source", "")
    if s:
        sp = os.path.join(base, s) if not os.path.isabs(s) else s
        if os.path.isfile(sp):
            try:
                os.remove(sp)
            except Exception:
                pass
    entries.pop(idx)
    m[sec] = entries
    save_skin_manifest(m)
    renumber_secretary_skins(sec)


def get_current_secretary() -> str:
    """获取当前秘书舰英文名：pet_config.json 的 secretary 键优先，否则按日期轮换"""
    cfg = load_config()
    override = cfg.get("secretary")
    if override in SECRETARY_NAMES:
        return override
    delta = (datetime.date.today() - SECRETARY_BASE).days
    return SECRETARY_NAMES[delta % len(SECRETARY_NAMES)]


def _time_slot() -> str:
    """根据当前小时返回时段：凌晨/早上/上午/中午/下午/晚上/深夜"""
    h = datetime.datetime.now().hour
    if 5 <= h < 8:
        return "早上"
    elif 8 <= h < 12:
        return "上午"
    elif 12 <= h < 14:
        return "中午"
    elif 14 <= h < 18:
        return "下午"
    elif 18 <= h < 22:
        return "晚上"
    elif 22 <= h or h < 2:
        return "深夜"
    else:
        return "凌晨"


def time_greeting(name: str) -> str:
    """生成时段感知的问候语"""
    slot = _time_slot()
    greetings = {
        "早上": f"早安，指挥官。我是{name}，新的一天要精神满满哦。",
        "上午": f"上午好，指挥官。我是{name}，今天的工作就交给我来协助吧。",
        "中午": f"中午好，指挥官。我是{name}，别忘了按时吃饭哦。",
        "下午": f"下午好，指挥官。我是{name}，来杯红茶提提神吧。",
        "晚上": f"晚好，指挥官。我是{name}，今天由我来陪伴你。",
        "深夜": f"还不休息吗，指挥官？我是{name}，我会一直在这里陪着你的。",
        "凌晨": f"已经这么晚了…指挥官，我是{name}，偶尔也要好好休息呢。",
    }
    return greetings.get(slot, f"你好，指挥官。我是{name}，今天由我来陪伴你。")


def get_skin_path(secretary: str | None = None) -> str:
    """获取指定秘书舰（默认当日）的主立绘路径（支持 png/jpg/jpeg）"""
    if secretary is None:
        secretary = get_current_secretary()
    if getattr(sys, "frozen", False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    for ext in (".png", ".jpg", ".jpeg"):
        path = os.path.join(base_dir, "skins", secretary + ext)
        if os.path.isfile(path):
            return path
    return os.path.join(base_dir, "skins", secretary + ".png")


def get_available_skins(secretary: str | None = None) -> list[str]:
    """获取指定秘书舰的所有可用立绘路径列表"""
    if secretary is None:
        secretary = get_current_secretary()
    if getattr(sys, "frozen", False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    skins_dir = os.path.join(base_dir, "skins")
    # 扫描 {name}.png / {name}.jpg / {name}.jpeg, {name}_2.png ... 跳过缺失继续
    skins: list[str] = []
    for suffix in [""] + [f"_{i}" for i in range(2, 20)]:
        for ext in (".png", ".jpg", ".jpeg"):
            path = os.path.join(skins_dir, f"{secretary}{suffix}{ext}")
            if os.path.isfile(path):
                skins.append(path)
                break
    return skins


def _get_voices_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.join(sys._MEIPASS, "voices")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "voices")


def load_voice_map(secretary: str) -> list[dict]:
    """加载指定秘书舰的语音映射 [{text, mp3}, ...]"""
    path = os.path.join(_get_voices_dir(), secretary, "voice_map.json")
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return []


DEFAULT_IMAGE_PATH = get_skin_path()
DEFAULT_API_BASE = "http://127.0.0.1:6185"
DEFAULT_API_KEY = ""  # 请由用户在设置中填写


class AstrBotClient(QObject):
    user_loaded = pyqtSignal(str)
    chat_received = pyqtSignal(str, str)
    error_occurred = pyqtSignal(str)
    connection_changed = pyqtSignal(bool)

    def __init__(self, base_url: str, api_key: str) -> None:
        super().__init__()
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.manager = QNetworkAccessManager(self)
        self.user_id = "desktop_pet"
        self.username = "desktop_pet"
        self.fallback_enabled = True
        self.history: list[dict[str, str]] = []
        self.conversation_id: str = ""
        self._pending_message: str = ""

        # WebSocket（默认通讯方案）
        self._use_websocket = True
        self.ws: QWebSocket | None = None
        self._ws_buffer = ""
        self._ws_plain_buffer = ""  # 拼接 type=plain 流式内容

    def fetch_user(self) -> None:
        self.user_loaded.emit(self.user_id)

    def set_user(self, user_id: str) -> None:
        self.user_id = user_id
        self.username = user_id
        self.user_loaded.emit(user_id)

    def clear_conversation(self) -> None:
        self.history.clear()
        self.conversation_id = ""

    @property
    def use_websocket(self) -> bool:
        return self._use_websocket

    @use_websocket.setter
    def use_websocket(self, value: bool) -> None:
        self._use_websocket = value
        if not value and self.ws:
            self.ws.close()
            self.ws = None

    # ── WebSocket 发送 ──
    def _send_ws(self, message: str) -> None:
        payload = json.dumps({"message": message, "username": self.username})
        # 已连接：直接发送
        if self.ws is not None and self.ws.state() == QWebSocket.ConnectedState:
            self.ws.sendTextMessage(payload)
            return
        # 首次或重连
        if self.ws is None:
            ws_url = f"ws://127.0.0.1:6185/api/v1/chat/ws?api_key={self.api_key}"
            self.ws = QWebSocket()
            self.ws.textMessageReceived.connect(self._on_ws_text)
            self.ws.error.connect(self._on_ws_error)
            self.ws.disconnected.connect(self._on_ws_disconnected)
            self.ws.open(QUrl(ws_url))
        # 绑定发送（先断开旧连接，避免堆叠）
        try:
            self.ws.connected.disconnect()
        except TypeError:
            pass
        self.ws.connected.connect(lambda msg=payload: self.ws.sendTextMessage(msg))

    def _on_ws_disconnected(self) -> None:
        """WebSocket 断开时清理，避免残留状态"""
        self.connection_changed.emit(False)
        if self.ws:
            try:
                self.ws.connected.disconnect()
            except TypeError:
                pass
            self.ws.close()
            self.ws = None

    def _on_ws_text(self, text: str) -> None:
        self._ws_buffer += text
        while True:
            try:
                obj, idx = json.JSONDecoder().raw_decode(self._ws_buffer)
                self._ws_buffer = self._ws_buffer[idx:].strip()
            except json.JSONDecodeError:
                break

            if not isinstance(obj, dict):
                continue

            evt_type = obj.get("type", "")

            # plain：流式文本片段，累积到临时缓冲区
            if evt_type == "plain":
                data = obj.get("data", "")
                if isinstance(data, str):
                    self._ws_plain_buffer += data
                elif isinstance(data, dict):
                    self._ws_plain_buffer += data.get("content") or data.get("text") or ""

            # complete：最终完整回复，优先使用
            elif evt_type == "complete":
                data = obj.get("data", "")
                if isinstance(data, dict):
                    data = data.get("content") or data.get("text") or ""
                if data:
                    self._save_context(self._pending_message, str(data))
                    self.chat_received.emit(str(data), "talk")
                self._ws_plain_buffer = ""

            # end：流式结束，发送累积的 plain 内容
            elif evt_type == "end":
                if self._ws_plain_buffer.strip():
                    self._save_context(self._pending_message, self._ws_plain_buffer)
                    self.chat_received.emit(self._ws_plain_buffer, "talk")
                self._ws_plain_buffer = ""

            # tool_call：AstrBot 下发工具调用指令
            elif evt_type == "tool_call":
                action = obj.get("action") or obj.get("name", "")
                params = obj.get("params") or obj.get("arguments") or {}
                if action:
                    self.chat_received.emit(f"__AGENT__{action}__|__{json.dumps(params)}", "agent")

            # 其他类型（tool_call, tool_call_result, agent_stats 等）：忽略

    def _on_ws_error(self, error_code: int) -> None:
        self.connection_changed.emit(False)
        self.error_occurred.emit(f"WebSocket 错误 (code={error_code})，回退 HTTP")
        self._use_websocket = False
        if self.ws:
            try:
                self.ws.connected.disconnect()
            except TypeError:
                pass
            self.ws.close()
            self.ws = None
        # 用 HTTP 重试当前消息
        if self._pending_message:
            msg = self._pending_message
            self._pending_message = ""
            self.chat(msg)

    # ── HTTP 发送（原逻辑） ──
    def chat(self, message: str) -> None:
        self._pending_message = message

        if self._use_websocket:
            self._send_ws(message)
            return

        url = QUrl(f"{self.base_url}/api/v1/chat")
        query = QUrlQuery()
        query.addQueryItem("api_key", self.api_key)
        url.setQuery(query.query(QUrl.FullyEncoded))

        payload_obj: dict = {"message": message, "username": self.username}
        if self.history:
            payload_obj["context"] = self.history[-20:]
        if self.conversation_id:
            payload_obj["conversation_id"] = self.conversation_id

        payload = json.dumps(payload_obj).encode("utf-8")
        request = QNetworkRequest(url)
        request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json; charset=utf-8")
        request.setRawHeader(b"X-API-Key", self.api_key.encode("utf-8"))
        request.setRawHeader(b"Authorization", f"ApiKey {self.api_key}".encode("utf-8"))

        reply = self.manager.post(request, payload)
        reply.finished.connect(lambda: self._handle_chat(reply, message))

    def _handle_chat(self, reply: QNetworkReply, message: str) -> None:
        status = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if reply.error() != QNetworkReply.NoError:
            reply.deleteLater()
            if self.fallback_enabled:
                fallback = self._fallback_reply(message)
                self._save_context(message, fallback)
                self.chat_received.emit(fallback, self._fallback_action(message))
                if status in {404, 405}:
                    self.error_occurred.emit("AstrBot 接口返回了 404/405，已使用本地兜底回复")
                else:
                    self.error_occurred.emit(f"AstrBot 暂不可用，已使用本地兜底回复：{reply.errorString()}")
            else:
                self.error_occurred.emit(f"/api/v1/chat 请求失败：{reply.errorString()}")
            return

        text = self._parse_sse(reply)
        reply.deleteLater()
        if not text:
            if self.fallback_enabled:
                fallback = self._fallback_reply(message)
                self._save_context(message, fallback)
                self.chat_received.emit(fallback, self._fallback_action(message))
                self.error_occurred.emit("AstrBot 返回内容为空，已使用本地兜底回复")
            else:
                self.error_occurred.emit("AstrBot 返回内容为空")
            return
        self._save_context(message, text)
        self.chat_received.emit(text, "talk")
        self.connection_changed.emit(True)

    def _save_context(self, user_msg: str, bot_reply: str) -> None:
        """保存一轮对话到上下文历史"""
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": bot_reply})
        # 只保留最近 40 条（20 轮）
        if len(self.history) > 40:
            self.history = self.history[-40:]

    def _parse_sse(self, reply: QNetworkReply) -> str:
        try:
            raw = bytes(reply.readAll()).decode("utf-8", errors="ignore")
        except Exception as exc:
            self.error_occurred.emit(f"响应读取失败：{exc}")
            return ""

        # 调试开关
        if os.environ.get("DESKTOP_PET_DEBUG_SSE"):
            import tempfile, datetime as _dt
            dump_path = os.path.join(tempfile.gettempdir(),
                                     f"desktop_pet_sse_{_dt.datetime.now():%Y%m%d_%H%M%S}.txt")
            with open(dump_path, "w", encoding="utf-8") as _f:
                _f.write(raw)
            self.error_occurred.emit(f"[DEBUG] SSE → {dump_path}")

        # AstrBot v4 SSE 事件类型：
        #   session_id / user_message_saved / plain（混有工具调用） / agent_stats
        #   → 只取 complete 事件的 data 字段作为最终回复
        final_reply = ""
        for line in raw.splitlines():
            line = line.strip()
            if not line or not line.startswith("data:"):
                continue
            payload = line[len("data:"):].strip()
            if not payload:
                continue
            try:
                data_obj = json.loads(payload)
            except json.JSONDecodeError:
                continue
            if not isinstance(data_obj, dict):
                continue
            if data_obj.get("type") == "complete":
                data_value = data_obj.get("data")
                if isinstance(data_value, str):
                    final_reply = data_value
                elif isinstance(data_value, dict):
                    final_reply = data_value.get("content") or data_value.get("text") or ""
                break  # 找到 complete 即停止

        return final_reply.strip()

    @staticmethod
    def _fallback_reply(message: str) -> str:
        return f"指挥官，我先用本地应答：{message}"

    @staticmethod
    def _fallback_action(message: str) -> str:
        return "idle"


# ── Agent 工具英文名 → 中文显示名 映射 ──
AGENT_TOOL_NAMES: dict[str, str] = {
    "screenshot": "截取屏幕",
    "open_file": "打开文件",
    "type_text": "输入文本",
    "get_system_info": "获取系统信息",
    "list_apps": "列出运行中的应用",
    "execute_command": "执行桌面操作",
    "keyboard_type": "键盘输入",
    "keyboard_press": "模拟按键",
    "mouse_click": "鼠标点击",
    "mouse_move": "移动鼠标",
    "read_file": "读取文件",
    "write_file": "写入文件",
    "list_processes": "列出进程",
    "kill_process": "结束进程",
    "find_window": "查找窗口",
    "clipboard_get": "读取剪贴板",
    "clipboard_set": "写入剪贴板",
    "astrbot_execute_shell": "执行终端命令",
}


class AgentEngine(QObject):
    """本地 Agent 执行引擎 —— 解析并执行 AstrBot 下发的工具调用"""
    action_started = pyqtSignal(str)
    action_finished = pyqtSignal(str, str, bool)  # (动作, 摘要, 是否成功)
    error_occurred = pyqtSignal(str)

    def __init__(self) -> None:
        super().__init__()
        self._tools: dict[str, callable] = self._build_tools()

    def _build_tools(self) -> dict[str, callable]:
        return {
            "screenshot": self._screenshot, "open_file": self._open_file,
            "type_text": self._type_text, "get_system_info": self._system_info,
            "list_apps": self._list_apps, "execute_command": self._execute_command,
            "keyboard_type": self._keyboard_type, "keyboard_press": self._keyboard_press,
            "mouse_click": self._mouse_click, "mouse_move": self._mouse_move,
            "read_file": self._read_file, "write_file": self._write_file,
            "list_processes": self._list_processes, "kill_process": self._kill_process,
            "find_window": self._find_window,
            "clipboard_get": self._clipboard_get, "clipboard_set": self._clipboard_set,
        }

    def execute(self, action: str, params: dict | None = None) -> dict:
        """执行工具调用，返回统一格式 {'success': bool, 'data'/'error': ...}"""
        if params is None:
            params = {}
        func = self._tools.get(action)
        if func is None:
            return {"success": False, "error": f"未知动作: {action}"}
        try:
            self.action_started.emit(action)
            # 通过线程池执行并设置 30 秒超时
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(func, params)
                result = future.result(timeout=30)
            self.action_finished.emit(
                action,
                str(result.get("data", result.get("message", "")))[:200],
                result.get("success", False),
            )
            return result
        except concurrent.futures.TimeoutError:
            msg = f"工具 {action} 执行超时"
            self.error_occurred.emit(msg)
            return {"success": False, "error": msg}
        except Exception as e:
            msg = f"执行失败: {e}"
            self.error_occurred.emit(msg)
            return {"success": False, "error": msg}

    # ── 工具实现 ──
    @staticmethod
    def _screenshot(params: dict) -> dict:
        import pyautogui, base64, io
        path = params.get("save_path") or params.get("path", "")
        img = pyautogui.screenshot()
        if path:
            img.save(path)
        # 转 JPEG base64（体积更小）
        buf = io.BytesIO()
        img.convert("RGB").save(buf, format="JPEG", quality=95)
        b64 = base64.b64encode(buf.getvalue()).decode()
        return {"success": True, "data": {"image_base64": b64, "width": img.width, "height": img.height}}

    @staticmethod
    def _open_file(params: dict) -> dict:
        path = params.get("path", "")
        if not path:
            return {"success": False, "error": "未指定路径"}
        if not os.path.exists(path):
            return {"success": False, "error": f"路径不存在: {path}"}
        os.startfile(path)
        return {"success": True, "message": f"已打开: {os.path.basename(path)}"}

    @staticmethod
    def _type_text(params: dict) -> dict:
        import pyautogui, pyperclip
        text = params.get("text", "")
        if not text: return {"success": False, "error": "未提供文本"}
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        return {"success": True, "message": f"已输入 {len(text)} 字符"}

    @staticmethod
    def _system_info(params: dict) -> dict:
        import psutil, platform
        cpu = psutil.cpu_percent(interval=0.3)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        return {"success": True, "data": {
            "cpu_percent": cpu,
            "memory_percent": mem.percent, "memory_used_gb": round(mem.used/1073741824, 1),
            "memory_total_gb": round(mem.total/1073741824, 1),
            "disk_percent": disk.percent, "disk_free_gb": round(disk.free/1073741824, 1),
            "system": f"{platform.system()} {platform.release()}"
        }}

    @staticmethod
    def _list_apps(params: dict) -> dict:
        import psutil
        names = set()
        for p in psutil.process_iter(["name"]):
            try:
                n = p.info["name"]
                if n: names.add(n)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {"success": True, "data": sorted(names)[:50]}

    @staticmethod
    def _execute_command(params: dict) -> dict:
        import pyautogui, subprocess
        a = (params.get("action", "") or "").lower()
        # 精确匹配
        if a == "open_calculator": subprocess.Popen("calc.exe"); return {"success": True, "message": "已打开计算器"}
        if a == "open_notepad": subprocess.Popen("notepad.exe"); return {"success": True, "message": "已打开记事本"}
        if a == "open_cmd": subprocess.Popen("cmd.exe"); return {"success": True, "message": "已打开命令提示符"}
        if a == "minimize_all": pyautogui.hotkey("win", "d"); return {"success": True, "message": "已显示桌面"}
        if a == "volume_up": pyautogui.press("volumeup"); return {"success": True, "message": "音量已增加"}
        if a == "volume_down": pyautogui.press("volumedown"); return {"success": True, "message": "音量已减小"}
        if a == "volume_mute": pyautogui.press("volumemute"); return {"success": True, "message": "已静音"}
        if a == "lock": subprocess.Popen("rundll32.exe user32.dll,LockWorkStation"); return {"success": True, "message": "屏幕已锁定"}
        # 关键词匹配：支持自然语言描述
        if any(k in a for k in ["计算器", "calc"]): subprocess.Popen("calc.exe"); return {"success": True, "message": "已打开计算器"}
        if any(k in a for k in ["记事本", "notepad", "画图", "paint", "mspaint"]):
            if "画图" in a or "paint" in a: subprocess.Popen("mspaint.exe"); return {"success": True, "message": "已打开画图"}
            subprocess.Popen("notepad.exe"); return {"success": True, "message": "已打开记事本"}
        if any(k in a for k in ["cmd", "命令提示符", "命令行", "终端"]): subprocess.Popen("cmd.exe"); return {"success": True, "message": "已打开命令提示符"}
        if any(k in a for k in ["浏览器", "chrome", "edge", "firefox", "网页"]): os.startfile("https://www.baidu.com"); return {"success": True, "message": "已打开浏览器"}
        if any(k in a for k in ["最小化", "桌面", "显示桌面"]): pyautogui.hotkey("win", "d"); return {"success": True, "message": "已显示桌面"}
        if any(k in a for k in ["静音", "mute"]): pyautogui.press("volumemute"); return {"success": True, "message": "已静音"}
        if any(k in a for k in ["锁定", "lock"]): subprocess.Popen("rundll32.exe user32.dll,LockWorkStation"); return {"success": True, "message": "屏幕已锁定"}
        # 尝试作为程序名直接启动
        if a and not a.startswith("unknown") and len(a) < 50:
            try: subprocess.Popen(a, shell=True); return {"success": True, "message": f"已尝试启动: {a}"}
            except: pass
        return {"success": False, "error": "无法识别的桌面操作，支持：打开计算器/记事本/画图/命令行/浏览器、最小化所有窗口、调整音量、静音、锁定屏幕"}

    @staticmethod
    def _keyboard_type(params: dict) -> dict:
        import pyautogui, pyperclip
        text = params.get("text", "")
        if not text: return {"success": False, "error": "未提供输入文本"}
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        return {"success": True, "message": f"已输入: {text[:60]}"}

    @staticmethod
    def _keyboard_press(params: dict) -> dict:
        import pyautogui
        keys = params.get("keys", "")
        if not keys: return {"success": False, "error": "未指定按键"}
        k = [x.strip() for x in keys.split("+")]
        pyautogui.hotkey(*k) if len(k) > 1 else pyautogui.press(k[0])
        return {"success": True, "message": f"已按键: {keys}"}

    @staticmethod
    def _mouse_click(params: dict) -> dict:
        import pyautogui
        x, y = params.get("x", pyautogui.position().x), params.get("y", pyautogui.position().y)
        pyautogui.click(x, y, button=params.get("button", "left"))
        return {"success": True, "message": f"已点击 ({x},{y})"}

    @staticmethod
    def _mouse_move(params: dict) -> dict:
        import pyautogui
        pyautogui.moveTo(params.get("x", 0), params.get("y", 0))
        return {"success": True, "message": f"鼠标移至 ({params.get('x')},{params.get('y')})"}

    @staticmethod
    def _read_file(params: dict) -> dict:
        path = params.get("path", "")
        if not os.path.isfile(path): return {"success": False, "error": f"文件不存在: {path}"}
        try:
            with open(path, encoding="utf-8") as f:
                return {"success": True, "data": f.read()[:3000]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @staticmethod
    def _write_file(params: dict) -> dict:
        path, content, mode = params.get("path", ""), params.get("content", ""), params.get("mode", "w")
        if not path: return {"success": False, "error": "未指定路径"}
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, mode, encoding="utf-8") as f:
            f.write(content)
        return {"success": True, "message": f"已写入 {path} ({len(content)}字符)"}

    @staticmethod
    def _list_processes(params: dict) -> dict:
        import psutil
        f = (params.get("filter", "") or "").lower()
        out = []
        for p in psutil.process_iter(["pid", "name"]):
            try:
                n = (p.info["name"] or "").lower()
                if not f or f in n:
                    out.append(f"{p.info['pid']}:{p.info['name']}")
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {"success": True, "data": out[:30]}

    @staticmethod
    def _kill_process(params: dict) -> dict:
        import psutil
        if pid := params.get("pid"):
            psutil.Process(int(pid)).terminate()
            return {"success": True, "message": f"已终止 PID={pid}"}
        if name := params.get("name"):
            for p in psutil.process_iter(["pid", "name"]):
                if p.info["name"] == name:
                    p.terminate()
                    return {"success": True, "message": f"已终止: {name}"}
        return {"success": False, "error": "未指定 pid/name"}

    @staticmethod
    def _find_window(params: dict) -> dict:
        t = (params.get("title", "") or "").lower()
        if not t: return {"success": False, "error": "未指定窗口标题"}
        try:
            import pygetwindow as gw
            for w in gw.getAllTitles():
                if t in w.lower():
                    gw.getWindowsWithTitle(w)[0].activate()
                    return {"success": True, "message": f"已激活: {w}"}
            return {"success": False, "error": f"未找到窗口: {t}"}
        except ImportError:
            return {"success": False, "error": "pygetwindow 未安装"}

    @staticmethod
    def _clipboard_get(params: dict) -> dict:
        import pyperclip
        return {"success": True, "data": pyperclip.paste()}

    @staticmethod
    def _clipboard_set(params: dict) -> dict:
        import pyperclip
        t = params.get("text", "")
        pyperclip.copy(t)
        return {"success": True, "message": f"已复制 ({len(t)}字符)"}


# ── safe_slot 装饰器：捕获槽函数异常并输出日志 ──
def safe_slot(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            logger.error(f"槽函数 {func.__name__} 异常: {e}")
            traceback.print_exc()
    return wrapper


class PluginWebSocketClient(QObject):
    """桌面助手插件 WebSocket 客户端 (端口由 pet_config.server_port 决定，协议对齐)"""
    chat_received = pyqtSignal(str, str)       # (回复文本, 动作类型)
    command_received = pyqtSignal(str, dict)    # (命令名, params)
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)
    command_finished = pyqtSignal(str, str, dict)  # (命令名, request_id, 结果) 后台线程回传

    def __init__(self, ws_url: str, session_id: str, api_key: str, agent_engine: AgentEngine) -> None:
        super().__init__()
        self.session_id = session_id
        self.api_key = api_key
        self.ws_url = self._build_ws_url(ws_url)
        self.agent = agent_engine
        self.ws: QWebSocket | None = None
        self.connected = False
        self._buffer = ""
        self.awareness_enabled = False

        # 后台线程执行完工具后，经此信号回主线程发送结果
        self.command_finished.connect(self._on_command_finished)

        # ── 消息队列 ──
        self.msg_queue: queue.Queue = queue.Queue(maxsize=200)
        self._queue_timer = QTimer(self)
        self._queue_timer.setInterval(10)
        self._queue_timer.timeout.connect(self._process_queue)
        self._queue_timer.start()

        # ── 重连 ──
        self.reconnect_interval = 3000
        self.max_reconnect_interval = 60000
        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setSingleShot(True)
        self.reconnect_timer.timeout.connect(self.connect_to_server)

        # ── 心跳 ──
        self._last_heartbeat_ack = time.time()
        self._heartbeat_timeout = 60.0
        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.setInterval(20000)
        self._heartbeat_timer.timeout.connect(self._send_heartbeat)
        self._heartbeat_check_timer = QTimer(self)
        self._heartbeat_check_timer.setInterval(10000)
        self._heartbeat_check_timer.timeout.connect(self._check_heartbeat)
        self._heartbeat_check_timer.start()

    def connect_to_server(self) -> None:
        self.reconnect_timer.stop()
        self._heartbeat_timer.stop()
        self._heartbeat_check_timer.stop()
        if self.ws:
            # 先断开旧 socket 的信号，避免其 disconnected 事件误触发重连循环
            for sig in (self.ws.textMessageReceived, self.ws.connected,
                        self.ws.disconnected, self.ws.error):
                try:
                    sig.disconnect()
                except TypeError:
                    pass
            try:
                self.ws.close()
            except Exception:
                pass
        self.ws = QWebSocket()
        self.ws.textMessageReceived.connect(self._on_text_message)
        self.ws.connected.connect(self._on_connected)
        self.ws.disconnected.connect(self._on_disconnected)
        self.ws.error.connect(self._on_ws_error)
        self.ws.open(QUrl(self.ws_url))

    def _build_ws_url(self, base: str) -> str:
        """把基础地址拼成带 session_id/token 的完整 WS URL（strip 掉已有 query）"""
        base = base.split("?", 1)[0]
        return f"{base}?session_id={self.session_id}&token={self.api_key}"

    def switch_url(self, ws_url: str) -> None:
        """切换服务端地址并立即重连（AstrBot 6190 ⇄ DSH 6191 一键切换）。

        入参是基础地址（如 ws://127.0.0.1:6190/），这里自动补回
        session_id/token 查询串——否则服务端会因缺少参数拒绝握手。
        旧 socket 的信号已在 connect_to_server 里断开，不会误触发重连循环。
        """
        new_url = self._build_ws_url(ws_url)
        if new_url == self.ws_url and self.connected:
            return
        self.ws_url = new_url
        self.reconnect_interval = 3000
        self.connected = False
        self.connection_changed.emit(False)
        self.connect_to_server()

    def _on_connected(self) -> None:
        # 忽略过期 socket 的连接事件
        if self.sender() is not None and self.sender() is not self.ws:
            return
        self.connected = True
        self.connection_changed.emit(True)
        self.reconnect_interval = 3000
        self._heartbeat_timer.start()
        self._heartbeat_check_timer.start()
        # 连接后同步当前桌面感知开关状态
        self.send_awareness(getattr(self, "awareness_enabled", False))
        # 同步主动回话参数
        try:
            self.send_config_sync({
                "proactive": {
                    "probability": getattr(self, "_proactive_probability", 0.3),
                    "min_interval": getattr(self, "_proactive_min_interval", 300),
                    "max_interval": getattr(self, "_proactive_max_interval", 900),
                }
            })
        except Exception:
            pass

    def _on_disconnected(self) -> None:
        # 忽略过期 socket 的断开事件（仅当前 socket 的断开才触发重连）
        if self.sender() is not None and self.sender() is not self.ws:
            return
        self.connected = False
        self.connection_changed.emit(False)
        self._heartbeat_timer.stop()
        self._heartbeat_check_timer.stop()
        # 清空消息队列
        while not self.msg_queue.empty():
            try:
                self.msg_queue.get_nowait()
            except queue.Empty:
                break
        # 自动重连（指数退避）
        self.reconnect_timer.start(self.reconnect_interval)
        self.reconnect_interval = min(self.reconnect_interval * 2, self.max_reconnect_interval)

    def _send_heartbeat(self) -> None:
        if self.ws and self.connected:
            self.ws.sendTextMessage(json.dumps({"type": "heartbeat", "timestamp": time.time()}))

    def send_chat(self, text: str, image_base64: str = "") -> None:
        msg: dict = {"type": "chat_message", "content": text}
        msg["sender_id"] = "星海机"
        msg["sender_name"] = "星海机的人机"
        if image_base64:
            msg["image_base64"] = image_base64
        self._send(msg)

    def send_desktop_state(self, window_title: str, process: str, screenshot_b64: str = None) -> None:
        from datetime import datetime, timezone
        msg = {
            "type": "desktop_state",
            "data": {
                "active_window_title": window_title,
                "active_window_process": process,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        }
        if screenshot_b64:
            msg["data"]["screenshot_base64"] = screenshot_b64
        self._send(msg)

    def send_awareness(self, enabled: bool) -> None:
        """上报桌面感知开关状态（服务端据此启停主动回话）"""
        self.awareness_enabled = enabled
        self._send({"type": "awareness", "data": {"enabled": bool(enabled)}})

    def send_config_sync(self, settings: dict) -> None:
        """上报主动回话参数（概率/间隔），服务端实时应用"""
        self._send({"type": "config_sync", "data": settings})

    def send_command_result(self, command: str, request_id: str, result: dict) -> None:
        if command == "screenshot":
            data = result.get("data", result)
            payload = {
                "type": "screenshot_response",
                "data": {
                    "request_id": request_id,
                    "success": result.get("success", False),
                    "image_base64": data.get("image_base64", ""),
                    "width": data.get("width", 0),
                    "height": data.get("height", 0),
                    "error_message": result.get("error", ""),
                }
            }
            self._send(payload)
        else:
            self._send({"type": "command_result", "command": command, "request_id": request_id, "data": result})

    def _send(self, msg: dict) -> None:
        if self.ws and self.connected:
            self.ws.sendTextMessage(json.dumps(msg))

    def _on_text_message(self, text: str) -> None:
        # 忽略过期 socket 的消息
        if self.sender() is not None and self.sender() is not self.ws:
            return
        self._buffer += text
        # 缓冲区保护：超过 1MB 则截断
        if len(self._buffer) > 1_048_576:
            self._buffer = self._buffer[-1_048_576:]
        while True:
            try:
                obj, idx = json.JSONDecoder().raw_decode(self._buffer)
                self._buffer = self._buffer[idx:].strip()
            except json.JSONDecodeError:
                break
            if not isinstance(obj, dict):
                continue
            msg_type = obj.get("type", "")
            # 任何来自服务器的消息都证明连接存活，刷新心跳 ack 时间
            self._last_heartbeat_ack = time.time()
            if msg_type == "heartbeat_ack":
                continue
            # 其他消息入队，由 _process_queue 在主线程处理
            try:
                self.msg_queue.put_nowait(obj)
            except queue.Full:
                try:
                    self.msg_queue.get_nowait()
                    self.msg_queue.put_nowait(obj)
                except queue.Empty:
                    pass

    def _process_queue(self) -> None:
        try:
            obj = self.msg_queue.get_nowait()
        except queue.Empty:
            return
        msg_type = obj.get("type", "")
        if msg_type == "message":
            content = obj.get("content", "")
            # 修复AstrBot插件MessageChain泄露：str(message_chain) 而非 _message_chain_to_text
            if isinstance(content, str) and "MessageChain(chain=[" in content:
                import re
                # 提取所有 Plain 组件的 text 字段（支持转义单引号）
                texts = re.findall(r"text='((?:[^'\\]|\\.)*)'", content)
                if texts:
                    # 还原转义字符
                    content = "".join(t.replace("\\'", "'") for t in texts)
                elif "Image(" in content:
                    # 纯图片链：显示占位，绝不把 repr 当正文
                    content = "[图片]"
                else:
                    content = ""
            # 内容可能是图片对象等非字符串，统一转文本
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False)
            elif not isinstance(content, str):
                content = str(content) if content else ""
            if content:
                self.chat_received.emit(content, "talk")
        elif msg_type == "command":
            cmd = obj.get("command", "")
            rid = obj.get("request_id", "")
            params = obj.get("params", {})
            self.command_received.emit(cmd, params)
            # 后台线程执行，避免阻塞 Qt 主线程导致 WS 心跳/协议 ping 停滞而断连
            self._run_command_async(cmd, rid, params)
        elif msg_type == "connection_status" and obj.get("status") == "connected":
            self.connection_changed.emit(True)
        elif msg_type == "todo_push":
            # 待办事项推送：通过 chat_received 信号复用现有气泡显示逻辑
            content = obj.get("content", "")
            if isinstance(content, (dict, list)):
                content = json.dumps(content, ensure_ascii=False)
            elif not isinstance(content, str):
                content = str(content) if content else ""
            if content:
                self.chat_received.emit(f"📋 待办提醒：{content}", "talk")
        elif msg_type == "todo_push":
            # 待办推送：在气泡显示待办事项
            title = obj.get("title", "待办")
            content = obj.get("content", "")
            due = obj.get("due", "")
            priority = obj.get("priority", "")
            text = f"📝 待办：{title}"
            if content:
                text += f"\n{content}"
            if due:
                text += f"\n⏰ {due}"
            if priority:
                text += f"  [{priority}]"
            self.chat_received.emit(text, "todo")

    def _run_command_async(self, cmd: str, rid: str, params: dict) -> None:
        """在后台线程执行桌宠工具，完成后经信号回主线程发送结果"""
        import threading

        def _worker() -> None:
            try:
                result = self.agent.execute(cmd, params)
            except Exception as e:
                result = {"success": False, "error": f"工具执行异常: {e}"}
            # 跨线程发射信号，PyQt 自动排队到主线程
            self.command_finished.emit(cmd, rid, result)

        threading.Thread(target=_worker, daemon=True).start()

    def _on_command_finished(self, cmd: str, rid: str, result: dict) -> None:
        """主线程收到工具执行结果后回传给服务器"""
        try:
            self.send_command_result(cmd, rid, result)
        except Exception as e:
            logger.error(f"回传命令结果失败: {e}")

    def _check_heartbeat(self) -> None:
        if not self.connected:
            return
        if time.time() - self._last_heartbeat_ack > self._heartbeat_timeout:
            self.error_occurred.emit("心跳超时，连接断开")
            self.connection_changed.emit(False)
            self.connected = False
            self._heartbeat_timer.stop()
            if self.ws:
                try:
                    self.ws.close()
                except Exception:
                    pass

    def _on_ws_error(self, error_code: int) -> None:
        # 忽略过期 socket 的错误事件
        if self.sender() is not None and self.sender() is not self.ws:
            return
        self.error_occurred.emit(f"WebSocket 错误 (code={error_code})")
        self.connection_changed.emit(False)


class ChatBubble(QFrame):
    send_requested = pyqtSignal(str)
    theme_change_requested = pyqtSignal()
    screenshot_requested = pyqtSignal()
    awareness_toggle_requested = pyqtSignal()

    def __init__(self) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._bubble_labels: list[StyledBubble] = []
        self._agent_status_label: QLabel | None = None
        self._typing_indicator: TypingIndicator | None = None
        self._thinking_label: QLabel | None = None
        self._last_bot_bubble: StyledBubble | None = None
        self.setObjectName("chatBubble")
        self._apply_theme()

        # ── 顶部标题栏（iOS 风格） ──
        self.avatar_label = QLabel()
        self.avatar_label.setFixedSize(46, 46)
        self.avatar_label.setAlignment(Qt.AlignCenter)
        self.title_label = GradientTitleLabel("碧蓝桌宠", size=22,
                                              align=Qt.AlignLeft | Qt.AlignVCenter)
        self.status_pill = QLabel("● 离线")
        self.status_pill.setStyleSheet(
            f'color: {get_theme_colors()["fg_muted"]}; font-size: {FONT_CAPTION}px; '
            f'background: {get_theme_colors()["bot_bubble"]}; '
            f'border: 1px solid {get_theme_colors()["bot_bubble_border"]}; '
            f'border-radius: {RADIUS_PILL}px; padding: 3px 11px;'
        )
        # 截图 / 感知 / 主题 三个图标钮放标题栏，给输入区让出全部横向空间
        self.screenshot_btn = IconButton("camera", "立即截图并发送给 AI 分析", size=44)
        self.awareness_btn = IconButton("eye", "开启/关闭桌面感知", size=44)
        self.theme_btn = IconButton("palette", "切换主题", size=44)
        self.screenshot_btn.clicked.connect(self.screenshot_requested)
        self.awareness_btn.clicked.connect(self.awareness_toggle_requested)
        self.theme_btn.clicked.connect(self.theme_change_requested)

        header_layout = QHBoxLayout()
        header_layout.setSpacing(8)
        header_layout.setContentsMargins(4, 2, 4, 4)
        header_layout.addWidget(self.avatar_label)
        header_layout.addWidget(self.title_label, 1)
        header_layout.addWidget(self.status_pill)
        header_layout.addWidget(self.screenshot_btn)
        header_layout.addWidget(self.awareness_btn)
        header_layout.addWidget(self.theme_btn)

        # ── 发丝线分隔（优雅留白的呼吸） ──
        self.header_separator = QFrame()
        self.header_separator.setObjectName("headerSeparator")
        self.header_separator.setFixedHeight(1)

        # ── 对话历史（可滚动） ──
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.scroll_area.setFrameShape(QFrame.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        # 视口默认绘制白色底色，会盖住自绘玻璃，必须显式透明
        self.scroll_area.viewport().setStyleSheet("background: transparent;")
        self.scroll_area.viewport().setAutoFillBackground(False)

        self.history_widget = QWidget()
        self.history_widget.setAttribute(Qt.WA_TranslucentBackground, True)
        self.history_layout = QVBoxLayout(self.history_widget)
        self.history_layout.setContentsMargins(10, 12, 10, 6)
        self.history_layout.setSpacing(8)
        self.history_layout.addStretch()
        self.scroll_area.setWidget(self.history_widget)

        # ── 文件上传 ──
        self.selected_files = []

        # ── 输入区：单行 composer 胶囊（附件 + 多行输入 + 新话题 + 发送，全部内嵌） ──
        self.input_line = ChatInput()
        self.upload_btn = IconButton("clip", "上传文件（右键清空）", size=40)
        self.upload_btn.clicked.connect(self._on_upload_files)
        self.upload_btn.setContextMenuPolicy(Qt.CustomContextMenu)
        self.upload_btn.customContextMenuRequested.connect(self._on_upload_context)

        self.clear_btn = IconButton("refresh", "新话题（清空对话）", size=40)
        self.send_button = IconButton("arrow_up", "发送（回车）", size=40, filled=True)

        composer = QFrame()
        composer.setObjectName("composer")
        comp_layout = QHBoxLayout(composer)
        comp_layout.setContentsMargins(6, 4, 6, 4)
        comp_layout.setSpacing(4)
        comp_layout.addWidget(self.upload_btn)
        comp_layout.addWidget(self.input_line, 1)
        comp_layout.addWidget(self.clear_btn)
        comp_layout.addWidget(self.send_button)

        # composer 独占一行（胶囊内已含全部按钮）
        input_layout = QHBoxLayout()
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.addWidget(composer, 1)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(GLASS_MARGIN, GLASS_MARGIN, GLASS_MARGIN, GLASS_MARGIN)
        layout.setSpacing(10)
        layout.addLayout(header_layout)
        layout.addWidget(self.header_separator)
        layout.addWidget(self.scroll_area, 1)
        layout.addLayout(input_layout)

        self.send_button.clicked.connect(self._on_send)
        self.clear_btn.clicked.connect(self._on_clear)
        self.input_line.send_requested.connect(self._on_send)
        # 高度按屏幕可用区自适应（默认 552，上限 760），长回复一次看全；宽度恢复 456
        try:
            avail_h = QApplication.primaryScreen().availableGeometry().height()
        except Exception:
            avail_h = 900
        content_h = max(552, min(760, int(avail_h * 0.78)))
        self.resize(456 + GLASS_MARGIN * 2, content_h + GLASS_MARGIN * 2)

        # 窗口淡入淡出动画（首帧必须先把 opacity 设到起点再 show，避免“满亮闪一下再从 0 淡入”）
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(280)
        self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
        self._fading_out = False
        self.setWindowOpacity(0.0)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self._pinned = False
        self._swipe_start = None
        self._swipe_moved = False

    def _apply_theme(self) -> None:
        """应用主题样式"""
        self.setStyleSheet(theme_stylesheet())
        # 窗口阴影改由 paintEvent 自绘（paint_liquid_glass），
        # 避免 QGraphicsEffect + windowOpacity 动画在 Windows 分层窗口上的合成失败/闪退。
        c = get_theme_colors()
        # 刷新状态药丸与标题颜色
        if hasattr(self, "status_pill"):
            self.status_pill.setStyleSheet(
                f'color: {c["fg_muted"]}; font-size: {FONT_CAPTION}px; '
                f'background: {c["bot_bubble"]}; '
                f'border: 1px solid {c["bot_bubble_border"]}; '
                f'border-radius: {RADIUS_PILL}px; padding: 3px 11px;'
            )
        if hasattr(self, "header_separator"):
            self.header_separator.setStyleSheet(
                f'background: {c["border"]}; border: none; max-height: 1px;'
            )
        if hasattr(self, "title_label"):
            self.title_label.setStyleSheet(
                f'color: {c["fg"]}; font-size: {FONT_TITLE}px; font-weight: 700; border: none;'
            )

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """自绘 iOS 26 Liquid Glass 玻璃卡片（含外阴影与高光）"""
        try:
            painter = QPainter(self)
            card = self.rect().adjusted(GLASS_MARGIN, GLASS_MARGIN,
                                        -GLASS_MARGIN, -GLASS_MARGIN)
            if card.width() <= 0 or card.height() <= 0:
                return
            paint_liquid_glass(painter, card)
        except Exception as e:
            logger.error(f"ChatBubble.paintEvent 异常: {e}")

    def set_avatar(self, pixmap: QPixmap) -> None:
        """设置头部秘书舰圆角头像"""
        if pixmap.isNull():
            return
        self.avatar_label.setPixmap(make_rounded_pixmap(pixmap, 34))

    def set_connection(self, connected: bool) -> None:
        """更新连接状态药丸"""
        c = get_theme_colors()
        color = c["connected"] if connected else c["disconnected"]
        text = "在线" if connected else "离线"
        self.status_pill.setStyleSheet(
            f'color: {c["fg"]}; font-size: {FONT_CAPTION}px; font-weight: 600; '
            f'background: {c["bot_bubble"]}; '
            f'border: 1px solid {c["bot_bubble_border"]}; '
            f'border-radius: {RADIUS_PILL}px; padding: 3px 11px;'
        )
        self.status_pill.setText(f"<span style='color:{color};'>●</span> {text}")

    def showEvent(self, event) -> None:  # type: ignore[override]
        try:
            super().showEvent(event)
            # 玻璃观感由 paintEvent 自绘实现；不再调用系统亚克力
            # （SetWindowCompositionAttribute 会引发黑框/黑闪，见历史问题记录）
            # 禁用 DWM 显隐过渡，消除分层窗口 show/hide 时的黑闪
            _disable_dwm_transitions(self)
        except Exception as e:
            logger.error(f"ChatBubble.showEvent 异常: {e}")

    def _apply_glass(self) -> None:
        """兼容占位：玻璃观感由 paintEvent 自绘，无需系统亚克力"""
        try:
            self._glass_pending = False
        except Exception:
            pass

    def moveEvent(self, event) -> None:  # type: ignore[override]
        try:
            super().moveEvent(event)
        except Exception as e:
            logger.error(f"ChatBubble.moveEvent 异常: {e}")

    def show(self) -> None:  # type: ignore[override]
        try:
            self._fade_anim.stop()
            try:
                self._fade_anim.finished.disconnect()
            except TypeError:
                pass
            self._fading_out = False
            was_visible = self.isVisible()
            cur = float(self.windowOpacity())
            # 已完全可见且不在淡出：不再从 0 重播（否则整窗闪一下）
            if was_visible and cur >= 0.97:
                self.setWindowOpacity(1.0)
                QTimer.singleShot(0, self._scroll_to_bottom)
                return
            # 先定位再显示，避免首帧落在旧坐标再跳一下
            before = getattr(self, "before_show", None)
            if callable(before):
                try:
                    before()
                except Exception:
                    pass
            # 隐藏时从 0 起淡；淡出被打断时从当前透明度继续淡回（连贯，不闪）
            start = 0.0 if not was_visible else max(0.0, min(1.0, cur))
            self.setWindowOpacity(start)
            super().show()
            self._fade_anim.setStartValue(start)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._fade_anim.start()
            # 显示时平滑滚动到底部
            QTimer.singleShot(120, self._scroll_to_bottom)
        except Exception as e:
            logger.error(f"ChatBubble.show 异常: {e}")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        try:
            if event.button() == Qt.LeftButton:
                self._swipe_start = event.globalPos()
                self._swipe_moved = False
                # accept：确保后续 move/release 都进本窗口（子 QLabel 默认不吃鼠标）
                event.accept()
                return
        except Exception:
            pass
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        try:
            if self._swipe_start is not None and (event.buttons() & Qt.LeftButton):
                dy = event.globalPos().y() - self._swipe_start.y()
                dx = event.globalPos().x() - self._swipe_start.x()
                if abs(dy) > 8 or abs(dx) > 8:
                    self._swipe_moved = True
                # 下擦关闭（竖直位移为主）
                if dy > 72 and abs(dy) > abs(dx):
                    self._swipe_start = None
                    self.hide()
                    event.accept()
                    return
                event.accept()
                return
        except Exception:
            pass
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        try:
            if event.button() == Qt.LeftButton and self._swipe_start is not None:
                was_click = not self._swipe_moved
                self._swipe_start = None
                if was_click:
                    self._pinned = not self._pinned
                    self.title_label.setText("📌 碧蓝桌宠" if self._pinned else "碧蓝桌宠")
        except Exception:
            pass
        super().mouseReleaseEvent(event)

    def hide(self) -> None:  # type: ignore[override]
        try:
            if not self.isVisible():
                return
            self._fade_anim.stop()
            try:
                self._fade_anim.finished.disconnect()
            except TypeError:
                pass
            self._fading_out = True
            start = float(self.windowOpacity())
            self._fade_anim.setStartValue(start)
            self._fade_anim.setEndValue(0.0)
            self._fade_anim.setEasingCurve(QEasingCurve.InCubic)

            # 嵌套函数里零参 super() 不可用，先绑定父类方法
            parent_hide = super().hide

            def _finish() -> None:
                self._fading_out = False
                parent_hide()
                try:
                    self.setWindowOpacity(0.0)
                except Exception:
                    pass

            self._fade_anim.finished.connect(_finish)
            # 若已几乎透明，直接收尾，避免再播一轮空动画
            if start <= 0.02:
                self._fade_anim.stop()
                _finish()
                return
            self._fade_anim.start()
        except Exception as e:
            logger.error(f"ChatBubble.hide 异常: {e}")

    def _scroll_to_bottom(self, animated: bool = True) -> None:
        """平滑滚动到底部（200ms OutCubic）"""
        try:
            sb = self.scroll_area.verticalScrollBar()
            if sb is None:
                return
            target = sb.maximum()
            if not animated:
                sb.setValue(target)
                return
            anim = getattr(self, "_scroll_anim", None)
            if anim is not None:
                anim.stop()
            self._scroll_anim = QPropertyAnimation(sb, b"value", self)
            self._scroll_anim.setDuration(200)
            self._scroll_anim.setStartValue(sb.value())
            self._scroll_anim.setEndValue(target)
            self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)
            self._scroll_anim.start()
        except Exception as e:
            logger.error(f"滚动到底部异常: {e}")

    def _on_upload_files(self) -> None:
        """上传文件按钮：弹出文件选择框，支持多选"""
        from PyQt5.QtWidgets import QFileDialog
        paths, _ = QFileDialog.getOpenFileNames(self, "选择文件（可多选）", "", "所有文件 (*)")
        if not paths:
            return
        self.selected_files.extend(paths)
        self.input_line.setPlaceholderText(f"已选{len(self.selected_files)}个文件（右键📎清空）输入提问后发送")

    def _on_upload_context(self, pos):
        """📎右键菜单：清空已选文件"""
        if not self.selected_files:
            return
        menu = QMenu(self)
        clear_act = QAction("清空已选文件", self)
        clear_act.triggered.connect(self._clear_selected_files)
        menu.addAction(clear_act)
        menu.exec_(self.upload_btn.mapToGlobal(pos))

    def _clear_selected_files(self):
        self.selected_files.clear()
        self.input_line.setPlaceholderText("输入要对桌宠说的话...")

    def _on_send(self) -> None:
        text = self.input_line.toPlainText().strip()
        if not text and not self.selected_files:
            return
        # 构建显示用消息（只显示文件名）
        display_parts = []
        if text:
            display_parts.append(text)
        file_names = [str(fp).split("/")[-1].split("\\")[-1] for fp in self.selected_files]
        if file_names:
            display_parts.append("📎 " + "、".join(file_names))
        display_msg = chr(10).join(display_parts)
        # 气泡立即显示：文字 + 文件名
        self.add_message(display_msg, is_user=True)
        self.input_line.clear()
        self.input_line.setPlaceholderText("输入要对桌宠说的话...")

        # 有文件：后台线程读取全文（避免大文件解析阻塞 UI 造成卡顿）
        if self.selected_files:
            files = list(self.selected_files)
            self.selected_files.clear()
            self.show_agent_status("📄 正在读取文件内容…")
            import threading

            def _worker() -> None:
                try:
                    from file_handler import FileHandler
                    handler = FileHandler(max_chars=15000, max_total=60000)
                    results = handler.read_files(files)
                except Exception as e:
                    logger.error(f"读取文件异常: {e}")
                    results = [
                        {"name": os.path.basename(str(f)) if str(f) else "?",
                         "error": str(e), "type": "未知",
                         "content": "", "truncated": False, "size_kb": 0}
                        for f in files
                    ]
                parts = [text] if text else []
                for r in results:
                    if r["error"]:
                        parts.append(f"--- 文件: {r['name']} [错误: {r['error']}] ---")
                    elif r["content"]:
                        truncated_mark = " (截断)" if r["truncated"] else ""
                        parts.append(
                            f"--- 文件: {r['name']} ({r['type']}, {r['size_kb']}KB){truncated_mark} ---\n"
                            f"{r['content']}"
                        )
                    else:
                        parts.append(f"--- 文件: {r['name']} ({r['type']}) [不支持直接读取内容] ---")
                full_msg = chr(10).join(parts)
                # 跨线程发射信号（PyQt 自动排队到主线程）
                self.send_requested.emit(full_msg)

            threading.Thread(target=_worker, daemon=True).start()
            return

        # 无文件：直接发送文字
        self.send_requested.emit(text)

    def _on_clear(self) -> None:
        """清空对话历史"""
        self._bubble_labels.clear()
        # 必须同步丢弃对已删子控件的引用，否则后续 add_message/show_typing 会访问悬空对象
        self._typing_indicator = None
        self._thinking_label = None
        self._last_bot_bubble = None
        self._agent_status_label = None
        while self.history_layout.count() > 1:  # 保留 stretch
            item = self.history_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._show_history_empty()

    def _show_history_empty(self) -> None:
        """清空后插入空态：标题 + 示例，避免一片死寂玻璃"""
        try:
            c = get_theme_colors()
            host = QWidget()
            host.setObjectName("historyEmpty")
            clear_container_bg(host)
            lay = QVBoxLayout(host)
            lay.setContentsMargins(18, 28, 18, 12)
            lay.setSpacing(8)
            lay.setAlignment(Qt.AlignCenter)
            title = QLabel("对话已清空")
            title.setAlignment(Qt.AlignCenter)
            title.setStyleSheet(
                f"color: {c['fg']}; font-size: {FONT_BODY}px; font-weight: 600;"
                f" background: transparent; border: none;"
            )
            hint = QLabel("和我打个招呼，或试试：帮我看看今天日程")
            hint.setAlignment(Qt.AlignCenter)
            hint.setWordWrap(True)
            hint.setStyleSheet(
                f"color: {c['fg_muted']}; font-size: {FONT_CAPTION}px;"
                f" background: transparent; border: none;"
            )
            lay.addWidget(title)
            lay.addWidget(hint)
            self.history_layout.insertWidget(0, host)
        except Exception as e:
            logger.error(f"空态插入异常: {e}")

    @staticmethod
    def _alive(w) -> bool:
        """控件仍有效（未被 deleteLater）才返回 True"""
        return w is not None and not sip.isdeleted(w)

    def add_message(self, text: str, is_user: bool = False, preserve_typing: bool = False) -> None:
        """添加一条消息到对话历史；preserve_typing=True 时不移除打字指示器（系统提示消息）"""
        # 移除打字指示器（除非要求保留，例如主题切换提示）
        if not preserve_typing and self._alive(self._typing_indicator):
            self._typing_indicator.hide()
            self._typing_indicator.deleteLater()
        if not preserve_typing:
            self._typing_indicator = None
        # 移除「思考中」过渡标签
        if self._alive(self._thinking_label):
            self._thinking_label.hide()
            self._thinking_label.deleteLater()
        self._thinking_label = None

        bubble = StyledBubble(text, is_user, self)
        # 约束宽度为视口宽度
        viewport_w = self.scroll_area.viewport().width() - 24
        if viewport_w > 60:
            bubble.setMaximumWidth(viewport_w)

        # 插入到 stretch 之前
        self.history_layout.insertWidget(self.history_layout.count() - 1, bubble)
        if not is_user:
            self._last_bot_bubble = bubble
        self._bubble_labels.append(bubble)

        # 消息上限保护：超过 100 条时移除最旧的
        MAX_MESSAGES = 100
        if self.history_layout.count() > MAX_MESSAGES + 1:
            item = self.history_layout.takeAt(0)
            if item and item.widget():
                if item.widget() in self._bubble_labels:
                    self._bubble_labels.remove(item.widget())
                item.widget().deleteLater()

        # 淡入动画：用 QGraphicsOpacityEffect（子控件上 windowOpacity 无效且易与特效冲突）
        eff = QGraphicsOpacityEffect(bubble)
        bubble.setGraphicsEffect(eff)
        fade_in = QPropertyAnimation(eff, b"opacity", bubble)
        fade_in.setDuration(220)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.OutCubic)
        fade_in.finished.connect(lambda b=bubble: _clear_bubble_effect(b))
        fade_in.start()

        # 平滑滚动到底部
        QTimer.singleShot(60, self._scroll_to_bottom)

    def show_typing_indicator(self) -> None:
        """显示打字指示器"""
        if self._alive(self._typing_indicator):
            return
        self._typing_indicator = None
        # 清除「思考中」标签
        if self._alive(self._thinking_label):
            self._thinking_label.deleteLater()
        self._thinking_label = None
        self._typing_indicator = TypingIndicator(self)
        self.history_layout.insertWidget(self.history_layout.count() - 1, self._typing_indicator)
        self._scroll_to_bottom()

    def _show_thinking(self) -> None:
        """发送后先显示「思考中」过渡，稍后转为打字指示器（P1 思考反馈）"""
        try:
            if self._alive(self._thinking_label):
                self._thinking_label.show()
            else:
                self._thinking_label = QLabel("思考中…")
                self._thinking_label.setStyleSheet(
                    f'color: {get_theme_colors()["fg_muted"]}; font-size: {FONT_CAPTION}px;'
                    f' background: {get_theme_colors()["btn_secondary"]};'
                    f' border-radius: {RADIUS_PILL}px; padding: 5px 14px;')
                self.history_layout.insertWidget(
                    self.history_layout.count() - 1, self._thinking_label)
                self._thinking_label.show()
            self._scroll_to_bottom()
            QTimer.singleShot(1200, self.show_typing_indicator)
        except Exception as e:
            logger.error(f"思考过渡异常: {e}")

    def replace_last_bot(self, text: str) -> None:
        """替换最后一条 bot 消息文本（兼容旧接口，已由 append_bot_reply 取代）"""
        if self._alive(getattr(self, '_last_bot_bubble', None)):
            self._last_bot_bubble.setText(text)
            self._last_bot_bubble._apply_text(text)

    def append_bot_reply(self, text: str) -> None:
        """追加一条 Bot 回复：有打字指示器则移除并新建气泡；
        若上一条已是 Bot 气泡（流式续写）则合并到该气泡，避免覆盖用户消息。"""
        try:
            if self._alive(self._typing_indicator):
                self.add_message(text, is_user=False)
                return
            self._typing_indicator = None
            # 无打字指示器：若最后一条是 Bot 气泡则合并（流式续写）
            last = None
            if self.history_layout.count() > 1:
                item = self.history_layout.itemAt(self.history_layout.count() - 2)
                if item and item.widget() and isinstance(item.widget(), StyledBubble):
                    last = item.widget()
            if self._alive(last) and not last._is_user:
                last.setText("")
                last._apply_text(text)
                QTimer.singleShot(60, self._scroll_to_bottom)
                return
            self.add_message(text, is_user=False)
        except Exception as e:
            logger.error(f"append_bot_reply 异常: {e}")

    def show_agent_status(self, text: str, done: bool = False) -> None:
        """在对话气泡顶部显示/更新 Agent 执行状态条（iOS 药丸样式）"""
        if sip.isdeleted(self):
            return
        if self._agent_status_label is None or sip.isdeleted(self._agent_status_label):
            self._agent_status_label = QLabel("")
            self._agent_status_label.setWordWrap(True)
            self._agent_status_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            self._agent_status_label.setContentsMargins(12, 7, 12, 7)
            # 插入到历史区最顶部（stretch 之前的第一个位置）
            self.history_layout.insertWidget(0, self._agent_status_label)
        c = get_theme_colors()
        if done:
            style = f"""
                QLabel {{
                    background: {c["status_done_bg"]};
                    color: {c["status_done_fg"]};
                    border: 1px solid {c["status_done_border"]};
                    border-radius: {RADIUS_PILL}px;
                    font-size: {FONT_CAPTION}px;
                    font-weight: 600;
                    padding: 6px 14px;
                }}
            """
        else:
            style = f"""
                QLabel {{
                    background: {c["status_running_bg"]};
                    color: {c["status_running_fg"]};
                    border: 1px solid {c["status_running_border"]};
                    border-radius: {RADIUS_PILL}px;
                    font-size: {FONT_CAPTION}px;
                    font-weight: 600;
                    padding: 6px 14px;
                }}
            """
        self._agent_status_label.setStyleSheet(style)
        self._agent_status_label.setText(text)
        self._agent_status_label.show()

    def clear_agent_status(self) -> None:
        """隐藏并清空 Agent 状态条"""
        if sip.isdeleted(self):
            return
        if self._agent_status_label is not None and not sip.isdeleted(self._agent_status_label):
            self._agent_status_label.hide()
            self._agent_status_label.setText("")

    def set_message(self, text: str) -> None:
        """兼容旧接口：作为 bot 回复追加"""
        self.add_message(text, is_user=False)


class SecretaryCard(QPushButton):
    """iOS 风格秘书舰卡片：圆角头像 + 名称 + 当前标记"""
    def __init__(self, key: str, name: str, active: bool = False, parent=None):
        super().__init__(parent)
        self.key = key
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(96, 108)
        self.setCheckable(False)

        c = get_theme_colors()
        card_bg = c["bot_bubble"] if not active else c["accent_glow"]
        card_border = c["bot_bubble_border"] if not active else c["accent"]
        self.setStyleSheet(f"""
            QPushButton {{
                background: {card_bg};
                border: 1.5px solid {card_border};
                border-radius: {RADIUS_CARD}px;
                color: {c["fg"]};
            }}
            QPushButton:hover {{
                background: {c["btn_secondary"]};
            }}
            QPushButton:pressed {{
                background: {c["accent_glow"]};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignCenter)

        # 圆角头像
        self.avatar = QLabel()
        self.avatar.setFixedSize(52, 52)
        self.avatar.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.avatar, 0, Qt.AlignCenter)

        self.name_label = QLabel(name)
        self.name_label.setAlignment(Qt.AlignCenter)
        self.name_label.setStyleSheet(
            f"background: transparent; border: none; color: {c['fg']}; font-size: {FONT_BODY}px; font-weight: 600;"
        )
        layout.addWidget(self.name_label)

        if active:
            badge = QLabel("● 当前")
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                f"background: {c['accent']}; color: white; border: none; "
                f"border-radius: {RADIUS_PILL}px; font-size: 14px; padding: 1px 8px;"
            )
            layout.addWidget(badge)

        self._load_avatar(key)

    def _load_avatar(self, key: str) -> None:
        """加载秘书舰立绘缩略图作为圆角头像"""
        try:
            path = get_skin_path(key)
            pixmap = QPixmap(path)
            if pixmap.isNull():
                return
            self.avatar.setPixmap(make_rounded_pixmap(pixmap, 52))
        except Exception:
            pass

    def _animate_geometry(self, target, duration=90):
        """几何缓动（按下缩小 / 松手回弹）"""
        try:
            anim = QPropertyAnimation(self, b"geometry", self)
            anim.setDuration(duration)
            anim.setStartValue(self.geometry())
            anim.setEndValue(target)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start()
            self._geo_anim = anim
        except Exception:
            pass

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        self._orig_geom = self.geometry()
        self._animate_geometry(self._orig_geom.adjusted(2, 2, -2, -2), 90)
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if getattr(self, "_orig_geom", None) is not None:
            self._animate_geometry(self._orig_geom, 140)
            self._orig_geom = None
        super().mouseReleaseEvent(event)

    def mouseLeaveEvent(self, event) -> None:  # type: ignore[override]
        # 移出时若已无按下（拖出后释放）也要恢复
        if not self.isDown() and getattr(self, "_orig_geom", None) is not None:
            self._animate_geometry(self._orig_geom, 140)
            self._orig_geom = None
        super().mouseLeaveEvent(event)


class SecretaryPanel(QFrame):
    """秘书舰切换面板 —— iOS 26 Liquid Glass 卡片网格"""
    secretary_selected = pyqtSignal(str)  # 发出选中的 secretary key
    manage_requested = pyqtSignal()       # 请求打开皮肤·语音管理

    DISPLAY_NAMES = {
        "enterprise": "企业", "shoukaku": "翔鹤", "newjersey": "新泽西",
        "hood": "胡德", "zuikaku": "瑞鹤", "essex": "埃塞克斯",
        "taihou": "大凤", "yorktown2": "约克城", "belfast": "贝尔法斯特",
        "anshan": "鞍山",
    }

    def __init__(self, current: str) -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.Tool | Qt.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setObjectName("secretaryPanel")
        self._apply_theme()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(GLASS_MARGIN, GLASS_MARGIN, GLASS_MARGIN, GLASS_MARGIN)
        layout.setSpacing(10)

        title = GradientTitleLabel("切换秘书舰", size=17)
        layout.addWidget(title)

        subtitle = QLabel("每天轮换 · 双击桌宠可切换换装")
        subtitle.setAlignment(Qt.AlignCenter)
        subtitle.setStyleSheet(f'color: {get_theme_colors()["fg_muted"]}; font-size: {FONT_CAPTION}px; border: none;')
        layout.addWidget(subtitle)

        grid = QHBoxLayout()
        grid.setSpacing(8)
        cols = [QVBoxLayout() for _ in range(3)]
        for c in cols:
            c.setSpacing(8)

        self.cards: dict[str, SecretaryCard] = {}
        for i, (key, name) in enumerate(self.DISPLAY_NAMES.items()):
            card = SecretaryCard(key, name, active=(key == current))
            card.clicked.connect(lambda checked, k=key: self._select(k))
            self.cards[key] = card
            cols[i % 3].addWidget(card)

        for c in cols:
            grid.addLayout(c)
        layout.addLayout(grid)

        self.manage_btn = QPushButton("皮肤 · 语音 · 台词管理")
        self.manage_btn.setProperty("secondary", "true")
        self.manage_btn.setCursor(Qt.PointingHandCursor)
        self.manage_btn.clicked.connect(self.manage_requested.emit)
        layout.addWidget(self.manage_btn)

        # 高度随秘书舰数量自适应（每张卡片 96x108，行距 8）
        n = len(self.DISPLAY_NAMES)
        rows = (n + 2) // 3
        grid_h = rows * 108 + (rows - 1) * 8
        panel_h = grid_h + 166  # 标题/副标题/管理按钮/边距
        self.resize(336 + GLASS_MARGIN * 2, panel_h + GLASS_MARGIN * 2)

        # 窗口淡入淡出
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(300)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self.setWindowOpacity(1.0)

    def _apply_theme(self) -> None:
        """应用主题样式"""
        self.setStyleSheet(theme_stylesheet())

    def paintEvent(self, event) -> None:  # type: ignore[override]
        """自绘 iOS 26 Liquid Glass 玻璃卡片"""
        try:
            painter = QPainter(self)
            card = self.rect().adjusted(GLASS_MARGIN, GLASS_MARGIN,
                                        -GLASS_MARGIN, -GLASS_MARGIN)
            if card.width() <= 0 or card.height() <= 0:
                return
            paint_liquid_glass(painter, card, tier="panel")
        except Exception as e:
            logger.error(f"SecretaryPanel.paintEvent 异常: {e}")

    def showEvent(self, event) -> None:  # type: ignore[override]
        try:
            super().showEvent(event)
            # 玻璃观感由 paintEvent 自绘，无需系统亚克力
        except Exception as e:
            logger.error(f"SecretaryPanel.showEvent 异常: {e}")

    def _apply_glass(self) -> None:
        """兼容占位：玻璃观感由 paintEvent 自绘，无需系统亚克力"""
        try:
            self._glass_pending = False
        except Exception:
            pass

    def moveEvent(self, event) -> None:  # type: ignore[override]
        try:
            super().moveEvent(event)
        except Exception as e:
            logger.error(f"SecretaryPanel.moveEvent 异常: {e}")

    def refresh_active(self, current: str) -> None:
        """切换后刷新当前标记"""
        for key, card in self.cards.items():
            is_active = (key == current)
            c = get_theme_colors()
            card.setStyleSheet(f"""
                QPushButton {{
                    background: {c["accent_glow"] if is_active else c["bot_bubble"]};
                    border: 1.5px solid {c["accent"] if is_active else c["bot_bubble_border"]};
                    border-radius: {RADIUS_CARD}px;
                    color: {c["fg"]};
                }}
                QPushButton:hover {{ background: {c["btn_secondary"]}; }}
                QPushButton:pressed {{ background: {c["accent_glow"]}; }}
            """)

    def show(self) -> None:  # type: ignore[override]
        try:
            self._fade.stop()
            try:
                self._fade.finished.disconnect()
            except TypeError:
                pass
            super().show()
            self._fade.setStartValue(0.0)
            self._fade.setEndValue(1.0)
            self._fade.setEasingCurve(QEasingCurve.OutBack)
            self._fade.start()
        except Exception as e:
            logger.error(f"SecretaryPanel.show 异常: {e}")

    def hide(self) -> None:  # type: ignore[override]
        try:
            if not self.isVisible():
                return
            self._fade.stop()
            try:
                self._fade.finished.disconnect()
            except TypeError:
                pass
            self._fade.setStartValue(self.windowOpacity())
            self._fade.setEndValue(0.0)
            self._fade.finished.connect(super().hide)
            self._fade.start()
        except Exception as e:
            logger.error(f"SecretaryPanel.hide 异常: {e}")

    def _select(self, key: str) -> None:
        self.secretary_selected.emit(key)
        self.hide()


# ── 精进功能：玻璃风格对话框（日程） ──
def clear_container_bg(w) -> None:
    """容器自身透明：选择器限定属性，禁止无选择器 border:none 级联抹掉子控件样式"""
    try:
        w.setProperty("bgClear", "true")
        w.setStyleSheet('[bgClear="true"] { background: transparent; border: none; }')
    except Exception:
        pass


class GlassDialog(QDialog):
    """iOS 26 玻璃风格无边框对话框：自绘玻璃卡片、可拖动、淡入"""

    def __init__(self, title: str, width: int = 460, height: int = 520, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setObjectName("glassDialog")
        self.resize(width, height)
        self._drag_pos = None
        self._fade_anim: Optional[QPropertyAnimation] = None
        # 标题距卡片边：加大内边距，避免标题贴边
        self._inset = GLASS_MARGIN + 8

        root = QVBoxLayout(self)
        root.setContentsMargins(self._inset, self._inset, self._inset, self._inset)
        root.setSpacing(12)

        header = QHBoxLayout()
        header.setContentsMargins(4, 6, 0, 6)
        header.setSpacing(8)
        title_label = GradientTitleLabel(title, size=17,
                                         align=Qt.AlignLeft | Qt.AlignVCenter)
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(30, 30)
        close_btn.setProperty("secondary", "true")
        close_btn.setToolTip("关闭")
        close_btn.clicked.connect(self.reject)
        header.addWidget(title_label, 1)
        header.addWidget(close_btn)
        root.addLayout(header)

        self._body = QVBoxLayout()
        self._body.setSpacing(8)
        root.addLayout(self._body, 1)
        self.setStyleSheet(theme_stylesheet())

    def paintEvent(self, event):  # type: ignore[override]
        try:
            painter = QPainter(self)
            m = self._inset
            card = self.rect().adjusted(m, m, -m, -m)
            if card.width() <= 0 or card.height() <= 0:
                return
            paint_liquid_glass(painter, card, tier="panel")
        except Exception as e:
            logger.error(f"GlassDialog.paintEvent 异常: {e}")

    def mousePressEvent(self, event):  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._drag_pos = event.globalPos() - self.frameGeometry().topLeft()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[override]
        if self._drag_pos is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPos() - self._drag_pos)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # type: ignore[override]
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def showEvent(self, event):  # type: ignore[override]
        try:
            super().showEvent(event)
            _disable_dwm_transitions(self)
            # 淡入：与右键菜单同一套出场节奏
            if self._fade_anim is not None:
                self._fade_anim.stop()
            self.setWindowOpacity(0.0)
            anim = QPropertyAnimation(self, b"windowOpacity", self)
            anim.setDuration(200)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.start(QAbstractAnimation.DeleteWhenStopped)
            self._fade_anim = anim
        except Exception:
            pass


# ── 日程对话框 ──


def _fmt_schedule_when(when: str) -> str:
    """把存储格式转为友好显示：'每天 08:00' / '今天 09:00' / '明天 09:00' / '09-25 09:00'"""
    when = (when or "").strip()
    if " " in when and len(when) >= 16:
        d, t = when.split(" ", 1)
        try:
            date = datetime.datetime.strptime(d, "%Y-%m-%d").date()
            today = datetime.date.today()
            delta = (date - today).days
            if delta == 0:
                prefix = "今天"
            elif delta == 1:
                prefix = "明天"
            elif delta == 2:
                prefix = "后天"
            else:
                prefix = date.strftime("%m-%d")
            return f"{prefix} {t}"
        except Exception:
            return when
    return f"每天 {when}"


class _ScheduleCard(QFrame):
    """时间线行程卡：完成勾选 + 时间胶囊 + 文案 + 行内编辑/删除"""

    def __init__(self, rec: dict, when_label: str, done: bool, on_change, parent=None):
        super().__init__(parent)
        self.rec = rec
        self._on_change = on_change
        self._editing = False
        c = get_theme_colors()
        self.setStyleSheet(
            f"QFrame {{ background: {c['btn_secondary']}; border: 1px solid {c['border']};"
            f" border-radius: {RADIUS_CARD}px; }}"
            f" QFrame:hover {{ border-color: {c['accent_glow']}; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 6, 6)
        lay.setSpacing(8)

        self.check = QCheckBox()
        self.check.setChecked(done)
        self.check.setToolTip("标记今日已完成" if not done else "取消完成")
        self.check.setFixedSize(20, 20)
        self.check.setStyleSheet(
            f"QCheckBox {{ background: transparent; border: none; }}"
                f"QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: {RADIUS_CARD}px;"
            f" border: 1.5px solid {c['fg_muted']}; background: transparent; }}"
            f"QCheckBox::indicator:hover {{ border-color: {c['accent']}; }}"
            f"QCheckBox::indicator:checked {{ background: {c['accent']};"
            f" border: 1.5px solid {c['accent']}; }}"
        )
        self.check.toggled.connect(self._on_toggled)
        lay.addWidget(self.check)

        badge = QLabel(when_label)
        badge.setStyleSheet(
            f"color: {c['accent']}; background: {c['accent_glow']};"
            f" font-size: {FONT_CAPTION}px; font-weight: 600;"
            f" border-radius: {RADIUS_PILL}px; padding: 3px 9px; border: none;"
        )
        lay.addWidget(badge)

        self.text_label = QLabel(rec.get("text", ""))
        self.text_label.setStyleSheet(
            f"color: {c['fg']}; background: transparent; border: none;"
            f" font-size: {FONT_BODY}px;"
        )
        self.text_label.setMinimumWidth(0)
        self.text_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        if done:
            f = self.text_label.font()
            f.setStrikeOut(True)
            self.text_label.setFont(f)
            self.text_label.setStyleSheet(
                f"color: {c['fg_muted']}; background: transparent; border: none;"
                f" font-size: {FONT_BODY}px;"
            )
        lay.addWidget(self.text_label, 1)

        self.edit_btn = QPushButton("编辑")
        self.edit_btn.setProperty("secondary", "true")
        self.edit_btn.setCursor(Qt.PointingHandCursor)
        self.edit_btn.setFixedHeight(26)
        self.edit_btn.setStyleSheet(
            f"QPushButton {{ font-size: {FONT_CAPTION}px; padding: 0 8px; }}"
        )
        self.edit_btn.setToolTip("编辑（双击文字也可）")
        self.edit_btn.clicked.connect(self._begin_edit)
        lay.addWidget(self.edit_btn)

        del_btn = IconButton("x", "删除此日程", size=26)
        del_btn.clicked.connect(lambda: self._on_change("delete", self.rec.get("id")))
        lay.addWidget(del_btn)

        self.text_label.installEventFilter(_DoubleTapFilter(self, self._begin_edit))
        self.setFixedHeight(44)

    def _on_toggled(self, checked: bool) -> None:
        self._on_change("done", self.rec.get("id"), checked)

    def _begin_edit(self) -> None:
        if self._editing:
            return
        self._editing = True
        lay = self.layout()
        edit = QLineEdit(self.rec.get("text", ""))
        edit.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none;"
            f" color: {get_theme_colors()['fg']}; font-size: {FONT_BODY}px; }}"
        )
        edit.setMinimumWidth(80)
        lay.replaceWidget(self.text_label, edit)
        self.text_label.hide()
        edit.setFocus()
        edit.selectAll()

        state = {"done": False}

        def commit(ok: bool):
            if state["done"]:
                return
            state["done"] = True
            text = edit.text().strip()
            self._editing = False
            lay.replaceWidget(edit, self.text_label)
            edit.deleteLater()
            self.text_label.show()
            if ok and text and text != self.rec.get("text"):
                self._on_change("rename", self.rec.get("id"), text)

        edit.returnPressed.connect(lambda: commit(True))
        edit.editingFinished.connect(lambda: commit(True))
        edit.installEventFilter(_EscFilter(edit, lambda: commit(False)))


class _DoubleTapFilter(QObject):
    def __init__(self, target, on_double):
        super().__init__(target)
        self._on_double = on_double

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
            self._on_double()
            return True
        return False


class _EscFilter(QObject):
    def __init__(self, target, on_esc):
        super().__init__(target)
        self._on_esc = on_esc

    def eventFilter(self, obj, event):
        if event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self._on_esc()
            return True
        return False


class ScheduleDialog(GlassDialog):
    """日程：自然语言快速添加 + 时间线分组（今天/明天/更晚/每天），支持完成与行内编辑"""

    def __init__(self, mgr, parent=None):
        super().__init__("日程", 540, 620, parent)
        self.mgr = mgr
        c = get_theme_colors()

        # ── 添加区：自然语言单栏 + 实时解析 ──
        composer = QHBoxLayout()
        composer.setSpacing(8)
        self.text_edit = QLineEdit()
        self.text_edit.setPlaceholderText("明天早上9点 交报告 / 每天8:00 打卡…")
        self.text_edit.setClearButtonEnabled(True)
        self.text_edit.returnPressed.connect(self._on_add_inline)
        add_btn = QPushButton("添加")
        add_btn.setProperty("primary", "true")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._on_add_inline)
        composer.addWidget(self.text_edit, 1)
        composer.addWidget(add_btn)
        self._body.addLayout(composer)

        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setStyleSheet(
            f'color: {c["fg_muted"]}; font-size: {FONT_CAPTION}px; border: none;'
        )
        self._body.addWidget(self.preview)
        self.text_edit.textChanged.connect(self._update_preview)

        # ── 时间线滚动区 ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }"
                             "QScrollBar { background: transparent; width: 8px; }"
                             "QScrollBar::handle:vertical { background: "
                             f"{c['btn_secondary']}; border-radius: 4px; min-height: 30px; }}"
                             "QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}")
        self.timeline = QWidget()
        clear_container_bg(self.timeline)
        self.timeline_lay = QVBoxLayout(self.timeline)
        self.timeline_lay.setContentsMargins(0, 4, 0, 4)
        self.timeline_lay.setSpacing(4)
        scroll.setWidget(self.timeline)
        self._body.addWidget(scroll, 1)
        self.refresh()
        self._update_preview("")

    # ── 解析 / 预览 ──

    def _update_preview(self, text: str = ""):
        t = (text or self.text_edit.text()).strip()
        c = get_theme_colors()
        if not t:
            self.preview.setText("支持「明天早上9点 开会」「每天8:00 打卡」「今晚10点 睡觉」")
            self.preview.setStyleSheet(
                f'color: {c["fg_muted"]}; font-size: {FONT_CAPTION}px; border: none;')
            return
        parsed = parse_schedule_nl(t)
        if parsed:
            when, content = parsed
            self.preview.setText(f"✓ {_fmt_schedule_when(when)} · {content}")
            self.preview.setStyleSheet(
                f'color: {c["accent"]}; font-size: {FONT_CAPTION}px; border: none;')
        else:
            self.preview.setText("⚠ 无法识别时间 — 试试「明天9点 开会」或「每天8:00 打卡」")
            self.preview.setStyleSheet(
                f'color: {c.get("btn_danger", "#e05252")}; '
                f'font-size: {FONT_CAPTION}px; border: none;')

    def _on_add_inline(self):
        t = self.text_edit.text().strip()
        if not t:
            return
        parsed = parse_schedule_nl(t)
        if not parsed:
            self._update_preview(t)
            return
        when, content = parsed
        self.mgr.add(content, when)
        self.text_edit.clear()
        self.refresh()
        self._update_preview("")

    # ── 时间线渲染 ──

    @staticmethod
    def _group_key(when: str) -> str:
        when = (when or "").strip()
        if " " in when and len(when) >= 16:
            d = when.split(" ", 1)[0]
            try:
                date = datetime.datetime.strptime(d, "%Y-%m-%d").date()
                delta = (date - datetime.date.today()).days
            except Exception:
                return "更晚"
            if delta <= 0:
                return "今天"
            if delta == 1:
                return "明天"
            return "更晚"
        return "每天"

    @staticmethod
    def _is_done(rec: dict) -> bool:
        when = rec.get("when", "")
        if " " in when and len(when) >= 16:
            return bool(rec.get("fired"))
        today = datetime.date.today().strftime("%Y-%m-%d")
        return rec.get("last_fired_date", "") == today

    def _clear_layout(self, lay):
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _group_header(self, title: str, count: int) -> QWidget:
        c = get_theme_colors()
        w = QWidget()
        clear_container_bg(w)
        h = QHBoxLayout(w)
        h.setContentsMargins(2, 10, 0, 2)
        h.setSpacing(8)
        dot = QLabel()
        dot.setFixedSize(8, 8)
        dot.setStyleSheet(
            f"background: {c['accent']}; border-radius: 4px; border: none;"
        )
        lab = QLabel(title)
        lab.setStyleSheet(
            f"color: {c['fg']}; font-size: {FONT_SECTION}px; font-weight: 700;"
            f" border: none; background: transparent;"
        )
        cnt = QLabel(str(count))
        cnt.setStyleSheet(
            f"color: {c['fg_muted']}; font-size: {FONT_CAPTION}px; border: none;"
            f" background: transparent;"
        )
        h.addWidget(dot)
        h.addWidget(lab)
        h.addWidget(cnt)
        h.addStretch(1)
        return w

    def refresh(self):
        self._clear_layout(self.timeline_lay)
        records = self.mgr.list()
        if not records:
            empty = QWidget()
            empty = QWidget()
            clear_container_bg(empty)
            el = QVBoxLayout(empty)
            el.setContentsMargins(0, 36, 0, 0)
            el.setSpacing(6)
            e1 = QLabel("还没有日程")
            e1.setAlignment(Qt.AlignCenter)
            c = get_theme_colors()
            e1.setStyleSheet(
                f"color: {c['fg']}; font-size: {FONT_BODY}px; font-weight: 600;"
                f" border: none; background: transparent;"
            )
            e2 = QLabel("在上方输入，例如「明天9点 交报告」")
            e2.setAlignment(Qt.AlignCenter)
            e2.setStyleSheet(
                f"color: {c['fg_muted']}; font-size: {FONT_CAPTION}px; border: none;"
                f" background: transparent;"
            )
            el.addWidget(e1)
            el.addWidget(e2)
            self.timeline_lay.addWidget(empty)
            self.timeline_lay.addStretch(1)
            return

        order = ["今天", "明天", "更晚", "每天"]
        groups: dict = {k: [] for k in order}
        for r in records:
            groups.setdefault(self._group_key(r.get("when", "")), []).append(r)

        # 排序：今天/明天/更晚按时间，每天按钟点
        def sort_key(r):
            w = r.get("when", "")
            return w if " " in w else f"9999 {w}"

        first = True
        for key in order:
            items = groups.get(key) or []
            if not items:
                continue
            items.sort(key=sort_key)
            if not first:
                self.timeline_lay.addSpacing(2)
            first = False
            self.timeline_lay.addWidget(self._group_header(key, len(items)))
            for r in items:
                card = _ScheduleCard(
                    r, _fmt_schedule_when(r.get("when", "")),
                    self._is_done(r), self._on_card_action,
                )
                self.timeline_lay.addWidget(card)
        self.timeline_lay.addStretch(1)

    def _on_card_action(self, action: str, rid, arg=None):
        if not rid:
            return
        if action == "delete":
            self.mgr.delete(rid)
        elif action == "done":
            self.mgr.set_done(rid, bool(arg))
        elif action == "rename":
            self.mgr.rename(rid, str(arg))
        self.refresh()


# ── 设置卡片：圆角玻璃卡片 + label/control 行 ──
class ToggleSwitch(QWidget):
    """iOS 拨杆开关：轨道+滑块，形状即状态（开/关一眼可辨）"""
    toggled = pyqtSignal(bool)

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = bool(checked)
        self._pos = 1.0 if self._checked else 0.0
        self.setFixedSize(52, 30)
        self.setCursor(Qt.PointingHandCursor)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._on_anim)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, v: bool) -> None:
        v = bool(v)
        if v == self._checked:
            return
        self._checked = v
        self._animate_to(v)

    def _animate_to(self, v: bool) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if v else 0.0)
        self._anim.start()

    def _on_anim(self, val) -> None:
        self._pos = float(val)
        self.update()

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.LeftButton:
            self._checked = not self._checked
            self._animate_to(self._checked)
            self.toggled.emit(self._checked)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        try:
            c = get_theme_colors()
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            r = self.rect()
            on = _hex_to_qcolor(c["accent"])
            off = _hex_to_qcolor(c.get("btn_secondary", "rgba(120,120,128,0.3)"))
            t = self._pos
            track = QColor(
                int(off.red() + (on.red() - off.red()) * t),
                int(off.green() + (on.green() - off.green()) * t),
                int(off.blue() + (on.blue() - off.blue()) * t),
                int(off.alpha() + (on.alpha() - off.alpha()) * t),
            )
            p.setPen(Qt.NoPen)
            p.setBrush(track)
            p.drawRoundedRect(r, r.height() // 2, r.height() // 2)
            # 轨道描边保证关态在玻璃上可辨
            p.setPen(QPen(_hex_to_qcolor(c["border_light"]), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r.adjusted(0, 0, -1, -1), r.height() // 2, r.height() // 2)
            # 滑块
            m = 3
            d = r.height() - 2 * m
            cx = m + d / 2 + (r.width() - 2 * m - d) * t
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffffff"))
            p.drawEllipse(QPointF(cx, r.height() / 2), d / 2, d / 2)
            p.end()
        except Exception as e:
            logger.error(f"ToggleSwitch.paintEvent 异常: {e}")


class SegmentButton(QPushButton):
    """设置分段按钮：矢量图标 + 文字，自绘胶囊；选中实底、悬停微底——状态自明"""

    def __init__(self, text: str, icon_kind: str = "", parent=None):
        super().__init__(text, parent)
        self._kind = icon_kind
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedHeight(38)
        self.setMinimumWidth(104)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        try:
            c = get_theme_colors()
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            r = self.rect()
            checked = self.isChecked()
            hot = self.underMouse()
            rad = r.height() // 2
            if checked:
                p.setPen(Qt.NoPen)
                p.setBrush(_hex_to_qcolor(c["btn_primary"]))
                p.drawRoundedRect(r, rad, rad)
                fg, icon_col = "#ffffff", "#ffffff"
            elif hot:
                p.setPen(Qt.NoPen)
                p.setBrush(_hex_to_qcolor(c["btn_secondary"]))
                p.drawRoundedRect(r, rad, rad)
                fg, icon_col = c["fg"], c["fg"]
            else:
                fg, icon_col = c["fg_muted"], c["fg_muted"]
            f = self.font()
            f.setPixelSize(FONT_BODY)
            f.setWeight(600 if checked else 500)
            p.setFont(f)
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(self.text())
            icon_sz, gap = 16, 7
            total = (icon_sz + gap + tw) if self._kind else tw
            x0 = r.left() + max(8, (r.width() - total) // 2)
            cy = r.center().y()
            if self._kind:
                irect = QRect(x0, cy - icon_sz // 2, icon_sz, icon_sz)
                _draw_icon_path(p, self._kind, irect, icon_col,
                                stroke=1.9 * 20.0 / icon_sz)
                x0 += icon_sz + gap
            p.setPen(_hex_to_qcolor(fg))
            p.drawText(QRect(x0, r.top(), tw + 6, r.height()),
                       Qt.AlignVCenter | Qt.AlignLeft, self.text())
            p.end()
        except Exception as e:
            logger.error(f"SegmentButton.paintEvent 异常: {e}")


class FormCard(QFrame):
    """form-card 风格设置分组：透明底 + accent 点标题 + 发丝分隔线（不嵌套卡片）"""
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setStyleSheet("""
            QFrame { background: transparent; border: none; }
            QLabel { background: transparent; border: none; }
        """)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(4, 10, 4, 6)
        self._lay.setSpacing(10)
        c = get_theme_colors()
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._dot = QLabel()
        self._dot.setFixedSize(7, 7)
        self._dot.setStyleSheet(f"background: {c['accent']}; border-radius: 3px; border: none;")
        self._title_lab = QLabel(title)
        self._title_lab.setStyleSheet(
            f"color: {c['fg_muted']}; font-size: {FONT_CAPTION}px; "
            f"font-weight: 600; border: none;"
        )
        title_row.addWidget(self._dot)
        title_row.addWidget(self._title_lab)
        title_row.addStretch(1)
        self._lay.addLayout(title_row)
        self._seps: list[QFrame] = []
        self._row_labs: list[QLabel] = []

    def refresh_theme(self) -> None:
        """主题切换后刷新本卡片内烘焙的颜色"""
        try:
            c = get_theme_colors()
            self._dot.setStyleSheet(
                f"background: {c['accent']}; border-radius: 3px; border: none;")
            self._title_lab.setStyleSheet(
                f"color: {c['fg_muted']}; font-size: {FONT_CAPTION}px; "
                f"font-weight: 600; border: none;"
            )
            for sep in self._seps:
                if not sip.isdeleted(sep):
                    sep.setStyleSheet(
                        f'background: {c["border"]}; border: none;')
            for lab in self._row_labs:
                if not sip.isdeleted(lab):
                    lab.setStyleSheet(
                        f'color: {c["fg_muted"]}; font-size: {FONT_CAPTION}px; border: none;'
                    )
            self.update()
        except Exception:
            pass

    def add_row(self, label: str | None, widget) -> None:
        """添加一行：label 左 + 控件右（iOS 设置行），首行前不加分隔线"""
        if self._lay.count() > 1:  # 标题之后的行都带发丝分隔线
            sep = QFrame()
            sep.setFixedHeight(1)
            sep.setStyleSheet(f'background: {get_theme_colors()["border"]}; border: none;')
            self._lay.addWidget(sep)
            self._seps.append(sep)
        row = QHBoxLayout()
        row.setSpacing(12)
        if label:
            lab = QLabel(label)
            lab.setStyleSheet(
                f'color: {get_theme_colors()["fg_muted"]}; font-size: {FONT_CAPTION}px; border: none;'
            )
            self._row_labs.append(lab)
            row.addWidget(lab)
        row.addStretch(1)
        row.addWidget(widget)
        self._lay.addLayout(row)

    def add_widget(self, widget) -> None:
        self._lay.addWidget(widget)

    def add_layout(self, layout) -> None:
        self._lay.addLayout(layout)


class SettingsDialog(GlassDialog):
    """设置面板：分段导航（图标+文字）+ 设置行，底部脏状态感知的操作区"""

    def __init__(self, pet, parent=None):
        super().__init__("设置", 520, 470, parent)
        self.pet = pet
        self._dirty = False
        cfg = load_config()

        # ── 分段控制（Segmented Control：图标 + 文字）──
        self._segment_bar = QWidget()
        clear_container_bg(self._segment_bar)
        seg_layout = QHBoxLayout(self._segment_bar)
        seg_layout.setContentsMargins(0, 0, 0, 8)
        seg_layout.setSpacing(4)
        self._segment_group = QButtonGroup(self)
        self._segment_group.setExclusive(True)
        self._stack = QStackedWidget()
        self._segment_buttons: list[SegmentButton] = []

        # ── 外观卡片 ──
        self._form_cards: list[FormCard] = []
        self.theme_combo = QComboBox()
        for key, preset in THEME_PRESETS.items():
            self.theme_combo.addItem(preset["name"], key)
        idx = self.theme_combo.findData(get_current_theme())
        self.theme_combo.setCurrentIndex(max(0, idx))

        self.scale_combo = QComboBox()
        for val in SCALE_STEPS:
            self.scale_combo.addItem(SCALE_LABELS[val], round(val, 2))
        cur = self.scale_combo.findData(round(pet.user_scale, 2))
        if cur < 0:
            # 非精确档位：就近吸附
            cur = min(range(len(SCALE_STEPS)),
                      key=lambda i: abs(SCALE_STEPS[i] - pet.user_scale))
        self.scale_combo.setCurrentIndex(max(0, cur))

        page_appearance = QWidget()
        clear_container_bg(page_appearance)
        v = QVBoxLayout(page_appearance)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        card_appearance = FormCard("外观")
        self._form_cards.append(card_appearance)
        card_appearance.add_row("主题（立即生效，单选）", self.theme_combo)
        card_appearance.add_row("缩放比例", self.scale_combo)
        v.addWidget(card_appearance)
        v.addStretch(1)
        self._stack.addWidget(page_appearance)
        self._add_segment("外观", page_appearance, "palette")

        # ── 行为卡片（拨杆开关，状态自明）──
        self.lock_toggle = ToggleSwitch(pet.locked)
        self.auto_toggle = ToggleSwitch(DesktopPet._is_auto_start())

        page_behavior = QWidget()
        clear_container_bg(page_behavior)
        v2 = QVBoxLayout(page_behavior)
        v2.setContentsMargins(0, 0, 0, 0)
        v2.setSpacing(8)
        card_behavior = FormCard("行为")
        self._form_cards.append(card_behavior)
        card_behavior.add_row("锁定位置（防止拖动）", self.lock_toggle)
        card_behavior.add_row("开机自启动", self.auto_toggle)
        v2.addWidget(card_behavior)
        v2.addStretch(1)
        self._stack.addWidget(page_behavior)
        self._add_segment("行为", page_behavior, "sliders")

        # ── 番茄钟卡片 ──
        self.work_spin = QSpinBox()
        self.work_spin.setRange(1, 120)
        self.work_spin.setValue(self.pet.pomodoro._work_minutes)
        self.work_spin.setSuffix(" 分钟")
        self.break_spin = QSpinBox()
        self.break_spin.setRange(1, 120)
        self.break_spin.setValue(self.pet.pomodoro._break_minutes)
        self.break_spin.setSuffix(" 分钟")

        page_pomodoro = QWidget()
        clear_container_bg(page_pomodoro)
        v3 = QVBoxLayout(page_pomodoro)
        v3.setContentsMargins(0, 0, 0, 0)
        v3.setSpacing(8)
        card_pomodoro = FormCard("番茄钟")
        self._form_cards.append(card_pomodoro)
        card_pomodoro.add_row("工作时长", self.work_spin)
        card_pomodoro.add_row("休息时长", self.break_spin)
        v3.addWidget(card_pomodoro)
        v3.addStretch(1)
        self._stack.addWidget(page_pomodoro)
        self._add_segment("番茄钟", page_pomodoro, "timer")

        # ── 主动回话卡片（频率/概率 + 截图质量）──
        self.proactive_prob_spin = QSpinBox()
        self.proactive_prob_spin.setRange(0, 100)
        self.proactive_prob_spin.setSuffix(" %")
        self.proactive_prob_spin.setValue(int(round(pet._proactive_probability * 100)))
        self.proactive_min_spin = QSpinBox()
        self.proactive_min_spin.setRange(10, 3600)
        self.proactive_min_spin.setSuffix(" 秒")
        self.proactive_min_spin.setValue(pet._proactive_min_interval)
        self.proactive_max_spin = QSpinBox()
        self.proactive_max_spin.setRange(10, 7200)
        self.proactive_max_spin.setSuffix(" 秒")
        self.proactive_max_spin.setValue(pet._proactive_max_interval)
        self.quality_spin = QSpinBox()
        self.quality_spin.setRange(10, 100)
        self.quality_spin.setSuffix(" %")
        self.quality_spin.setValue(pet._screenshot_quality)

        page_proactive = QWidget()
        clear_container_bg(page_proactive)
        v4 = QVBoxLayout(page_proactive)
        v4.setContentsMargins(0, 0, 0, 0)
        v4.setSpacing(8)
        card_proactive = FormCard("主动回话")
        self._form_cards.append(card_proactive)
        card_proactive.add_row("触发概率", self.proactive_prob_spin)
        card_proactive.add_row("最小间隔", self.proactive_min_spin)
        card_proactive.add_row("最大间隔", self.proactive_max_spin)
        card_proactive.add_row("感知截图质量", self.quality_spin)
        hint = QLabel("保存后立即生效并同步服务端；开启「感知」后桌宠才会主动说话")
        hint.setWordWrap(True)
        hint.setStyleSheet(f'color: {get_theme_colors()["fg_muted"]}; font-size: {FONT_CAPTION}px; border: none;')
        v4.addWidget(card_proactive)
        v4.addWidget(hint)
        v4.addStretch(1)
        self._stack.addWidget(page_proactive)
        self._add_segment("主动回话", page_proactive, "chat")

        seg_layout.addStretch(1)
        for b in self._segment_buttons:
            seg_layout.addWidget(b)
        seg_layout.addStretch(1)

        self._body.addWidget(self._segment_bar)
        self._body.addWidget(self._stack)
        self._build_actions()
        self._wire_dirty()

    def _add_segment(self, label: str, page, icon_kind: str = "") -> None:
        """添加分段按钮（图标+文字），点击切换到对应层"""
        btn = SegmentButton(label, icon_kind)
        btn.setChecked(not self._segment_buttons)
        self._segment_group.addButton(btn)
        self._segment_buttons.append(btn)
        idx = len(self._segment_buttons) - 1
        btn.clicked.connect(lambda checked=False, i=idx: self._stack.setCurrentIndex(i))

    def _build_actions(self) -> None:
        """底部操作区：取消 / 保存（无改动时保存置灰）"""
        actions = QHBoxLayout()
        actions.addStretch(1)
        cancel_btn = QPushButton("取消")
        cancel_btn.setProperty("secondary", "true")
        cancel_btn.setCursor(Qt.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        self._save_btn = QPushButton("保存")
        self._save_btn.setProperty("primary", "true")
        self._save_btn.setCursor(Qt.PointingHandCursor)
        self._save_btn.clicked.connect(self._on_save)
        actions.addWidget(cancel_btn)
        actions.addWidget(self._save_btn)
        self._body.addLayout(actions)
        # 脏状态呼吸：有改动时保存按钮轻微呼吸提示
        self._breath_eff = QGraphicsOpacityEffect(self._save_btn)
        self._save_btn.setGraphicsEffect(self._breath_eff)
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(750)
        self._breath_on = True
        self._breath_timer.timeout.connect(self._breath_tick)
        # 保存成功确认条（短光效，不打断流程）
        c_now = get_theme_colors()
        self._saved_flash = QLabel("")
        self._saved_flash.setAlignment(Qt.AlignCenter)
        self._saved_flash.hide()
        self._body.addWidget(self._saved_flash)
        self._saved_flash_timer = QTimer(self)
        self._saved_flash_timer.setSingleShot(True)
        self._saved_flash_timer.setInterval(1400)
        self._saved_flash_timer.timeout.connect(self._saved_flash.hide)

    def _wire_dirty(self) -> None:
        """主题即选即生效（不关窗、不进脏状态）；其余控件变化 → 脏状态"""
        self.theme_combo.currentIndexChanged.connect(self._on_theme_combo)
        self.scale_combo.currentIndexChanged.connect(lambda *_: self._set_dirty(True))
        self.lock_toggle.toggled.connect(lambda *_: self._set_dirty(True))
        self.auto_toggle.toggled.connect(lambda *_: self._set_dirty(True))
        for sp in (self.work_spin, self.break_spin, self.proactive_prob_spin,
                   self.proactive_min_spin, self.proactive_max_spin, self.quality_spin):
            sp.valueChanged.connect(lambda *_: self._set_dirty(True))
        self._set_dirty(False)

    def _on_theme_combo(self, index: int = -1) -> None:
        """外观·主题：单选下拉，选中即应用并保持窗口打开（不进脏状态）"""
        key = self.theme_combo.currentData()
        if not key or key == get_current_theme():
            return
        try:
            self.pet._apply_theme_preset(key, announce=False)
            self._refresh_theme_styles()
        except Exception as e:
            logger.error(f"主题即时应用失败: {e}")

    def _refresh_theme_styles(self) -> None:
        """主题切换后刷新本对话框与分段/卡片烘焙色"""
        try:
            self.setStyleSheet(theme_stylesheet())
            for card in getattr(self, "_form_cards", []):
                card.refresh_theme()
            for b in getattr(self, "_segment_buttons", []):
                b.update()
            self.update()
        except Exception as e:
            logger.error(f"设置窗主题刷新失败: {e}")

    def _set_dirty(self, d: bool) -> None:
        self._dirty = d
        self._save_btn.setEnabled(d)
        if d and not self._breath_timer.isActive():
            self._breath_on = True
            self._breath_eff.setOpacity(1.0)
            self._breath_timer.start()
        elif not d:
            self._breath_timer.stop()
            self._breath_eff.setOpacity(1.0)

    def _breath_tick(self) -> None:
        self._breath_on = not self._breath_on
        self._breath_eff.setOpacity(1.0 if self._breath_on else 0.72)

    def _on_save(self) -> None:
        """保存设置：主题 / 缩放 / 锁定 / 自启 / 番茄钟时长"""
        try:
            pet = self.pet
            # 主题已在下拉变更时即时应用；此处仅兜底当前选择
            theme_key = self.theme_combo.currentData()
            if theme_key and theme_key != get_current_theme():
                pet._apply_theme_preset(theme_key)
            cfg = load_config()  # 主题已持久化，重新读取合并其余设置
            # 缩放
            scale = float(self.scale_combo.currentData())
            if abs(scale - pet.user_scale) > 0.01:
                pet._set_scale(scale)
            # 锁定位置
            if pet.locked != self.lock_toggle.isChecked():
                pet._toggle_lock(self.lock_toggle.isChecked())
            # 开机自启
            want_auto = self.auto_toggle.isChecked()
            if want_auto != DesktopPet._is_auto_start():
                if want_auto:
                    pet._add_auto_start()
                else:
                    pet._remove_auto_start()
            # 番茄钟时长（静默保存，不逐条弹气泡）
            work = self.work_spin.value()
            brk = self.break_spin.value()
            changed = False
            if work != pet.pomodoro._work_minutes:
                pet.pomodoro.set_work_minutes(work)
                changed = True
            if brk != pet.pomodoro._break_minutes:
                pet.pomodoro.set_break_minutes(brk)
                changed = True
            if changed:
                cfg["pomodoro_work_minutes"] = work
                cfg["pomodoro_break_minutes"] = brk
            # 主动回话参数（持久化 + 内存生效 + 同步服务端）
            cfg["proactive_probability"] = min(1.0, max(0.0, self.proactive_prob_spin.value() / 100.0))
            cfg["proactive_min_interval"] = self.proactive_min_spin.value()
            cfg["proactive_max_interval"] = self.proactive_max_spin.value()
            cfg["screenshot_quality"] = self.quality_spin.value()
            pet._proactive_probability = cfg["proactive_probability"]
            pet._proactive_min_interval = cfg["proactive_min_interval"]
            pet._proactive_max_interval = cfg["proactive_max_interval"]
            pet._screenshot_quality = cfg["screenshot_quality"]
            try:
                pet.ws_client.send_config_sync({
                    "proactive": {
                        "probability": pet._proactive_probability,
                        "min_interval": pet._proactive_min_interval,
                        "max_interval": pet._proactive_max_interval,
                    }
                })
            except Exception as e:
                logger.error(f"同步主动回话配置失败: {e}")
            # 合并位置/缩放/锁定/吸附，避免主题键被局部保存覆盖
            save_config({**cfg, "scale": pet.user_scale, "locked": pet.locked,
                         "corner_snap": getattr(pet, "corner_snap", False),
                         "pos_x": pet.x(), "pos_y": pet.y()})
            self._set_dirty(False)
            self._flash_saved()
            # 保存成功：短暂展示光效后关闭（主题已即时生效，不依赖此处关窗）
            QTimer.singleShot(420, self.accept)
        except Exception as e:
            logger.error(f"设置保存异常: {e}")

    def _flash_saved(self) -> None:
        """保存成功：顶栏细高光胶囊闪一下"""
        try:
            c = get_theme_colors()
            self._saved_flash.setText("已保存")
            self._saved_flash.setStyleSheet(
                f"color: {c['connected']}; font-size: {FONT_CAPTION}px; font-weight: 600;"
                f" background: {_theme_rgba('connected', 36)};"
                f" border: 1px solid {_theme_rgba('connected', 90)};"
                f" border-radius: {RADIUS_PILL}px; padding: 6px 14px;"
            )
            self._saved_flash.show()
            self._save_btn.setEnabled(False)
            self._breath_timer.stop()
            self._breath_eff.setOpacity(1.0)
            self._saved_flash_timer.start()
        except Exception:
            pass


class DesktopPet(QWidget):

    tts_ready = pyqtSignal(str)   # (wav路径) 后台 TTS 请求完成，回主线程播放

    VOICE_LINES: dict[str, list[str]] = {
        "enterprise": [
            "约克城级二号舰企业，报到。对于敌人，我不会同情也不会手下留情，只会全力迎战。",
            "指挥官，告诉我，我还要击沉多少敌人才行？",
            "幸运也是实力的一部分？那我能分一些给姐姐么？",
            "战争结束后你想做什么？——我？我的话，大概还会跟着你吧…你愿意……带我走吗？",
        ],
        "shoukaku": [
            "第五航空战队旗舰翔鹤，今后会以一航战的前·辈们为目标，好好努力的！噗嗤~开玩笑的~",
            "理智是女人的美德……拜此所赐，我总与那些前·辈们格格不入呢，真困扰~",
            "指挥官，想听一听我的笛声吗？",
            "瑞鹤，再给白鹰的同·僚们添麻烦的话，今天晚上你就只能吃天妇罗咯。",
        ],
        "newjersey": [
            "白鹰战列舰，最大最强的Black Dragon，新泽西登场！见识下我的力量吧！开玩笑的~Honey喜欢这样的感觉吗？",
            "欢迎回来。需要帮忙制定工作计划吗？或者，你对此已经胸有成竹了？",
            "欢迎Honey~今天要从哪个任务开始做起呢？",
            "装备检查完毕，各系统运行正常，辛苦你了——啊，难道是看着迷了~？我倒是不介意？",
            "在津津有味地看着什么？当然是看Honey啦~",
            "衣阿华对大和么……确实是一个热门的话题呢。呵呵，人们就是热衷这样的，不是吗？",
            "我也想和大和和武藏她们打一次呢。Honey觉得谁能赢呀？",
            "喜欢的饮料是果汁哦。青苹果汁、橙汁我都推荐，汽水的话也OK。咖啡…感觉不太行？",
            "就算是Honey，也不能随便插队哦？接下来是我的冰激凌~",
            "秘书舰该帮指挥官完成多少工作呢……我个人认为，40%吧。",
            "这件事……指挥官说的也有道理呢…那么接下来听听我的方案吧？",
            "航空母舰的时代啊……那可不好说。谁又说得清战列舰会有什么变化呢~",
            "白鹰的Big J，最大最强的Black Dragon就是我啦！",
            "如果是有任务，我当然义不容辞。至于别的请求，可就要额外收点报酬了哦？开玩笑的~",
            "正好，Honey帮我买下这个~…不行？",
            "指挥官，你已经处于被动状态了哦，各种意义上的~",
            "我知道的哦，你就喜欢这样的事情对吧~哈哈哈",
            "摸完了吗？好，那就乖乖坐下，该轮到我摸了~",
            "看下刚刚的战斗报告吧~谁先说~？我就一边吃着冰淇淋一边洗耳恭听咯~",
            "出击辛苦啦！首先是回家的啾？~嘻嘻，就是这样~接下来就开始战斗总结吧",
            "彼此疏远的话会心生顾虑啊，或许像这样……身体上的接触能让你放下心来？",
            "不知不觉间，大家也熟络起来了呢~下次想聊什么？舰装技术？还是日常生活？",
            "嗯？你怎么一脸疲倦的样子……果然是超负荷工作了吧？来，躺这里，这次就让我照顾你吧。就把我的大腿当成你临时的枕头吧~",
            "主动一点的新泽西和被动一些的新泽西，指挥官更喜欢哪一种呢？——停~我会在接下来的时间里慢慢确认的~",
            "你的想法，已经全部传达给我了。如果指挥官不嫌弃的话我当然也没问题哦~？",
            "全员，一级战备！要上了哦！",
            "Honey在看着哦！战斗开始！",
            "我们正锐不可当地向着正确的方向航行——哼哼，大家都喜欢这样的感觉吧？",
            "不敢相信，我们居然被敌人压制住了……在找出还击的方法之前，我是不会休息的！",
            "火控系统，瞄准目标！",
            "不用慌，我已经想出控制局势的办法了。",
            "最强最大的…不对，是最可爱最美的婚纱装扮新泽西登场！哼哼哼~看入迷了吧？",
            "毕竟穿着这身战斗…肯定没问题~Honey应该挺喜欢这种的吧，战斗新娘之类的",
            "不然让提康德罗加拿些冰淇淋过来吧~今天就决定是草莓口味的好了！",
            "工作很努力了呢，很了不起哦~乖孩子摸摸头~",
            "出击辛苦了！这是欢迎回来之吻哦，你喜欢这种对吧",
            "主动也好，被动也好，Honey就是我最喜欢的Honey，这点是永远不会变的哦。",
            "以双倍的速度上了哦！",
            "Honey，看着我哦",
            "好热……Honey不要紧吗？没热趴下吧？我分你点饮料，你能帮我涂下防晒吗？",
            "嗯…想吃冰淇淋了…Honey也来一根吗？没事没事，白鹰的大家都带了冰淇淋来哦？",
            "就拜托你好好涂啦！Honey",
            "呀！？真是的Honey，虽然我知道你喜欢这种啦…///",
            "出击辛苦了！咦，Honey是不是晒黑了？哈哈开玩笑的！来，饮料给你，慢慢休息吧",
            "我是不会让别人弄哭Honey的！",
            "呼~收尾的动作可真难啊，不过根本难不倒我啦！Honey~我跳得怎么样啊~？",
            "欢迎准时赴约的Honey~嘻嘻，看你的表情，我准备的惊喜很成功呢~！",
            "好奇这些布景么？当然是我亲自布置的啦~这种东西可难不倒最大最强的Black Dragon哦~！",
            "看来Honey很喜欢我这身衣服呢？那通常新泽西和东煌风新泽西，Honey更喜欢哪一个呀~？",
            "果然晚上还是有些冷吧？来，抱抱~！",
            "Honey，别只是站着，来一起跳舞吧！不会也没关系，我教你嘛~",
            "东煌好像有句诗……不过在我这里，可是永远不会缺的满月哦！所以我也会永远、永远跟Honey在一起的~！",
            "终于等到你了Honey！比赛之前，就让我来为Honey献上特别的超极速祝福吧~！快到我身边来~啾~",
            "我在这里哦Honey——嘿嘿，这个位置最棒了哦，既能第一时间捕捉到你，又可以吹到凉凉的空调~",
            "场上的氛围已经火热起来啦，Honey也该做热身准备了吧~在那之前，先让我给你一个祝福的……啾~",
            "Honey你看那条赛道，在阳光下闪闪发光的，像不像一条冠军之路呢~",
            "我在车载冰箱里放了些新口味冰淇淋哦，Honey快来尝尝吧！",
            "比赛结束之后想和Honey一起去兜风啊~这次换我载着Honey吧？",
            "真是的，虽然后备箱里是很宽敞没错啦……///",
            "怎么啦，想要更多亲亲嘛？啊哈哈，果然是这样吧~",
            "Honey的到来让气氛都火热起来了呢——不过最炽热的，还是我为你而不断加速的心跳哦~",
            "Black Dragon率先到达终点——",
        ],
        "hood": [
            "您就是指挥官吗，贵安。皇家海军的荣耀——胡德，与胜利一同来到您的身边。",
            "欢迎回来，指挥官，要来一杯红茶吗？",
            "虽然淑女要随时保持优雅，但是淑女对于钟情的对象也会勇敢发起攻势哦？",
            "优雅，可不是花瓶。",
        ],
        "zuikaku": [
            "我可是幸运之鹤！直到最后都坚持到底，这才是所谓的'精锐'！",
            "只要有姐姐在身边，我就无所畏惧！",
            "等等，灰色幽灵，不要赢了就跑！再、再来一次，这次我一定——",
            "指挥官给我的感觉和翔鹤姐有点像呢……哎、哎？不是啦！我没有把指挥官当成姐姐啦！",
        ],
        "essex": [
            "这里就是企业前辈也在的…咳、咳咳！白鹰最新锐航母、埃塞克斯号，正式报到！",
            "大家都知道埃塞克斯级很强，但是每个人的嘴上却又都挂着企业前辈…哈啊…",
            "企业前辈，看到我的表现了吗！",
            "谢谢你，指挥官。我不需要再独自去证明什么了。",
        ],
        "taihou": [
            "是吃大凤呢，和大凤一起洗澡呢，还是~要和大凤做没羞没臊的事情呢~♡",
            "指挥官喜欢小的吗？不喜欢的话，大凤就让大的那些全部都消失好了，嘻嘻……",
            "嘻嘻，只要是指挥官的要求，就算是天上的月亮，大凤也会去取来呦~",
            "终于送到大凤手里了呢~如果不是上面写着大凤的名字，早就把它处理掉了呢嘻嘻。",
        ],
        "yorktown2": [
            "从黑暗之后迎来的是绚烂的幸福之光。约克城，重新归来。",
            "就和我们不是仅为战斗而存在一样，指挥官也不是仅为工作而存在。",
            "有什么烦恼的话跟我说说吧？我会好好听的。",
            "企业，应该没事吧……不，这次我会保护好大家的，不会再让悲剧重演。",
        ],
        "belfast": [
            "贵安，我是爱丁堡级二号舰贝尔法斯特，皇家最大的巡洋舰，担任女仆长一职。有什么需要的话请尽管告诉我吧。",
            "欢迎回来，指挥官，红茶已经泡好，文档也归类完毕，开始舒适的工作吧。",
            "要来一杯红茶放松一下吗？茶点，或者您想换换口味的话，咖啡和威士忌也都准备好了呢。",
            "我希望能够成为最理解您的人——这份心愿对我而言，早已不亚于女仆长的职责了呢，呵呵~",
            "您手边的红茶有些凉了呢，我来为您换新的吧。……我知道您在工作时会格外投入，已经提前准备好替换的茶水了。",
            "偶尔，我也想让您尝尝我新学的点心呢。这并不是服务，而是……出自私心的分享哦？",
            "对我而言，守护在您的身边不仅仅是职责，也是我的幸福。所以……请永远不要让我离开您的身旁。",
            "为主人清除障碍正是女仆的职责。",
            "有什么需要请尽管吩咐，贝尔法斯特随时待命。",
            "祝您好梦，主人。我会守着这份宁静的时光。",
        ],
        "anshan": [
            "东煌轻巡洋舰鞍山，报到。指挥官，今天的任务清单已经整理好了，要现在开始吗？",
            "工作需要劳逸结合，偶尔也该歇一歇。要去甲板透透气么？",
            "文档我已经按优先级排好序了，先处理最要紧的那几项吧。",
            "指挥官，辛苦了。茶水我放在旁边，记得趁热喝。",
            "比起空谈，我更习惯把事情一件件落实下去——这样才安心。",
        ],
    }

    def __init__(self, image_path: str, api_base: str, api_key: str) -> None:
        super().__init__()
        # ── 载入持久化配置 ──
        self.pet_config = load_config()
        cfg = self.pet_config
        # pet_config.json 中的 api_key 优先于默认值/命令行（便于在配置中统一维护）
        api_key = cfg.get("api_key", api_key)
        self.user_scale = cfg.get("scale", 1.0)
        self.locked = cfg.get("locked", False)
        self.corner_snap = bool(cfg.get("corner_snap", False))
        pos_x = cfg.get("pos_x")
        pos_y = cfg.get("pos_y")
        # 桌面状态上报防抖
        self._last_state_report = 0.0
        self._state_report_interval = 5.0
        # 主动回话联动设置（服务端启停/概率/间隔）与截图质量
        self._proactive_probability = float(cfg.get("proactive_probability", 0.3))
        self._proactive_min_interval = int(cfg.get("proactive_min_interval", 300))
        self._proactive_max_interval = int(cfg.get("proactive_max_interval", 900))
        self._screenshot_quality = int(cfg.get("screenshot_quality", 60))
        logger.info(
            f"DesktopPet 初始化: scale={self.user_scale}, locked={self.locked}, "
            f"corner_snap={self.corner_snap}, pos=({pos_x}, {pos_y})")

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # 防止拖动时出现系统默认黑底填充导致的闪烁
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            raise FileNotFoundError(f"图片加载失败：{image_path}")
        if not pixmap.toImage().hasAlphaChannel():
            raise ValueError(
                "当前图片不含透明通道。请先运行 remove_bg.py 生成透明 PNG，再作为 --image 参数传入。"
            )
        self.base_pixmap = pixmap
        self.base_width = min(420, self.base_pixmap.width())
        scale_ratio = self.base_width / self.base_pixmap.width()
        self.base_height = int(self.base_pixmap.height() * scale_ratio)
        self.resize(self.base_width + 40, self.base_height + 40)

        self.state = "idle"
        self.state_until = 0.0
        self.state_start = time.time()
        self.voice_lines = self.VOICE_LINES

        self.dragging = False
        self.drag_offset = QPoint()
        self.drag_start_pos = QPoint()
        self.press_time = 0.0
        self.inertia_velocity = QPointF(0.0, 0.0)
        self.last_tick = time.time()
        self.last_move_time = 0.0
        self.last_move_pos = QPoint()
        self._snap_anim: Optional[QPropertyAnimation] = None
        self._snap_preview = 0  # 拖动近边预览：-1 左 / 0 无 / 1 右
        self._long_press_fired = False
        self._long_press_timer = QTimer(self)
        self._long_press_timer.setSingleShot(True)
        self._long_press_timer.setInterval(400)
        self._long_press_timer.timeout.connect(self._on_long_press)

        self.scale = 1.0
        self.float_y = 0.0
        self.talk_sway_x = 0.0
        self.remote_action = "idle"

        # 功能1：锁定位置（已从 config 加载）
        self.locked = getattr(self, 'locked', False)
        # 功能2：切换过渡动画
        self._transition_progress = 1.0
        self._old_pixmap = None
        # 功能3：自定义缩放（已从 config 加载）
        # 功能4：连接状态
        self.server_connected = False
        self._last_response_time = 0.0
        self._last_state_report = 0.0
        self._state_report_interval = 5.0

        self._current_secretary = get_current_secretary()
        self._current_skin_idx = 0  # 0=主立绘，1+=换装

        # ── 后台线程池：用于 pygetwindow 等阻塞调用 ──
        self._bg_executor = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="pet_bg")
        # TTS 后台请求完成 → 主线程播放
        self.tts_ready.connect(self._play_tts_file)

        # ── 音频预加载池：每个 secretary 一个 QMediaPlayer，预加载所有 mp3 ──
        self._audio_players: Dict[str, QMediaPlayer] = {}
        self._audio_contents: Dict[str, List[QMediaContent]] = {}
        self._preload_audio_for_secretary(self._current_secretary)

        self.bubble = ChatBubble()
        self.bubble.before_show = self._update_bubble_position
        self.bubble.send_requested.connect(self._on_send_message)
        self.bubble.theme_change_requested.connect(self._cycle_theme)
        self.bubble.screenshot_requested.connect(self._manual_screenshot)
        self.bubble.awareness_toggle_requested.connect(self._toggle_desktop_awareness)
        self.bubble.set_avatar(QPixmap(get_skin_path(self._current_secretary)))
        # 图层：聊天框 < 舰娘（番茄钟叠层画在舰娘上，永远在舰娘之上）
        self.bubble.installEventFilter(self)
        QTimer.singleShot(0, self._ensure_pet_above_bubble)
        self.secretary_panel = SecretaryPanel(self._current_secretary)
        self.secretary_panel.secretary_selected.connect(self._switch_secretary)
        self.secretary_panel.manage_requested.connect(self._open_manager)
        self._voice_map: list[dict] = load_voice_map(self._current_secretary)
        self.agent = AgentEngine()
        self.agent.action_started.connect(self._on_agent_action)
        self.agent.action_finished.connect(self._on_agent_result)
        self.agent.error_occurred.connect(lambda e: self.bubble.add_message(e, is_user=False))
        self._agent_step = 0  # 本轮对话已执行的工具步骤计数

        # ── 番茄钟 ──
        self.pomodoro = PomodoroTimer(self)
        self.pomodoro.load_config(self.pet_config)
        self.pomodoro.tick_signal.connect(self._on_pomodoro_tick)
        self.pomodoro.finished_signal.connect(self._on_pomodoro_finished)
        self._pomodoro_bubble: StyledBubble | None = None  # 当前倒计时气泡引用
        self._pomodoro_remaining: int = 0  # 番茄钟剩余秒数（用于 paintEvent 绘制）
        self._pomodoro_mode: str = "idle"  # 番茄钟模式：idle/work/break
        self._pomodoro_prev_mode: str = "idle"  # 上一帧模式，用于检测状态变化

        # ── 精进功能：日程 / 主动陪伴 ──
        self.schedule_mgr = ScheduleManager()
        self.proactive = ProactiveEngine(
            secretary=self._current_secretary,
            secretary_lines=self.VOICE_LINES.get(self._current_secretary, []),
        )
        self._pending_reminders: list = []   # 待展示提醒队列（克制，逐条弹出）
        self._smart_timer = QTimer(self)
        self._smart_timer.timeout.connect(self._on_smart_tick)
        self._smart_timer.start(20000)

        # 欢迎语（登录场景日文语音优先，缺失则时段问候兜底）
        secretary = get_current_secretary()
        if not self.play_scene_voice("login"):
            greeting = time_greeting(self._secretary_display_name(secretary))
            self.bubble.add_message(greeting, is_user=False)

        # 插件 WebSocket 客户端（主）—— 服务端端口由 pet_config.server_port 决定
        _pet_port = load_config().get("server_port", 6191)
        try:
            _pet_port = int(_pet_port)
        except (TypeError, ValueError):
            _pet_port = 6191
        logger.info(f"插件 WebSocket 目标: ws://127.0.0.1:{_pet_port}/")
        # 注意必须带路径 "/"：Qt 的 QWebSocket 在 path 为空时会发
        # `GET ?session_id=...`（缺少斜杠），Node http 解析器会直接拒绝，
        # 导致连不上 DSH；AstrBot 端同样接受 "/" 路径，双向兼容。
        self.ws_client = PluginWebSocketClient(
            ws_url=f"ws://127.0.0.1:{_pet_port}/",
            session_id="desktop_pet",
            api_key=api_key,
            agent_engine=self.agent,
        )
        self.ws_client.chat_received.connect(self._on_chat_received)
        self.ws_client.connection_changed.connect(self._on_connection_changed)
        self.ws_client.error_occurred.connect(lambda e: self.bubble.add_message(e, is_user=False))
        self.ws_client.connect_to_server()

        # 旧 AstrBotClient 保留作为回退（如需切换可取消注释）
        # self.client = AstrBotClient(api_base, api_key)
        # self.client.chat_received.connect(...)

        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._tick)
        self.anim_timer.start(16)

        self._setup_tray()

        self._move_to_bottom_right()
        # 从配置恢复窗口位置
        if pos_x is not None and pos_y is not None:
            self.move(pos_x, pos_y)
        self._update_bubble_position()

    def _setup_tray(self) -> None:
        """创建桌面托盘图标"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        # 用当前立绘缩成圆角托盘图标
        tray_icon = QIcon(make_rounded_pixmap(self.base_pixmap, 32))
        self.tray = QSystemTrayIcon(tray_icon, self)
        self.tray.setToolTip(f"碧蓝桌宠 - {self._secretary_display_name(self._current_secretary)}")

        # 托盘菜单
        menu = QMenu()
        menu.setStyleSheet(glass_menu_stylesheet())
        show_action = QAction("显示/隐藏", self)
        show_action.triggered.connect(self._toggle_visibility)
        secretary_action = QAction("切换秘书舰", self)
        secretary_action.triggered.connect(self._show_secretary_panel)
        settings_action = QAction("⚙️ 设置", self)
        settings_action.triggered.connect(self._open_settings)
        exit_action = QAction("退出", self)
        exit_action.triggered.connect(QApplication.instance().quit)

        menu.addAction(show_action)
        menu.addAction(secretary_action)
        menu.addAction(settings_action)
        menu.addSeparator()
        menu.addAction(exit_action)
        self.tray.setContextMenu(menu)

        # 左键点击显示/隐藏
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason: int) -> None:
        """托盘点击事件"""
        if reason == QSystemTrayIcon.Trigger:
            self._toggle_visibility()

    def _toggle_visibility(self) -> None:
        """切换桌宠和气泡的可见性"""
        visible = not self.isVisible()
        self.setVisible(visible)
        if self.bubble:
            self.bubble.setVisible(visible)

    def _update_tray_tooltip(self) -> None:
        """更新托盘提示文字"""
        if hasattr(self, 'tray'):
            self.tray.setToolTip(f"碧蓝桌宠 - {self._secretary_display_name(self._current_secretary)}")

    def _move_to_bottom_right(self) -> None:
        screen_rect = QApplication.primaryScreen().availableGeometry()
        x = screen_rect.right() - self.width() - 24
        y = screen_rect.bottom() - self.height() - 24
        self.move(x, y)

    def _set_corner_snap(self, checked: bool) -> None:
        """一级菜单开关：仅吸附左/右；上下仍可拖。开时动画贴到就近边，关时立刻停动画"""
        self.corner_snap = bool(checked)
        if not self.corner_snap:
            # 关闭：停掉进行中的贴边动画与惯性，避免“取消后仍滑向边/顶”
            self._stop_snap_anim()
            self.inertia_velocity = QPointF(0.0, 0.0)
            if self._snap_preview != 0:
                self._snap_preview = 0
                self.update()
            # 反馈：气泡顶栏提示已自由拖动，2s 后收起
            try:
                self.bubble.show_agent_status("已自由拖动", done=True)
                self.bubble.show()
                self._update_bubble_position()
                QTimer.singleShot(2000, self.bubble.clear_agent_status)
            except Exception:
                pass
        cfg = load_config()
        cfg["corner_snap"] = self.corner_snap
        save_config(cfg)
        if self.corner_snap and not self.locked:
            self._animate_snap_x()

    def _snap_edge_x(self) -> Optional[int]:
        """按当前中心落在左/右半屏，返回目标 x；失败返回 None"""
        try:
            geo = QApplication.primaryScreen().availableGeometry()
            margin = 24
            w = self.width()
            left = geo.left() + margin
            # Qt right() 为 inclusive，窗口可用右缘 = right()+1-w
            right = geo.right() + 1 - w - margin
            center_x = self.x() + w // 2
            mid_x = geo.left() + geo.width() // 2
            return left if center_x < mid_x else right
        except Exception as e:
            logger.error(f"计算吸附边失败: {e}")
            return None

    def _animate_snap_x(self) -> None:
        """只吸附水平边（左或右），Y 保留；用动画滑过去而非瞬移"""
        if not self.corner_snap or self.locked:
            return
        try:
            target_x = self._snap_edge_x()
            if target_x is None:
                return
            self.inertia_velocity = QPointF(0.0, 0.0)
            if self.x() == target_x:
                self._persist_window_pos()
                return
            self._stop_snap_anim()
            anim = QPropertyAnimation(self, b"pos", self)
            anim.setDuration(320)
            anim.setStartValue(self.pos())
            anim.setEndValue(QPoint(target_x, self.y()))
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.finished.connect(self._on_snap_anim_done)
            self._snap_anim = anim
            anim.start()
        except Exception as e:
            logger.error(f"吸附动画失败: {e}")

    def _on_snap_anim_done(self) -> None:
        try:
            if self._snap_anim is not None and not sip.isdeleted(self._snap_anim):
                self._snap_anim.deleteLater()
            self._snap_anim = None
            self._persist_window_pos()
        except Exception:
            self._snap_anim = None

    def _stop_snap_anim(self) -> None:
        try:
            if self._snap_anim is not None and not sip.isdeleted(self._snap_anim):
                self._snap_anim.stop()
                self._snap_anim.deleteLater()
        except Exception:
            pass
        self._snap_anim = None

    def _persist_window_pos(self) -> None:
        """合并写入位置等窗口状态，避免局部 save_config 冲掉 theme 等键"""
        try:
            cfg = load_config()
            cfg.update({
                "scale": self.user_scale,
                "locked": self.locked,
                "corner_snap": self.corner_snap,
                "pos_x": self.x(),
                "pos_y": self.y(),
            })
            save_config(cfg)
        except Exception as e:
            logger.error(f"保存窗口位置失败: {e}")

    def paintEvent(self, event) -> None:  # type: ignore[override]
        try:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

            us = self.user_scale
            draw_w = int(self.base_width * self.scale * us)
            draw_h = int(self.base_height * self.scale * us)
            x = (self.width() - draw_w) // 2 + int(self.talk_sway_x * us)
            y = (self.height() - draw_h) // 2 + int(self.float_y * us)

            # 过渡动画：同时画旧图和新图
            if self._transition_progress < 1.0 and self._old_pixmap is not None:
                t = self._transition_progress
                # 旧图淡出
                painter.setOpacity(1.0 - t)
                painter.drawPixmap(QRect(x, y, draw_w, draw_h), self._old_pixmap)
                # 新图淡入
                painter.setOpacity(t)
                painter.drawPixmap(QRect(x, y, draw_w, draw_h), self.base_pixmap)
                painter.setOpacity(1.0)
            else:
                painter.drawPixmap(QRect(x, y, draw_w, draw_h), self.base_pixmap)

            # 连接状态指示器（右上角，iOS 发光圆点）
            dot_r = 5
            dot_x = self.width() - 18
            dot_y = 12
            painter.setPen(Qt.NoPen)
            c = get_theme_colors()
            color = _hex_to_qcolor(c["connected"]) if self.server_connected else _hex_to_qcolor(c["disconnected"])
            # 呼吸发光层
            pulse = 0.5 + 0.5 * math.sin(time.time() * 3.0)
            glow_r = dot_r + 5 + int(pulse * 3)
            glow = QColor(color)
            glow.setAlphaF(0.25 + 0.2 * pulse)
            painter.setBrush(glow)
            painter.drawEllipse(QPoint(dot_x, dot_y), glow_r, glow_r)
            # 实体圆点 + 高光（iOS 风格）
            painter.setBrush(color)
            painter.drawEllipse(QPoint(dot_x, dot_y), dot_r, dot_r)
            painter.setBrush(QColor(255, 255, 255, 90))
            painter.drawEllipse(QPoint(dot_x - 1, dot_y - 1), dot_r - 2, dot_r - 2)

            # 番茄钟倒计时显示（桌宠本体上绘制，避免气泡闪烁）
            if self._pomodoro_mode != "idle" and self._pomodoro_remaining > 0:
                self._draw_pomodoro_overlay(painter, c)

            # 吸附近边预览：拖动靠近吸附目标时该侧高亮
            if self._snap_preview != 0 and self.dragging and self.corner_snap:
                painter.setRenderHint(QPainter.Antialiasing, True)
                painter.setPen(Qt.NoPen)
                glow = _hex_to_qcolor(c["accent"])
                glow.setAlpha(150)
                painter.setBrush(glow)
                bw = 5
                if self._snap_preview < 0:
                    painter.drawRoundedRect(QRectF(2, 10, bw, self.height() - 20), 3, 3)
                else:
                    painter.drawRoundedRect(
                        QRectF(self.width() - bw - 2, 10, bw, self.height() - 20), 3, 3)

        except Exception as e:
            logger.error(f"DesktopPet.paintEvent 异常: {e}")

    def _draw_pomodoro_overlay(self, painter: QPainter, colors: dict) -> None:
        """在桌宠本体上绘制番茄钟剩余时间（跟随桌宠位置，不独立闪烁窗口）"""
        try:
            painter.save()
            painter.setRenderHint(QPainter.Antialiasing, True)

            # 文本内容
            label = "工作" if self._pomodoro_mode == "work" else "休息"
            time_str = self.pomodoro.format_time(self._pomodoro_remaining)
            text = f"{label} {time_str}"

            # 字体设置 - 与聊天气泡一致
            font = painter.font()
            font.setPointSize(11)
            font.setBold(True)
            font.setFamily("Microsoft YaHei UI")
            painter.setFont(font)

            # 测量文本尺寸
            fm = painter.fontMetrics()
            text_rect = fm.boundingRect(text)
            padding_x = 16
            padding_y = 10
            bg_width = text_rect.width() + padding_x * 2
            bg_height = text_rect.height() + padding_y * 2

            # 位置：桌宠头顶上方居中，但约束在窗口内部
            us = self.user_scale
            pet_center_x = self.width() // 2 + int(self.talk_sway_x * us)
            pet_top_y = (self.height() - int(self.base_height * self.scale * us)) // 2 + int(self.float_y * us)
            bg_x = pet_center_x - bg_width // 2
            bg_y = pet_top_y - bg_height - 8  # 头顶上方留 8px 间距

            # 约束：确保倒计时完全在窗口范围内
            # 水平居中，防止超出左右边界
            bg_x = max(0, min(bg_x, self.width() - bg_width))
            # 垂直方向：优先画在立绘上方，若空间不足则画在立绘内部顶部或窗口顶部
            min_y = 4  # 窗口顶部最小边距
            max_y = self.height() - bg_height - 4  # 窗口底部最小边距
            if bg_y < min_y:
                # 空间不足时，尝试画在立绘内部顶部（立绘绘制区域的 y + 4）
                draw_y = (self.height() - int(self.base_height * self.scale * us)) // 2 + int(self.float_y * us)
                bg_y = max(min_y, draw_y + 4)
            bg_y = max(min_y, min(bg_y, max_y))

            # 背景圆角矩形 - 与聊天气泡同款圆角
            bg_rect = QRect(bg_x, bg_y, bg_width, bg_height)
            radius = RADIUS_CAPSULE

            # 外阴影 - 与聊天气泡一致的阴影风格
            shadow_color = QColor(0, 0, 0, 60)
            for i in range(4, 0, -1):
                shadow_color.setAlpha(15 - i * 2)
                painter.setBrush(shadow_color)
                painter.setPen(Qt.NoPen)
                painter.drawRoundedRect(bg_rect.adjusted(-i, -i, i, i), radius + i, radius + i)

            # 主体背景 - 使用 bot_bubble 配色（聊天气泡同款）
            bg_color = _hex_to_qcolor(colors.get("bot_bubble", "rgba(255, 255, 255, 0.13)"))
            bg_color.setAlpha(int(bg_color.alpha() * 0.95))
            painter.setBrush(bg_color)

            # 边框 - 使用 bot_bubble_border 配色（聊天气泡同款）
            border_color = _hex_to_qcolor(colors.get("bot_bubble_border", "rgba(255, 255, 255, 0.18)"))
            painter.setPen(QPen(border_color, 1))
            painter.drawRoundedRect(bg_rect, radius, radius)

            # 文本颜色 - 使用 fg 配色（聊天气泡同款）
            text_color = _hex_to_qcolor(colors.get("fg", "#ffffff"))
            painter.setPen(text_color)
            painter.drawText(bg_rect, Qt.AlignCenter, text)

            painter.restore()
        except Exception as e:
            logger.error(f"_draw_pomodoro_overlay 异常: {e}")

    def showEvent(self, event) -> None:  # type: ignore[override]
        try:
            super().showEvent(event)
            # 禁用 DWM 窗口过渡动画，消除拖动时的黑底闪烁
            _disable_dwm_transitions(self)
        except Exception as e:
            logger.error(f"DesktopPet.showEvent 异常: {e}")

    def eventFilter(self, obj, event) -> None:  # type: ignore[override]
        try:
            if obj is getattr(self, "bubble", None) and event.type() in (
                QEvent.Show,
                QEvent.Raise,
                QEvent.WindowActivate,
                QEvent.WindowStateChange,
            ):
                # 气泡显示/上浮/激活时，把舰娘抬回其上（不抢焦点）
                # 延后两帧：等淡入首帧画完再抬层，避免 raise 打断合成造成闪一下
                QTimer.singleShot(30, self._ensure_pet_above_bubble)
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def _ensure_pet_above_bubble(self) -> None:
        """保证图层：聊天框始终在舰娘下方；番茄钟叠层画在舰娘 paint 末尾，始终在舰娘之上。

        不在动画 tick 里反复 raise_，避免盖住右键菜单/面板等应浮在舰娘上的窗口。
        """
        try:
            b = getattr(self, "bubble", None)
            if b is None or sip.isdeleted(b) or not b.isVisible():
                return
            if not self.isVisible():
                return
            self.raise_()
        except Exception as e:
            logger.debug(f"_ensure_pet_above_bubble: {e}")

    def moveEvent(self, event) -> None:  # type: ignore[override]
        try:
            super().moveEvent(event)
            # 拖动期间强制同步重绘，保证分层窗口始终有最新内容，避免黑/透明闪烁
            if getattr(self, "dragging", False):
                self.repaint()
        except Exception as e:
            logger.error(f"DesktopPet.moveEvent 异常: {e}")

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        try:
            if event.button() == Qt.LeftButton:
                if self.locked:
                    event.accept()
                    return
                self._stop_snap_anim()
                self.dragging = True
                self._long_press_fired = False
                self._long_press_timer.start()
                self.drag_offset = event.globalPos() - self.frameGeometry().topLeft()
                self.drag_start_pos = event.globalPos()
                self.press_time = time.time()
                self.last_move_time = self.press_time
                self.last_move_pos = event.globalPos()
                self.inertia_velocity = QPointF(0.0, 0.0)
                event.accept()
                return
            if event.button() == Qt.RightButton:
                self._show_context_menu(event.globalPos())
                event.accept()
                return
        except Exception as e:
            logger.error(f"mousePressEvent 异常: {e}")
        super().mousePressEvent(event)

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        try:
            if event.modifiers() & Qt.ControlModifier:
                steps = SCALE_STEPS
                idx = min(range(len(steps)), key=lambda i: abs(steps[i] - self.user_scale))
                delta = 1 if event.angleDelta().y() > 0 else -1
                new_idx = max(0, min(len(steps) - 1, idx + delta))
                if new_idx != idx:
                    self._set_scale(steps[new_idx])
                event.accept()
                return
        except Exception as e:
            logger.error(f"wheelEvent 异常: {e}")
        super().wheelEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        try:
            if self.locked or not self.dragging:
                super().mouseMoveEvent(event)
                return
            moved = (event.globalPos() - self.drag_start_pos).manhattanLength()
            if moved > 8 and self._long_press_timer.isActive():
                self._long_press_timer.stop()
            new_pos = event.globalPos() - self.drag_offset
            # 吸附开：拖动时 X 跟手全自由；松手才动画贴边。仅限制在屏幕内
            if self.corner_snap:
                geo = QApplication.primaryScreen().availableGeometry()
                max_x = geo.right() + 1 - self.width()
                max_y = geo.bottom() + 1 - self.height()
                new_pos.setX(max(geo.left(), min(new_pos.x(), max_x)))
                new_pos.setY(max(geo.top(), min(new_pos.y(), max_y)))
                # 近边预览：距左/右吸附目标 < 56px 高亮该侧
                target_x = self._snap_edge_x()
                if target_x is not None and abs(new_pos.x() - target_x) < 56:
                    side = -1 if target_x < geo.left() + geo.width() // 2 else 1
                else:
                    side = 0
                if side != self._snap_preview:
                    self._snap_preview = side
                    self.update()
            self.move(new_pos)
            now = time.time()
            dt = max(1e-4, now - self.last_move_time)
            delta = event.globalPos() - self.last_move_pos
            self.inertia_velocity = QPointF(delta.x() / dt, delta.y() / dt)
            self.last_move_time = now
            self.last_move_pos = event.globalPos()
            self._update_bubble_position()
            event.accept()
        except Exception as e:
            logger.error(f"mouseMoveEvent 异常: {e}")

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        try:
            if self._long_press_timer.isActive():
                self._long_press_timer.stop()
            if self.locked:
                if event.button() == Qt.LeftButton:
                    self._safe_click()
                event.accept()
                return
            if event.button() == Qt.LeftButton and self.dragging:
                self.dragging = False
                moved = (event.globalPos() - self.drag_start_pos).manhattanLength()
                held = time.time() - self.press_time
                if self._snap_preview != 0:
                    self._snap_preview = 0
                    self.update()
                if self._long_press_fired:
                    self._long_press_fired = False
                    if self.corner_snap and not self.locked:
                        self._animate_snap_x()
                    else:
                        self._persist_window_pos()
                elif moved < 8 and held < 0.25:
                    self._safe_click()
                else:
                    # 松手：吸附开 → 动画滑到左/右边；Y 保留（可上下拖到任意高度再松手）
                    if self.corner_snap and not self.locked:
                        self._animate_snap_x()
                    else:
                        self._persist_window_pos()
                event.accept()
                return
        except Exception as e:
            logger.error(f"mouseReleaseEvent 异常: {e}")
        super().mouseReleaseEvent(event)

    def _safe_click(self) -> None:
        """包装 _on_pet_clicked，防止崩溃"""
        try:
            self._on_pet_clicked()
        except Exception as e:
            print(f"[桌面宠物] 点击事件异常: {e}", file=sys.stderr)

    def _on_pet_clicked(self) -> None:
        self.proactive.on_interaction()
        self.state = "click"
        self.state_start = time.time()
        self.state_until = self.state_start + 0.35
        secretary = self._current_secretary

        # 15% 概率触发时段问候
        if random.random() < 0.15:
            name = self._secretary_display_name(secretary)
            quote = time_greeting(name)
            self.bubble.add_message(quote, is_user=False)
            self.bubble.show()
            self._update_bubble_position()
            return

        # 场景化触摸语音优先（命中则播放日文台词并结束）
        if self.play_scene_voice("touch"):
            return

        # 有语音数据时：从预加载池取音频（非阻塞）
        if self._voice_map:
            # 皮肤↔语音对应：当前皮肤池优先（音频与文字同条目绑定），无匹配回退全池
            pool = self._voice_map
            skin_key = self._current_skin_name()
            if skin_key:
                filtered = [it for it in pool if it.get("skin") == skin_key]
                if filtered:
                    pool = filtered
            # 优先选音频文件真实存在的条目，避免「有台词但没声音」
            voices_dir = _get_voices_dir()
            playable = [
                it for it in pool
                if it.get("mp3") and os.path.isfile(os.path.join(voices_dir, secretary, it["mp3"]))
            ]
            item = random.choice(playable or pool)
            quote = item.get("text") or ""
            if quote:
                self.bubble.add_message(quote, is_user=False)
            mp3_rel = item.get("mp3", "")
            if mp3_rel:
                # 从预加载内容中查找匹配的音频（unquote 处理空格等被编码的文件名）
                contents = self._audio_contents.get(secretary, [])
                played = False
                target = mp3_rel.replace("\\", "/")
                for content in contents:
                    url = unquote(content.canonicalUrl().toString()).replace("\\", "/")
                    if target in url or os.path.basename(target) in url:
                        player = self._audio_players.get(secretary)
                        if player is None:
                            player = QMediaPlayer(self)
                            self._audio_players[secretary] = player
                        try:
                            player.setMedia(content)
                            player.play()
                            played = True
                        except Exception as e:
                            logger.error(f"语音播放失败: {e}")
                        break
                # 兜底：若预加载未命中则直接按路径播放
                if not played:
                    try:
                        mp3_path = os.path.join(voices_dir, secretary, mp3_rel)
                        if os.path.isfile(mp3_path):
                            player = self._audio_players.get(secretary)
                            if player is None:
                                player = QMediaPlayer(self)
                                self._audio_players[secretary] = player
                            player.setMedia(QMediaContent(QUrl.fromLocalFile(mp3_path)))
                            player.play()
                            played = True
                    except Exception as e:
                        logger.error(f"语音兜底播放失败: {e}")
                if not played:
                    logger.info(f"语音未播放: 文件缺失或无法加载 {mp3_rel}")
        else:
            # 无语音数据：纯文本
            lines = self.voice_lines.get(secretary, self.VOICE_LINES["enterprise"])
            quote = random.choice(lines)
            self.bubble.add_message(quote, is_user=False)

        self.bubble.show()
        self._update_bubble_position()

    def _current_skin_name(self) -> str:
        """返回当前皮肤在 jp voice_map 中的名称（来自皮肤清单，未记录则回退默认名）。"""
        return jp_skin_for(self._current_secretary, self._current_skin_idx)

    def _current_source_artwork(self) -> Optional[str]:
        """返回当前皮肤的源立绘（不透明）绝对路径，皮肤切换时与主立绘同步。"""
        return source_for(self._current_secretary, self._current_skin_idx)

    def play_scene_voice(self, event: str) -> bool:
        """按事件触发场景化日文语音。命中并成功发起播放返回 True，否则 False（静默）。

        事件路由见 jp_voice.EVENT_SCENE_MAP。命中后同时显示日文台词字幕。
        直接以 entry['path'] 绝对路径播放，避免文件名含空格时 canonicalUrl
        将空格编码为 %20 导致子串匹配失效（鞍山等含空格文件名）。
        """
        sec = self._current_secretary
        skin = self._current_skin_name()
        entry = jp_voice.resolve_event(sec, skin, event)
        if not entry:
            return False
        path = entry.get("path", "")
        if not path or not os.path.isfile(path):
            return False
        player = self._audio_players.get(sec)
        if player is None:
            player = QMediaPlayer(self)
            self._audio_players[sec] = player
        try:
            player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
            player.play()
        except Exception as e:
            logger.error(f"场景语音播放失败: {e}")
            return False
        text = entry.get("text", "")
        if text:
            try:
                self.bubble.add_message(text, is_user=False)
                self.bubble.show()
                self._update_bubble_position()
            except Exception:
                pass
        return True

    def apply_manager_changes(self) -> None:
        """管理界面改动后：重载皮肤清单、语音映射并刷新当前皮肤。"""
        try:
            jp_voice._CACHE.clear()
            sec = self._current_secretary
            skins = get_available_skins(sec)
            if self._current_skin_idx >= len(skins):
                self._current_skin_idx = max(0, len(skins) - 1)
            if skins:
                self._load_skin(skins[self._current_skin_idx])
            # 重新预加载音频，以纳入新增/修改的 jp 语音条目
            self._audio_players.pop(sec, None)
            self._audio_contents.pop(sec, None)
            self._voice_map = load_voice_map(sec)
            self._preload_audio_for_secretary(sec)
        except Exception as e:
            logger.error(f"应用管理改动失败: {e}")

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        """双击切换当前秘书舰的皮肤"""
        try:
            if event.button() == Qt.LeftButton:
                skins = get_available_skins(self._current_secretary)
                if len(skins) > 1:
                    new_idx = (self._current_skin_idx + 1) % len(skins)
                    self._load_skin(skins[new_idx])
                    self._current_skin_idx = new_idx
        except Exception as e:
            logger.error(f"mouseDoubleClickEvent 异常: {e}")
        super().mouseDoubleClickEvent(event)

    def _load_skin(self, path: str) -> None:
        """加载指定路径的立绘（带淡入淡出过渡）"""
        pixmap = QPixmap(path)
        if pixmap.isNull():
            return
        self._old_pixmap = QPixmap(self.base_pixmap)  # 保存旧图
        self.base_pixmap = pixmap
        self._transition_progress = 0.0  # 触发过渡动画
        self.base_width = min(420, self.base_pixmap.width())
        scale_ratio = self.base_width / self.base_pixmap.width()
        self.base_height = int(self.base_pixmap.height() * scale_ratio)
        self.resize(self.base_width + 40, self.base_height + 40)
        # 重新定位防止超出屏幕
        screen_rect = QApplication.primaryScreen().availableGeometry()
        x = min(self.x(), screen_rect.right() - self.width())
        y = min(self.y(), screen_rect.bottom() - self.height())
        self.move(max(screen_rect.left(), x), max(screen_rect.top(), y))

    def _preload_audio_for_secretary(self, secretary: str) -> None:
        """预加载指定秘书舰的所有语音文件到内存，避免点击时阻塞"""
        if secretary in self._audio_players and secretary in self._audio_contents:
            # 已有播放器与内容表；若内容为空但 voice_map 非空（曾加载失败），允许重载
            if self._audio_contents[secretary] or not load_voice_map(secretary):
                return
        voice_map = load_voice_map(secretary)
        if not voice_map:
            self._audio_players.setdefault(secretary, QMediaPlayer(self))
            self._audio_contents[secretary] = []
            return
        voices_dir = _get_voices_dir()
        player = QMediaPlayer(self)
        contents: List[QMediaContent] = []
        for item in voice_map:
            mp3_rel = item.get("mp3", "")
            if mp3_rel:
                mp3_path = os.path.join(voices_dir, secretary, mp3_rel)
                if os.path.isfile(mp3_path):
                    contents.append(QMediaContent(QUrl.fromLocalFile(mp3_path)))
        # 场景化日文语音也预加载进同一播放池（与 mp3 同目录）
        try:
            jp_map = jp_voice.load_jp_map(secretary)
            for skin, scenes in jp_map.items():
                for sc, entry in scenes.items():
                    mp3_path = entry.get("path")
                    if mp3_path and os.path.isfile(mp3_path):
                        contents.append(QMediaContent(QUrl.fromLocalFile(mp3_path)))
        except Exception as ex:
            logger.error(f"jp 语音预加载失败: {ex}")
        self._audio_players[secretary] = player
        self._audio_contents[secretary] = contents
        logger.info(f"预加载语音完成: {secretary}, 共 {len(contents)} 个音频文件")

    @safe_slot
    def _on_send_message(self, text: str) -> None:
        self.proactive.on_interaction()
        # 本地指令拦截：日程（不发送给 LLM）
        if self._handle_smart_command(text):
            return
        self.state = "talk"
        self.remote_action = "talk"
        self.state_start = time.time()
        self.state_until = self.state_start + 2.5
        self._agent_step = 0  # 新一轮对话，重置工具步骤计数
        self.bubble._show_thinking()   # 「思考中」过渡 -> 打字指示器
        self.bubble.show()
        self._update_bubble_position()
        self.ws_client.send_chat(text)

    def _on_user_loaded(self, user_id: str) -> None:
        self.bubble.add_message(f"已绑定用户：{user_id}", is_user=False)

    @safe_slot
    def _on_api_error(self, error: str) -> None:
        self.bubble.add_message(error, is_user=False)
        self.bubble.show()
        self._update_bubble_position()

    @safe_slot
    def _on_chat_received(self, text: str, action: str) -> None:
        self.server_connected = True
        self._last_response_time = time.time()
        self.proactive.on_interaction()
        # 移除打字指示器并追加 Bot 回复（支持流式合并，不覆盖用户消息）
        self.bubble.append_bot_reply(text)
        self.bubble.show()
        self._update_bubble_position()
        self.remote_action = action or "idle"
        self.state = "talk"
        self.state_start = time.time()
        self.state_until = self.state_start + 3.0
        # TTS：回复后自动语音播报（默认关闭；在 pet_config.json 添加 tts_enabled: true 可恢复）
        if load_config().get("tts_enabled", False):
            self._tts_speak(text)

    def _tts_speak(self, text: str) -> None:
        """调用 GPT-SoVITS API 生成语音并播放（请求在后台线程，不阻塞 UI）"""
        import urllib.request, urllib.parse, tempfile
        try:
            api_url = load_config().get("tts_api_url", "http://127.0.0.1:9880")
            # 参考音频：优先用当前秘书舰 voice_map 的第一条语音，提示词用其自带台词
            voice_map = self._voice_map or load_voice_map(self._current_secretary)
            ref = next((it for it in voice_map if it.get("mp3")), None)
            if not ref:
                logger.info("TTS 跳过: 当前秘书舰没有可用的参考语音")
                return
            ref_audio = os.path.join(_get_voices_dir(), self._current_secretary, ref["mp3"])
            if not os.path.isfile(ref_audio):
                logger.info(f"TTS 跳过: 参考音频缺失 {ref_audio}")
                return
            ref_text = (ref.get("text") or "").strip()
            if not ref_text:
                ref_text = "今日はどっち？真珠湾？それとも珊瑚海？"
            # 参考音频语言：含假名/汉字视为日文
            prompt_lang = "ja" if any(0x3040 <= ord(c) <= 0x9FFF for c in ref_text) else "zh"
            # 回复文本:纯日文用 ja，否则用中文
            is_ja = all(ord(c) < 0x3000 or 0x3040 <= ord(c) <= 0x9FFF for c in text if c.strip())
            lang = "ja" if is_ja else "zh"
            params = urllib.parse.urlencode({
                "text": text, "text_lang": lang,
                "ref_audio_path": ref_audio,
                "prompt_lang": prompt_lang, "prompt_text": ref_text,
                "text_split_method": "cut5", "batch_size": 1,
                "media_type": "wav", "streaming_mode": "false",
                "temperature": 0.65, "top_k": 12, "top_p": 0.8,
            })
            url = f"{api_url}/tts?{params}"
            tmp_wav = os.path.join(tempfile.gettempdir(), f"{self._current_secretary}_tts.wav")
            self._bg_executor.submit(self._tts_request, url, tmp_wav)
        except Exception as e:
            logger.warning(f"TTS 失败: {e}")

    def _tts_request(self, url: str, tmp_wav: str) -> None:
        """后台线程：请求 GPT-SoVITS 并保存音频，完成后回主线程播放"""
        import urllib.request
        try:
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=60) as resp:
                data = resp.read()
            if data[:1] == b"{":
                # GPT-SoVITS 出错时返回 JSON 而不是音频
                logger.warning(f"TTS 返回错误: {data.decode('utf-8', 'ignore')[:300]}")
                return
            if not data:
                logger.info("TTS 返回空音频")
                return
            with open(tmp_wav, "wb") as f:
                f.write(data)
            self.tts_ready.emit(tmp_wav)
        except Exception as e:
            logger.info(f"TTS 请求失败（服务端未启动或超时）: {e}")

    @safe_slot
    def _play_tts_file(self, path: str) -> None:
        """主线程播放 TTS 生成的音频"""
        try:
            player = QMediaPlayer(self)
            player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
            player.mediaStatusChanged.connect(
                lambda status, _p=player: _p.deleteLater() if status == QMediaPlayer.EndOfMedia else None
            )
            player.play()
        except Exception as e:
            logger.warning(f"TTS 播放失败: {e}")

    # ── 精进功能：主动陪伴 / 日程提醒 ──
    def _on_smart_tick(self) -> None:
        """每 20s：日程到点提醒（克制）+ 主动陪伴"""
        try:
            self._check_reminders()
            self._check_proactive()
        except Exception as e:
            logger.error(f"智能模块异常: {e}")

    def _check_reminders(self) -> None:
        """日程提醒：到点入队，逐条（间隔一个 tick）展示，避免轰炸"""
        try:
            due = self.schedule_mgr.due()
            for r in due:
                if r.get("id") not in [p.get("id") for p in self._pending_reminders]:
                    self._pending_reminders.append(r)
            if self._pending_reminders:
                r = self._pending_reminders.pop(0)
                self.schedule_mgr.mark_fired(r["id"])
                self.bubble.add_message(f"⏰ {r['text']}", is_user=False)
                self.bubble.show()
                self._update_bubble_position()
        except Exception as e:
            logger.error(f"日程提醒异常: {e}")

    def _check_proactive(self) -> None:
        """主动陪伴：满足条件时主动开口（待机主界面日文语音优先）"""
        try:
            if self.isVisible() and self.state not in ("talk", "agent"):
                if self.proactive.should_fire(visible=True, talking=False):
                    # 待机轮播：主界面1/2/3 场景日文语音优先
                    if self.play_scene_voice("main"):
                        self.proactive.on_interaction()
                    else:
                        text = self.proactive.pick()
                        self.bubble.add_message(text, is_user=False)
                        self.bubble.show()
                        self._update_bubble_position()
        except Exception as e:
            logger.error(f"主动陪伴异常: {e}")

    def _handle_smart_command(self, text: str) -> bool:
        """本地指令：日程/帮助/截图 + 自然语言日程。命中返回 True（不发给 LLM）"""
        t = text.strip()
        if not t:
            return False
        # 斜杠指令：/截图 /screenshot /help
        if t.lower() in ("/截图", "/screenshot", "/screencap"):
            self._manual_screenshot()
            return True
        if t.lower() in ("/help", "/帮助", "/指令"):
            self.bubble.add_message(
                "斜杠指令：\n"
                "/截图 — 截取当前屏幕并发送\n"
                "/感知 — 开关桌面感知\n"
                "/help — 显示帮助\n\n"
                "本地指令：\n"
                "「日程」— 打开日程面板\n"
                "「提醒我 明天9点 开会」— 自然语言添加日程", is_user=False)
            self.bubble.show()
            self._update_bubble_position()
            return True
        if t.lower() in ("/感知", "/awareness"):
            self._toggle_desktop_awareness()
            return True
        if t in ("日程", "我的日程", "提醒"):
            self._open_schedule_panel()
            return True
        # 自然语言日程：提醒我 明天 9点 开会 / 每天早上8点打卡 等
        if re.search(r"(提醒|设个?提醒|添加提醒|加个?提醒|帮我安排|日程安排)", t):
            parsed = parse_schedule_nl(t)
            if parsed:
                when, content = parsed
                self.schedule_mgr.add(content, when)
                self.bubble.add_message(f"⏰ 已添加提醒：{content}（{when}）", is_user=False)
                self.bubble.show()
                self._update_bubble_position()
                return True
        if t in ("帮助", "help", "help?"):
            self.bubble.add_message(
                "桌宠指令：\n"
                "「日程」— 打开日程面板\n"
                "「提醒我 明天 9点 开会」— 自然语言添加日程\n"
                "「截图」— 截取屏幕并分析", is_user=False)
            self.bubble.show()
            self._update_bubble_position()
            return True
        return False

    def _open_schedule_panel(self) -> None:
        try:
            dlg = ScheduleDialog(self.schedule_mgr, self)
            self._center_dialog(dlg)
            dlg.exec_()
        except Exception as e:
            logger.error(f"日程面板异常: {e}")

    def _open_settings(self) -> None:
        """打开设置面板（分段式 form-card 风格）"""
        try:
            dlg = SettingsDialog(self, self)
            self._center_dialog(dlg)
            dlg.exec_()
        except Exception as e:
            logger.error(f"设置面板异常: {e}")

    def _open_manager(self) -> None:
        """打开皮肤/语音管理面板；关闭后应用改动。"""
        try:
            dlg = ManagerWindow(self)
            self._center_dialog(dlg)
            dlg.exec_()
            if dlg.changed:
                self.apply_manager_changes()
        except Exception as e:
            logger.error(f"管理面板异常: {e}")

    def _center_dialog(self, dlg) -> None:
        sr = QApplication.primaryScreen().availableGeometry()
        # 尺寸先就位（GlassDialog 构造已 resize，保险再估一次）
        dw = dlg.width() or 520
        dh = dlg.height() or 470
        pet_cx = self.x() + self.width() // 2
        screen_cx = sr.left() + sr.width() // 2
        # 桌宠在右半屏（含吸附右侧）→ 设置放到桌宠左侧；否则桌宠右侧
        if pet_cx >= screen_cx:
            x = self.x() - dw - 16
            if x < sr.left() + 10:
                x = self.x() + self.width() + 16
        else:
            x = self.x() + self.width() + 16
            if x + dw > sr.right() - 10:
                x = self.x() - dw - 16
        # 优先桌宠上方，放不下改下方，最后夹屏内
        y = self.y() - dh - 40
        if y < sr.top() + 10:
            y = self.y() + self.height() + 16
        x = max(sr.left() + 10, min(x, sr.right() - dw - 10))
        y = max(sr.top() + 10, min(y, sr.bottom() - dh - 10))
        dlg.move(int(x), int(y))

    @safe_slot
    def _on_connection_changed(self, connected: bool) -> None:
        self.server_connected = connected
        self.bubble.set_connection(connected)
        if connected:
            self._last_response_time = time.time()

    @safe_slot
    def _cycle_theme(self) -> None:
        """循环切换主题并持久化"""
        keys = list(THEME_PRESETS.keys())
        current = get_current_theme()
        if current not in keys:
            current = DEFAULT_THEME
        nxt = keys[(keys.index(current) + 1) % len(keys)]
        self._apply_theme_preset(nxt)

    @safe_slot
    def _apply_theme_preset(self, key: str, announce: bool = True) -> None:
        """应用指定主题并持久化；announce=False 时静默（设置窗即时预览用）"""
        if key not in THEME_PRESETS:
            return
        cfg = load_config()
        cfg["theme"] = key
        save_config(cfg)
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(theme_stylesheet())
        # 重新应用样式
        self.bubble._apply_theme()
        self.secretary_panel._apply_theme()
        for label in self.bubble._bubble_labels:
            if not sip.isdeleted(label):
                label._setup_style()
                label._apply_text(label._text)
        if announce:
            c = get_theme_colors()
            self.bubble.add_message(
                f"主题已切换为「{c['name']}」", is_user=False, preserve_typing=True)
        logger.info(f"主题切换: {key}")

    @safe_slot
    def _on_agent_action(self, action: str) -> None:
        """工具开始执行：在气泡顶部显示动态状态条"""
        self._agent_step += 1
        cn = AGENT_TOOL_NAMES.get(action, action)
        self.bubble.show_agent_status(
            f"正在执行：{cn}\n第 {self._agent_step} 步操作中…"
        )
        # 桌宠本体切换到 Agent 执行动画（快速晃动 + 脉冲）
        self.state = "agent"
        self.state_start = time.time()
        self.state_until = self.state_start + 30.0
        # 强制刷新 UI，让状态条先于工具执行渲染出来
        QApplication.processEvents()

    @safe_slot
    def _on_agent_result(self, action: str, summary: str, success: bool) -> None:
        """工具执行结束：更新状态条为完成态，2 秒后自动消失"""
        cn = AGENT_TOOL_NAMES.get(action, action)
        mark = "✓" if success else "✗"
        self.bubble.show_agent_status(f"{mark} {cn} {'执行完成' if success else '执行失败'}", done=True)
        # 桌宠切换回完成动画
        self.state = "agent_done"
        self.state_start = time.time()
        self.state_until = self.state_start + 1.5
        QTimer.singleShot(2200, self.bubble.clear_agent_status)

    def _menu_item(self, menu, aid: str, text: str, icon: str, cb, **kw):
        return menu.add_item(text, icon, callback=cb, **kw)

    def _on_long_press(self) -> None:
        try:
            if not self.dragging or self.locked:
                return
            self._long_press_fired = True
            menu = IconGridMenu(self)
            lock_text = "解锁位置" if self.locked else "锁定位置"
            menu.add_item(lock_text, "monitor",
                          callback=lambda: self._toggle_lock(not self.locked))
            bubble_text = "关闭气泡" if self.bubble.isVisible() else "显示气泡"
            menu.add_item(bubble_text, "chat", callback=self._toggle_bubble)
            menu.add_item("番茄钟", "timer",
                          callback=lambda: self.pomodoro.start_work())
            menu._calc_size()
            w, h = menu._total_w, menu._total_h
            sr = QApplication.primaryScreen().availableGeometry()
            x = self.x() + (self.width() - w) // 2
            y = self.y() - h - 12
            if y < sr.top() + 8:
                y = self.y() + self.height() + 12
            x = max(sr.left() + 8, min(x, sr.right() - w - 8))
            menu.popup(QPoint(int(x), int(y)))
        except Exception as e:
            logger.error(f"长按快捷盘异常: {e}")

    def _show_context_menu(self, pos: QPoint) -> None:
        try:
            menu = IconGridMenu(self)
            logger.info(f"IconGridMenu 创建成功，pos={pos}")
        except Exception as e:
            logger.error(f"IconGridMenu 创建失败: {e}")
            return

        # ── 连接服务端：一键切换 AstrBot ⇄ DSH（点一下即写配置并重连）──
        cur_port = self._current_server_port()
        target_port = 6190 if cur_port == 6191 else 6191
        menu.add_section("连接服务端")
        menu.add_item(
            f"切换到 {self._server_label(target_port)}", "monitor",
            callback=self._toggle_protocol)

        # ── 效率：番茄钟 / 日程 / 清空对话 / 气泡 ──
        menu.add_section("效率")
        pomo = menu.add_submenu("番茄钟", "timer")
        pomo.add_item("开始工作 (25分)", callback=lambda: self.pomodoro.start_work())
        pomo.add_item("开始休息 (5分)", callback=lambda: self.pomodoro.start_break())
        pomo.add_separator()
        pomo.add_item("暂停", callback=self.pomodoro.pause)
        pomo.add_item("继续", callback=self.pomodoro.resume)
        pomo.add_item("重置", callback=self.pomodoro.reset)
        pomo.add_separator()
        config_sub = pomo.add_submenu("配置时长")
        for label, minutes, is_work in [
            ("工作 15分", 15, True), ("工作 25分", 25, True), ("工作 50分", 50, True),
            ("休息 3分", 3, False), ("休息 5分", 5, False), ("休息 10分", 10, False),
        ]:
            is_checked = (self.pomodoro._work_minutes == minutes) if is_work else (self.pomodoro._break_minutes == minutes)
            config_sub.add_item(label, checkable=True, checked=is_checked,
                                callback=lambda m=minutes, w=is_work: self._set_pomodoro_time(m, w))
        self._menu_item(menu, "schedule", "日程", "calendar", self._open_schedule_panel)
        self._menu_item(menu, "clear", "清空对话", "refresh", self._clear_conversation)
        toggle_text = "关闭气泡" if self.bubble.isVisible() else "显示气泡"
        self._menu_item(menu, "bubble", toggle_text, "chat", self._toggle_bubble)

        # ── 秘书舰：切换 / 皮肤语音 ──
        menu.add_section("秘书舰")
        self._menu_item(menu, "secretary", "切换秘书舰", "person", self._show_secretary_panel)
        self._menu_item(menu, "manager", "皮肤·语音", "sparkle", self._open_manager)

        # ── 外观与系统 ──
        menu.add_section("外观与系统")

        def _snap_cb():
            self._set_corner_snap(not self.corner_snap)
        menu.add_item(
            "吸附左右边", "edge",
            checkable=True,
            checked=bool(getattr(self, "corner_snap", False)),
            callback=_snap_cb,
        )
        appearance = menu.add_submenu("外观", "palette")
        theme_sub = appearance.add_submenu("主题")
        current_theme = get_current_theme()
        theme_items: list = []
        for key, preset in THEME_PRESETS.items():
            it = theme_sub.add_item(
                preset["name"], checkable=True, checked=(key == current_theme),
                callback=None)
            theme_items.append((key, it))

        def _theme_cb(k: str):
            # 单选互斥：先清空全部勾选，点击后的 toggle 只点亮当前项
            for _k, it in theme_items:
                it["checked"] = False
            self._apply_theme_preset(k)

        for k, it in theme_items:
            it["cb"] = (lambda kk=k: _theme_cb(kk))
        appearance.add_item("缩放比例…", callback=self._open_settings)
        appearance.add_separator()
        lock_item_text = "解锁位置" if self.locked else "锁定位置"

        def _lock_cb():
            self._toggle_lock(not self.locked)
        appearance.add_item(lock_item_text, callback=_lock_cb)

        system = menu.add_submenu("系统", "monitor")
        conn_state = "已连接" if self.ws_client.connected else "未连接"
        system.add_item(f"{conn_state} · {self._server_label(cur_port)}", enabled=False)
        system.add_item("绑定用户ID", callback=self._bind_user_id)
        system.add_separator()
        system.add_item("立即截图", callback=self._manual_screenshot)
        system.add_item("桌面感知", callback=self._toggle_desktop_awareness)
        system.add_separator()
        auto_start_text = "取消开机自启" if self._is_auto_start() else "开机自启动"
        system.add_item(auto_start_text, callback=self._toggle_auto_start)
        system.add_item("隐藏桌宠", callback=self._hide_pet)

        self._menu_item(menu, "settings", "设置", "gear", self._open_settings)
        menu.add_item("退出", "power", callback=QApplication.instance().quit)

        menu.popup(pos)

    def _toggle_lock(self, checked: bool) -> None:
        self.locked = checked
        self._persist_window_pos()

    def _set_pomodoro_time(self, minutes: int, is_work: bool) -> None:
        """设置番茄钟工作/休息时长"""
        if is_work:
            self.pomodoro.set_work_minutes(minutes)
        else:
            self.pomodoro.set_break_minutes(minutes)
        save_config({
            **self.pet_config,
            "pomodoro_work_minutes": self.pomodoro._work_minutes,
            "pomodoro_break_minutes": self.pomodoro._break_minutes,
        })
        # 刷新菜单显示
        self._update_pomodoro_menu_state()

    def _update_pomodoro_menu_state(self) -> None:
        """更新番茄钟菜单项的启用/禁用状态"""
        if not hasattr(self, '_pomodoro_start_action'):
            return
        mode = self.pomodoro.get_mode()
        running = self.pomodoro.is_running()
        paused = self.pomodoro.is_paused()

        self._pomodoro_start_action.setEnabled(mode == "idle")
        self._pomodoro_break_action.setEnabled(mode == "idle")
        self._pomodoro_pause_action.setEnabled(running)
        self._pomodoro_resume_action.setEnabled(paused)
        self._pomodoro_reset_action.setEnabled(mode != "idle")

        # 更新文本显示剩余时间
        if mode != "idle":
            remaining = self.pomodoro.get_remaining_seconds()
            if mode == "work":
                self._pomodoro_start_action.setText(f"工作中 {self.pomodoro.format_time(remaining)}")
            else:
                self._pomodoro_break_action.setText(f"休息中 {self.pomodoro.format_time(remaining)}")
        else:
            self._pomodoro_start_action.setText(f"开始工作 ({self.pomodoro._work_minutes}分)")
            self._pomodoro_break_action.setText(f"开始休息 ({self.pomodoro._break_minutes}分)")

    def _hide_pet(self) -> None:
        """隐藏桌宠本体、气泡与面板（可从托盘图标恢复显示）"""
        try:
            if self.bubble:
                self.bubble.hide()
            if self.secretary_panel:
                self.secretary_panel.hide()
            self.hide()
            # 托盘提示如何恢复
            if (hasattr(self, "tray") and self.tray
                    and QSystemTrayIcon.isSystemTrayAvailable()):
                self.tray.showMessage(
                    "碧蓝桌宠", "桌宠已隐藏，点击托盘图标可恢复显示",
                    QSystemTrayIcon.Information, 2500)
        except Exception as e:
            logger.error(f"隐藏桌宠异常: {e}")

    def _set_scale(self, val: float) -> None:
        self.user_scale = val
        # 使用原图重算尺寸
        self.base_width = min(420, self.base_pixmap.width())
        scale_ratio = self.base_width / self.base_pixmap.width()
        self.base_height = int(self.base_pixmap.height() * scale_ratio)
        self.resize(int(self.base_width * val + 40), int(self.base_height * val + 40))
        # 限制在屏幕内
        sr = QApplication.primaryScreen().availableGeometry()
        self.move(min(max(sr.left(), self.x()), sr.right() - self.width()),
                  min(max(sr.top(), self.y()), sr.bottom() - self.height()))
        self._persist_window_pos()

    def _cycle_scale(self) -> None:
        """循环切换缩放比例（80→90→100→110→120→80…）"""
        current = self.user_scale
        idx = min(range(len(SCALE_STEPS)),
                  key=lambda i: abs(SCALE_STEPS[i] - current))
        next_idx = (idx + 1) % len(SCALE_STEPS)
        self._set_scale(SCALE_STEPS[next_idx])

    def _set_pomodoro_time(self, minutes: int, is_work: bool) -> None:
        """设置番茄钟工作/休息时长"""
        if is_work:
            self.pomodoro.set_work_minutes(minutes)
        else:
            self.pomodoro.set_break_minutes(minutes)
        # 保存到配置
        self.pomodoro.save_config(self.pet_config)
        save_config(self.pet_config)
        self.bubble.add_message(f"已设置{'工作' if is_work else '休息'}时长为 {minutes} 分钟", is_user=False)
        self.bubble.show()
        self._update_bubble_position()

    def _show_secretary_panel(self) -> None:
        pet_center = self.geometry().center()
        panel_w = self.secretary_panel.width()
        panel_h = self.secretary_panel.height()
        self.secretary_panel.move(pet_center.x() - panel_w // 2,
                                  pet_center.y() - panel_h // 2)
        self.secretary_panel.show()

    def _manual_screenshot(self) -> None:
        """手动截图并发送给服务器"""
        try:
            import pyautogui, base64, io
            img = pyautogui.screenshot()
            buf = io.BytesIO()
            img.convert("RGB").save(buf, format="JPEG", quality=95)
            b64 = base64.b64encode(buf.getvalue()).decode()
            self.ws_client.send_command_result("screenshot", "manual_" + str(int(time.time())), {
                "success": True,
                "data": {"image_base64": b64, "width": img.width, "height": img.height}
            })
            self.bubble.add_message("截图已发送到服务器", is_user=False)
            self.bubble.show()
            self._update_bubble_position()
            logger.info("手动截图已发送")
        except Exception as e:
            logger.error(f"截图失败: {e}")
            self.bubble.add_message(f"截图失败：{e}。详情见 pet.log", is_user=False)
            self.bubble.show()
            self._update_bubble_position()

    def _toggle_desktop_awareness(self) -> None:
        """切换桌面感知功能"""
        if not hasattr(self, '_desktop_awareness_enabled'):
            self._desktop_awareness_enabled = False
        self._desktop_awareness_enabled = not self._desktop_awareness_enabled
        status = "开启" if self._desktop_awareness_enabled else "关闭"
        # 同步开关状态到服务端（服务端据此启停主动回话）
        self.ws_client.send_awareness(self._desktop_awareness_enabled)
        if self._desktop_awareness_enabled:
            self._state_report_interval = 30.0
            self.bubble.add_message(f"桌面感知已{status}（每 30 秒上报截图）", is_user=False)
            # accent 激活态 + 呼吸发光（IconButton 自绘）
            self.bubble.awareness_btn.set_active(True)
        else:
            self._state_report_interval = 999.0
            self.bubble.add_message(f"桌面感知已{status}", is_user=False)
            self.bubble.awareness_btn.set_active(False)
        self.bubble.show()
        self._update_bubble_position()
        logger.info(f"桌面感知: {status}")

    # ── 服务端切换：AstrBot (6190) ⇄ DSH (6191) ──

    @staticmethod
    def _server_label(port: int) -> str:
        return "AstrBot (6190)" if int(port) == 6190 else "DSH (6191)"

    def _current_server_port(self) -> int:
        try:
            return int(load_config().get("server_port", 6191))
        except (TypeError, ValueError):
            return 6191

    @safe_slot
    def _set_server_port(self, port: int) -> None:
        """切换连接的服务端：写入 pet_config.server_port + 立即重连（无需重启）"""
        port = 6190 if int(port) == 6190 else 6191
        cur = self._current_server_port()
        cfg = load_config()
        cfg["server_port"] = port
        save_config(cfg)
        label = self._server_label(port)
        if port == cur and self.ws_client.connected:
            self.bubble.add_message(f"已连接 {label}", is_user=False)
            self.bubble.show()
            return
        url = f"ws://127.0.0.1:{port}/"
        logger.info(f"切换服务端: {self._server_label(cur)} -> {label} ({url})")
        self.ws_client.switch_url(url)
        self.bubble.add_message(f"正在连接 {label}…", is_user=False)
        self.bubble.show()

    def _toggle_protocol(self) -> None:
        """在两个服务端之间来回切换"""
        self._set_server_port(6190 if self._current_server_port() == 6191 else 6191)

    def _switch_secretary(self, key: str) -> None:
        try:
            self._current_secretary = key
            skins = get_available_skins(key)
            # 皮肤索引越界保护（删除皮肤后可能残留无效索引），切到新舰重置首选
            self._current_skin_idx = 0
            if skins:
                self._load_skin(skins[self._current_skin_idx])
            self._voice_map = load_voice_map(key)
            # 预加载新秘书舰的语音
            self._preload_audio_for_secretary(key)
            self._update_tray_tooltip()
            self.bubble.set_avatar(QPixmap(get_skin_path(key)))
            name = self._secretary_display_name(key)
            self.bubble.add_message(f"今日秘书舰：{name}，向您报到。", is_user=False)
        except Exception as e:
            logger.error(f"切换秘书舰异常: {e}")
        finally:
            self.secretary_panel.refresh_active(key)
            self.bubble.show()
            self._update_bubble_position()

    def _clear_conversation(self) -> None:
        """清空对话历史（本地气泡）"""
        self.bubble._on_clear()

    _AUTO_START_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
    _AUTO_START_NAME = "EnterpriseDesktopPet"

    @classmethod
    def _is_auto_start(cls) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, cls._AUTO_START_KEY) as key:
                winreg.QueryValueEx(key, cls._AUTO_START_NAME)
            return True
        except FileNotFoundError:
            return False

    def _toggle_auto_start(self) -> None:
        if self._is_auto_start():
            self._remove_auto_start()
        else:
            self._add_auto_start()

    def _add_auto_start(self) -> None:
        exe_path = sys.executable if getattr(sys, "frozen", False) else sys.argv[0]
        if not getattr(sys, "frozen", False):
            # 开发模式下用 pythonw 启动
            exe_path = f'"{sys.executable}" "{os.path.abspath(__file__)}"'
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                self._AUTO_START_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, self._AUTO_START_NAME, 0, winreg.REG_SZ, exe_path)
            self.bubble.add_message("已设置开机自启动 ✓", is_user=False)
        except Exception as e:
            self.bubble.add_message(f"设置失败：{e}。详情见 pet.log", is_user=False)

    def _remove_auto_start(self) -> None:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                self._AUTO_START_KEY, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, self._AUTO_START_NAME)
            self.bubble.add_message("已取消开机自启动", is_user=False)
        except FileNotFoundError:
            pass
        except Exception as e:
            self.bubble.add_message(f"取消失败：{e}", is_user=False)

    @staticmethod
    def _secretary_display_name(key: str) -> str:
        names = {
            "enterprise": "企业", "shoukaku": "翔鹤", "newjersey": "新泽西",
            "hood": "胡德", "zuikaku": "瑞鹤", "essex": "埃塞克斯",
            "taihou": "大凤", "yorktown2": "约克城", "belfast": "贝尔法斯特",
            "anshan": "鞍山",
        }
        return names.get(key, key)

    @safe_slot
    def _on_pomodoro_tick(self, remaining: int, mode: str) -> None:
        """番茄钟倒计时：仅更新内部状态供 paintEvent 绘制，避免气泡每秒重绘闪烁"""
        # 检测从 idle 到 work/break 的转换，隐藏聊天气泡避免遮挡倒计时
        if self._pomodoro_prev_mode == "idle" and mode != "idle":
            if self.bubble and self.bubble.isVisible():
                self.bubble.hide()
        # 检测从 work/break 到 idle 的转换（如手动重置），恢复显示聊天气泡
        elif self._pomodoro_prev_mode != "idle" and mode == "idle":
            if self.bubble and not self.bubble.isVisible():
                self.bubble.show()
                self._update_bubble_position()
        self._pomodoro_remaining = remaining
        self._pomodoro_mode = mode
        self._pomodoro_prev_mode = mode
        # 更新右键菜单显示的剩余时间
        self._update_pomodoro_menu_state()
        # 触发桌宠重绘以显示倒计时
        self.update()

    @safe_slot
    def _on_pomodoro_finished(self, mode: str) -> None:
        """番茄钟完成：语音播报 + 气泡提示"""
        # 清除倒计时状态
        self._pomodoro_remaining = 0
        self._pomodoro_mode = "idle"
        self._pomodoro_prev_mode = "idle"
        self._pomodoro_bubble = None
        # 收工场景日文语音（回港）优先播放
        self.play_scene_voice("return")
        if mode == "work":
            msg = "番茄钟工作时间结束，休息一下吧！"
            self._play_notification_sound()
        else:
            msg = "休息结束，可以继续工作了！"
            self._play_notification_sound()
        self.bubble.add_message(msg, is_user=False)
        self.bubble.show()
        self._update_bubble_position()
        # 结束脉冲：桌宠轻快弹跳 ~2s
        self.state = "pulse"
        self.state_start = time.time()
        self.state_until = self.state_start + 2.0
        # 触发桌宠重绘以清除倒计时显示
        self.update()
        # 保存完成计数
        cfg = {**self.pet_config}
        self.pomodoro.save_config(cfg)
        save_config(cfg)

    def _play_notification_sound(self) -> None:
        """播放提示音（复用现有 QMediaPlayer 机制）"""
        try:
            # 使用当前秘书舰的语音播放器播放一段简短提示音
            # 这里复用现有的语音播放逻辑，播放第一条可用语音作为提示
            secretary = self._current_secretary
            player = self._audio_players.get(secretary)
            contents = self._audio_contents.get(secretary, [])
            if player and contents:
                player.setMedia(contents[0])
                player.play()
        except Exception as e:
            logger.error(f"番茄钟提示音播放失败: {e}")

    def _toggle_bubble(self) -> None:
        if self.bubble.isVisible():
            self.bubble.hide()
            return
        self.bubble.show()
        self._update_bubble_position()

    def _bind_user_id(self) -> None:
        """绑定用户（固定管理员，无需手动设置）"""
        self.bubble.add_message("当前已固定为管理员身份，无需手动绑定。", is_user=False)
        self.bubble.show()
        self._update_bubble_position()

    def _tick(self) -> None:
        try:
            self._tick_impl()
        except Exception as e:
            print(f"[桌面宠物] 动画循环异常: {e}", file=sys.stderr)

    def _tick_impl(self) -> None:
        now = time.time()
        dt = min(0.05, max(1e-4, now - self.last_tick))
        self.last_tick = now

        # 防御性检查：state_until 未初始化或异常值时重置
        if not isinstance(self.state_until, (int, float)) or self.state_until < 0:
            self.state_until = 0.0
        if not isinstance(self.state_start, (int, float)) or self.state_start < 0:
            self.state_start = now

        if now > self.state_until and self.state != "idle":
            self.state = "idle"
            self.remote_action = "idle"

        # 自然呼吸动画 - 缓存 sin 计算避免重复
        breath_t = now * 1.5
        sin_breath = math.sin(breath_t)
        sin_breath_2x = math.sin(breath_t * 2)
        self.float_y = sin_breath * 6.0 + sin_breath_2x * 1.5
        self.talk_sway_x = 0.0
        self.scale = 1.0

        if self.state == "click":
            progress = (now - self.state_start) / 0.35
            progress = max(0.0, min(1.0, progress))
            eased = 1 - (1 - progress) ** 3  # easeOutCubic
            sin_eased_pi = math.sin(eased * math.pi)
            self.scale = 1.0 - 0.15 * sin_eased_pi
            self.float_y -= sin_eased_pi * 14.0
        elif self.state == "talk":
            # 说话时的微妙脉动和摆动 - 缓存 sin 值
            sin_7 = math.sin(now * 7.0)
            sin_13 = math.sin(now * 13.0)
            self.scale = 1.0 + sin_7 * 0.012 + sin_13 * 0.005
            amp = 6.0 if self.remote_action == "wave" else 4.0
            sin_85 = math.sin(now * 8.5)
            sin_17 = math.sin(now * 17.0)
            self.talk_sway_x = sin_85 * amp + sin_17 * 1.5
        elif self.state == "agent":
            # Agent 思考/执行：快速晃动 + 脉冲 - 缓存 sin 值
            sin_10 = math.sin(now * 10.0)
            sin_20 = math.sin(now * 20.0)
            self.scale = 1.0 + sin_10 * 0.035 + sin_20 * 0.01
            sin_12 = math.sin(now * 12.0)
            sin_24 = math.sin(now * 24.0)
            self.talk_sway_x = sin_12 * 7.0 + sin_24 * 2.0
        elif self.state == "agent_done":
            # 完成状态：轻快的弹跳
            progress = min(1.0, (now - self.state_start) / 1.5)
            eased = 1 - (1 - progress) ** 4  # easeOutQuart
            sin_6 = math.sin(now * 6.0)
            sin_8 = math.sin(now * 8.0)
            self.scale = 1.0 + (1 - eased) * sin_6 * 0.025
            self.talk_sway_x = (1 - eased) * sin_8 * 3.0
        elif self.state == "pulse":
            # 番茄钟结束脉冲：衰减弹跳
            progress = max(0.0, min(1.0, (now - self.state_start) / 2.0))
            decay = 1.0 - progress
            sin_8 = math.sin(now * 8.0)
            sin_16 = math.sin(now * 16.0)
            self.scale = 1.0 + decay * (abs(sin_8) * 0.12 + abs(sin_16) * 0.04)
            self.float_y -= decay * abs(sin_8) * 18.0
        else:
            # 未知状态：重置为 idle，防止卡死
            if self.state != "idle":
                self.state = "idle"
                self.remote_action = "idle"
                self.state_until = 0.0

        # 过渡动画进度 - 使用平滑步进
        if self._transition_progress < 1.0:
            self._transition_progress = min(1.0, self._transition_progress + dt * 8.0)

        # 连接状态超时检测
        if self._last_response_time > 0 and (now - self._last_response_time) > 30:
            self.server_connected = False

        if not self.dragging and not self.locked:
            self._apply_inertia(dt)

        # 桌面状态上报防抖（每 5 秒）——异步执行避免阻塞主线程
        if time.time() - self._last_state_report > self._state_report_interval:
            self._last_state_report = time.time()
            self._bg_executor.submit(self._report_desktop_state)

        self._update_bubble_position()
        self.update()

    def _report_desktop_state(self) -> None:
        """后台线程获取活动窗口并上报，避免阻塞 UI"""
        try:
            import pygetwindow as gw
            active = gw.getActiveWindow()
            if active and active.title:
                # 如果桌面感知开启，附带截图
                screenshot_b64 = None
                awareness = getattr(self, '_desktop_awareness_enabled', False)
                logger.info(f"桌面状态上报检查: awareness={awareness}")
                if awareness:
                    try:
                        import pyautogui, base64, io
                        img = pyautogui.screenshot()
                        buf = io.BytesIO()
                        q = max(10, min(100, int(getattr(self, "_screenshot_quality", 60))))
                        img.convert("RGB").save(buf, format="JPEG", quality=q)
                        screenshot_b64 = base64.b64encode(buf.getvalue()).decode()
                        logger.info(f"截图成功，质量={q}，大小={len(screenshot_b64)}")
                    except Exception as e:
                        logger.error(f"桌面感知截图失败: {e}")
                logger.info(f"桌面状态上报: {active.title}, 截图={'有' if screenshot_b64 else '无'}")
                # 回主线程发送
                QApplication.instance().postEvent(
                    self,
                    _DesktopStateEvent(active.title, "", screenshot_b64)
                )
        except Exception as e:
            logger.error(f"桌面状态上报异常: {e}")

    def customEvent(self, event) -> None:  # type: ignore[override]
        try:
            if isinstance(event, _DesktopStateEvent):
                self.ws_client.send_desktop_state(event.title, event.process, event.screenshot_base64)
        except Exception as e:
            logger.error(f"customEvent 异常: {e}")

    def _apply_inertia(self, dt: float) -> None:
        speed = math.hypot(self.inertia_velocity.x(), self.inertia_velocity.y())
        if speed < 1.0:
            self.inertia_velocity = QPointF(0.0, 0.0)
            return
        x = self.x() + int(self.inertia_velocity.x() * dt)
        y = self.y() + int(self.inertia_velocity.y() * dt)
        screen_rect = QApplication.primaryScreen().availableGeometry()
        min_x = screen_rect.left()
        max_x = screen_rect.right() - self.width()
        min_y = screen_rect.top()
        max_y = screen_rect.bottom() - self.height()
        x = max(min_x, min(max_x, x))
        y = max(min_y, min(max_y, y))
        self.move(x, y)
        friction = pow(0.84, dt * 60.0)
        self.inertia_velocity = QPointF(
            self.inertia_velocity.x() * friction,
            self.inertia_velocity.y() * friction,
        )

    def _update_bubble_position(self) -> None:
        # 钉住：气泡停在原位，不再跟随桌宠
        if getattr(getattr(self, "bubble", None), "_pinned", False):
            return
        if self.bubble is None or sip.isdeleted(self.bubble):
            return
        # 隐藏时也预定位（before_show 在 show 前调用）：首帧即在正确坐标，避免先闪旧位再跳
        gap = 8
        bw, bh = self.bubble.width(), self.bubble.height()
        # 水平居中于桌宠
        x = self.x() + (self.width() - bw) // 2
        # 优先贴桌宠上方；上方放不下则改贴下方，避免被 screen.top 硬吸到屏幕顶
        screen = QApplication.primaryScreen().availableGeometry()
        x = max(screen.left(), min(x, screen.right() - bw))
        y_above = self.y() - bh - gap
        if y_above >= screen.top():
            y = y_above
        else:
            y_below = self.y() + self.height() + gap
            if y_below + bh <= screen.bottom():
                y = y_below
            else:
                # 上下都放不下：夹在屏内，仍尽量靠近桌宠
                y = max(screen.top(), min(y_above, screen.bottom() - bh))
        # 位置未变化时跳过 move，避免无谓的事件与重绘
        if getattr(self, "_bubble_last_pos", None) != (x, y):
            self.bubble.move(x, y)
            self._bubble_last_pos = (x, y)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        try:
            logger.info("DesktopPet 关闭中...")
            if hasattr(self, 'ws_client') and self.ws_client:
                self.ws_client._heartbeat_timer.stop()
                self.ws_client._queue_timer.stop()
                self.ws_client._heartbeat_check_timer.stop()
                self.ws_client.reconnect_timer.stop()
                if self.ws_client.ws:
                    try:
                        self.ws_client.ws.close()
                    except Exception:
                        pass
            if hasattr(self, 'bubble') and self.bubble:
                self.bubble.close()
            # 关闭后台线程池
            if hasattr(self, '_bg_executor') and self._bg_executor:
                self._bg_executor.shutdown(wait=False)
            # 保存配置：合并 load_config，避免局部 dict 冲掉 corner_snap/api_key 等键
            cfg = load_config()
            cfg.update({
                "pos_x": self.x(),
                "pos_y": self.y(),
                "scale": self.user_scale,
                "locked": self.locked,
                "theme": get_current_theme(),
                "corner_snap": bool(getattr(self, "corner_snap", False)),
            })
            self.pomodoro.save_config(cfg)
            save_config(cfg)
            self.anim_timer.stop()
            logger.info("DesktopPet 已关闭")
        except Exception as e:
            logger.error(f"closeEvent 异常: {e}")
        super().closeEvent(event)


class GlassTile(QFrame):
    """右键一级界面同款实体磁贴：bg_secondary 高不透明底 + 1px 边 + RADIUS_CARD，悬停 accent 微光"""

    def __init__(self, parent=None, radius: int = RADIUS_CARD, hover_glow: bool = True):
        super().__init__(parent)
        self._tile_radius = int(radius)
        self._tile_hover = bool(hover_glow)
        self._tile_hot = False
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        # 必须用选择器限定：无选择器的 border:none 会级联到子控件，
        # 把输入框/按钮的边框和底色抹成“裸文字”（云白/粉樱下尤其明显）
        self.setProperty("bgClear", "true")
        self.setStyleSheet('[bgClear="true"] { background: transparent; border: none; }')

    def enterEvent(self, event) -> None:  # type: ignore[override]
        self._tile_hot = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # type: ignore[override]
        self._tile_hot = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, event) -> None:  # type: ignore[override]
        try:
            p = QPainter(self)
            p.setRenderHint(QPainter.Antialiasing, True)
            c = get_theme_colors()
            r = self.rect()
            if r.width() < 6 or r.height() < 6:
                return
            rr = self._tile_radius
            if self._tile_hover and self._tile_hot:
                glow = _hex_to_qcolor(c.get("accent_glow", c.get("accent", "#888")))
                glow.setAlphaF(0.32)
                p.setPen(Qt.NoPen)
                p.setBrush(glow)
                p.drawRoundedRect(r.adjusted(-3, -3, 3, 3), rr + 3, rr + 3)
            # 与 _draw_icon_cell 一致：GLASS_ALPHA_SOLID 可读面，避免透底干扰文字
            bg = _hex_to_qcolor(c["bg_secondary"])
            bg.setAlpha(GLASS_ALPHA_SOLID)
            p.setBrush(bg)
            p.setPen(QPen(_hex_to_qcolor(c["border"]), 1))
            p.drawRoundedRect(r, rr, rr)
            light = _hex_to_qcolor(c.get("border_light", "rgba(255,255,255,0.35)"))
            p.setPen(QPen(light, 1))
            p.drawLine(r.left() + rr // 2, r.top() + 1,
                       r.right() - rr // 2, r.top() + 1)
            p.end()
        except Exception as e:
            logger.error(f"GlassTile.paintEvent 异常: {e}")


class _VoiceEntryCard(GlassTile):
    """语音磁贴行：实体玻璃底 + 16px 正文，字段就地编辑（对齐右键一级磁贴）"""

    dirty = pyqtSignal()

    def __init__(self, schema: str, data: dict, voice_dir: str,
                 play_fn, parent=None):
        super().__init__(parent, radius=RADIUS_CARD, hover_glow=True)
        self._schema = schema
        self._data = dict(data)
        self._voice_dir = voice_dir
        self._play_fn = play_fn
        c = get_theme_colors()

        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 12, 10)
        lay.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)

        skin_chip = QLabel("皮肤")
        skin_chip.setStyleSheet(
            f"color: {c['fg_muted']}; font-size: 16px; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        top.addWidget(skin_chip)

        self.skin_edit = QLineEdit(str(data.get("skin", "")))
        self.skin_edit.setPlaceholderText("皮肤名")
        self.skin_edit.setFixedWidth(120)
        self._style_line(self.skin_edit, bold=True)
        top.addWidget(self.skin_edit)

        self.scene_edit = None
        self.jp_edit = None
        if schema == "jp":
            scene_chip = QLabel("场景")
            scene_chip.setStyleSheet(skin_chip.styleSheet())
            top.addWidget(scene_chip)
            self.scene_edit = QLineEdit(str(data.get("scene", "")))
            self.scene_edit.setPlaceholderText("场景")
            self.scene_edit.setFixedWidth(100)
            self._style_line(self.scene_edit)
            top.addWidget(self.scene_edit)

        text_chip = QLabel("台词")
        text_chip.setStyleSheet(skin_chip.styleSheet())
        top.addWidget(text_chip)
        self.text_edit = QLineEdit(str(data.get("text", "")))
        self.text_edit.setPlaceholderText("台词内容…")
        self._style_line(self.text_edit, bold=True)
        top.addWidget(self.text_edit, 1)

        if schema == "cn":
            jp_chip = QLabel("日文")
            jp_chip.setStyleSheet(skin_chip.styleSheet())
            top.addWidget(jp_chip)
            self.jp_edit = QLineEdit(str(data.get("jp", "")))
            self.jp_edit.setPlaceholderText("可选")
            self.jp_edit.setFixedWidth(130)
            self._style_line(self.jp_edit)
            top.addWidget(self.jp_edit)
        else:
            self.jp_edit = None

        fname = str(data.get("mp3") if schema == "cn" else data.get("file", ""))
        self._fname = fname
        play = IconButton("play", "试听" if fname else "未选择音频", size=36)
        play.setEnabled(bool(fname))
        play.clicked.connect(lambda: self._play_fn(
            os.path.join(self._voice_dir, self._fname) if self._fname_valid() else ""))
        top.addWidget(play)
        self._play_btn = play

        del_btn = IconButton("x", "删除此条", size=34)
        del_btn.clicked.connect(lambda: self._emit("delete"))
        top.addWidget(del_btn)
        lay.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(10)
        audio_lab = QLabel("音频")
        audio_lab.setStyleSheet(skin_chip.styleSheet())
        bottom.addWidget(audio_lab)
        file_btn = QPushButton(os.path.basename(fname) if fname else "选择音频…")
        file_btn.setCursor(Qt.PointingHandCursor)
        file_btn.setStyleSheet(
            f"QPushButton {{ color: {c['fg']}; font-size: 16px; font-weight: 500;"
            f" background: {c['input_bg']}; border: 1px solid {c['input_border']};"
            f" border-radius: {RADIUS_CARD}px; padding: 7px 14px; text-align: left; }}"
            f" QPushButton:hover {{ border-color: {c['accent']};"
            f" background: {c['btn_secondary_hover']}; }}"
        )
        file_btn.clicked.connect(self._pick_file)
        self._file_btn = file_btn
        bottom.addWidget(file_btn)

        self.matched_cb = None
        self.missing_cb = None
        if schema == "jp":
            self.matched_cb = QCheckBox("有效")
            self.matched_cb.setChecked(bool(data.get("matched", True)))
            self.missing_cb = QCheckBox("缺失")
            self.missing_cb.setChecked(bool(data.get("missing", False)))
            for cb in (self.matched_cb, self.missing_cb):
                cb.setStyleSheet(
                    f"QCheckBox {{ color: {c['fg']}; font-size: 16px; font-weight: 500;"
                    f" background: transparent; border: none; spacing: 6px; }}"
                    f" QCheckBox:hover {{ color: {c['accent']}; }}"
                )
                cb.toggled.connect(lambda *_: self.dirty.emit())
                bottom.addWidget(cb)
        bottom.addStretch(1)
        lay.addLayout(bottom)

        for w in (self.skin_edit, self.text_edit, self.jp_edit, self.scene_edit):
            if w is not None:
                w.textChanged.connect(lambda *_: self.dirty.emit())

    @staticmethod
    def _style_line(edit: QLineEdit, bold: bool = False) -> None:
        c = get_theme_colors()
        weight = 600 if bold else 500
        edit.setStyleSheet(
            f"QLineEdit {{ background: {c['input_bg']}; border: 1px solid {c['input_border']};"
            f" color: {c['fg']}; font-size: 17px; font-weight: {weight};"
            f" padding: 8px 12px; border-radius: {RADIUS_CARD}px; }}"
            f" QLineEdit:hover {{ border-color: {_theme_rgba('accent', 90)}; }}"
            f" QLineEdit:focus {{ background: {c['input_bg']}; color: {c['fg']};"
            f" border: 1px solid {c['accent']}; }}"
            f" QLineEdit::placeholder {{ color: {c['fg_muted']}; font-weight: 400; }}"
        )

    def _fname_valid(self) -> bool:
        return bool(self._fname) and os.path.isfile(
            os.path.join(self._voice_dir, self._fname))

    def _play(self) -> None:
        if self._fname_valid():
            self._play_fn(os.path.join(self._voice_dir, self._fname))

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择语音文件", self._voice_dir or "", "音频 (*.mp3)")
        if not path:
            return
        self._fname = os.path.basename(path)
        self._file_btn.setText(self._fname)
        self.dirty.emit()

    def _emit(self, kind: str) -> None:
        parent = self.parent()
        while parent is not None and not isinstance(parent, ManagerWindow):
            parent = parent.parent()
        if parent is not None:
            parent._on_voice_card_event(kind, self)

    def to_row(self) -> dict:
        cn = self._schema == "cn"
        row = {
            "skin": self.skin_edit.text().strip(),
            "text": self.text_edit.text().strip(),
        }
        if cn:
            row["mp3"] = self._fname
            row["jp"] = (self.jp_edit.text().strip() if self.jp_edit else "")
        else:
            row["scene"] = self.scene_edit.text().strip() if hasattr(self, "scene_edit") else ""
            row["file"] = self._fname
            row["matched"] = bool(self.matched_cb and self.matched_cb.isChecked())
            row["missing"] = bool(self.missing_cb and self.missing_cb.isChecked())
        return row


class ManagerWindow(GlassDialog):
    """皮肤 · 语音 · 台词工作台（重构）：
    左栏秘书舰上下文 + 右栏皮肤/语音分区；
    皮肤：单击选中、显式「穿上」；语音：顶栏命令条 + 扁平行内编辑。
    业务 API（changed / 脏检查 / 保存加载）保持不变。"""

    def __init__(self, pet, parent=None) -> None:
        super().__init__("皮肤 · 语音 · 台词", 1080, 820, parent)
        self.pet = pet
        self.changed = False
        self._voice_dirty = False
        self._voice_guard = False
        self._skin_data: dict = {}
        self._cur_sec: str = SECRETARY_NAMES[0]
        self._cur_voice_path: Optional[str] = None
        self._cur_voice_dir: Optional[str] = None
        self._preview_player = None
        self._voice_cards: list[_VoiceEntryCard] = []

        c = get_theme_colors()
        section_ss = (
            f"color: {c['fg_muted']}; font-size: 16px; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(16)

        # ── 左栏：秘书舰上下文（实体磁贴 + 列表） ──
        side = QWidget()
        side.setFixedWidth(188)
        clear_container_bg(side)
        side_lay = QVBoxLayout(side)
        side_lay.setContentsMargins(0, 0, 0, 0)
        side_lay.setSpacing(0)
        side_tile = GlassTile(side, hover_glow=False)
        tile_lay = QVBoxLayout(side_tile)
        tile_lay.setContentsMargins(12, 14, 12, 14)
        tile_lay.setSpacing(4)
        cap = QLabel("秘书舰")
        cap.setStyleSheet(section_ss)
        tile_lay.addWidget(cap)

        self.nav = QListWidget()
        self.nav.setObjectName("navList")
        self.nav.setStyleSheet(
            f"QListWidget#navList {{ background: transparent; border: none;"
            f" font-size: 17px; outline: none; color: {c['fg']}; }}"
            f" QListWidget#navList::item {{ padding: 12px 14px; border-radius: {RADIUS_CARD}px;"
            f" margin: 2px 0; color: {c['fg']}; font-size: 17px; }}"
            f" QListWidget#navList::item:selected {{"
            f" background: {_theme_rgba('accent', 52)}; color: {c['fg']};"
            f" border-left: 3px solid {c['accent']};"
            f" font-weight: 600; }}"
            f" QListWidget#navList::item:hover {{ background: {c['btn_secondary_hover']}; }}"
        )
        for key in SECRETARY_NAMES:
            name = SecretaryPanel.DISPLAY_NAMES.get(key, key)
            self.nav.addItem(QListWidgetItem(name))
            self.nav.item(self.nav.count() - 1).setData(Qt.UserRole, key)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        tile_lay.addWidget(self.nav, 1)
        side_lay.addWidget(side_tile, 1)
        body.addWidget(side)

        # ── 右栏 ──
        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(10)
        self.title_lab = GradientTitleLabel("企业", size=17,
                                            align=Qt.AlignLeft | Qt.AlignVCenter)
        head.addWidget(self.title_lab, 1)

        self._seg_group = QButtonGroup(self)
        self._seg_group.setExclusive(True)
        self._seg_buttons: list[SegmentButton] = []
        self._stack = QStackedWidget()
        self._page_anim: Optional[QPropertyAnimation] = None

        seg_skin = SegmentButton("皮肤", "palette")
        seg_voice = SegmentButton("语音 · 台词", "chat")
        for i, b in enumerate((seg_skin, seg_voice)):
            b.setChecked(i == 0)
            self._seg_group.addButton(b)
            self._seg_buttons.append(b)
            idx = i
            b.clicked.connect(lambda _=False, i=idx: self._switch_page(i))
            head.addWidget(b)
        right.addLayout(head)

        self._stack.addWidget(self._build_skin_page())
        self._stack.addWidget(self._build_voice_page())
        right.addWidget(self._stack, 1)

        # ── 底部操作 ──
        foot = QHBoxLayout()
        foot.setSpacing(8)
        foot.setContentsMargins(0, 4, 0, 0)
        self.foot_status = QLabel("")
        self.foot_status.setStyleSheet(
            f"color: {c['fg_muted']}; font-size: 16px; border: none;"
            f" background: transparent;"
        )
        foot.addWidget(self.foot_status, 1)
        close_btn = QPushButton("关闭")
        close_btn.setProperty("secondary", "true")
        close_btn.setCursor(Qt.PointingHandCursor)
        close_btn.clicked.connect(self._on_close)
        apply_btn = QPushButton("应用并关闭")
        apply_btn.setProperty("primary", "true")
        apply_btn.setCursor(Qt.PointingHandCursor)
        apply_btn.clicked.connect(self._on_apply)
        foot.addWidget(close_btn)
        foot.addWidget(apply_btn)
        right.addLayout(foot)

        body.addLayout(right, 1)
        self._body.addLayout(body, 1)

        self.setStyleSheet(f"""
            ManagerWindow QLabel {{ background: transparent; border: none; }}
            ManagerWindow QLineEdit, ManagerWindow QComboBox {{
                font-size: 17px;
                padding: 9px 14px;
                color: {c["fg"]};
                background: {c["input_bg"]};
                border: 1px solid {c["input_border"]};
                border-radius: {RADIUS_CARD}px;
            }}
            ManagerWindow QLineEdit:hover, ManagerWindow QComboBox:hover {{
                border-color: {_theme_rgba("accent", 120)};
            }}
            ManagerWindow QLineEdit:focus, ManagerWindow QComboBox:focus {{
                background: {c["input_bg"]};
                border: 1px solid {c["accent"]};
            }}
            ManagerWindow QPushButton {{
                font-size: 16px;
                font-weight: 600;
            }}
            ManagerWindow QPushButton[secondary="true"] {{
                color: {c["fg"]};
                background: {c["input_bg"]};
                border: 1px solid {c["input_border"]};
                border-radius: {RADIUS_CARD}px;
                padding: 9px 18px;
            }}
            ManagerWindow QPushButton[secondary="true"]:hover {{
                background: {c["btn_secondary_hover"]};
                border: 1px solid {c["accent"]};
                color: {c["accent"]};
            }}
            ManagerWindow QPushButton[primary="true"] {{
                color: #ffffff;
                background: {c["btn_primary"]};
                border: 1px solid {c["btn_primary"]};
                border-radius: {RADIUS_CARD}px;
                padding: 9px 18px;
            }}
            ManagerWindow QPushButton[primary="true"]:hover {{
                background: {c["btn_primary_hover"]};
                border: 1px solid {c["btn_primary_hover"]};
            }}
            ManagerWindow QPushButton[danger="true"] {{
                color: #ffffff;
                background: {c["btn_danger"]};
                border: 1px solid {c["btn_danger"]};
                border-radius: {RADIUS_CARD}px;
                padding: 9px 18px;
            }}
            ManagerWindow QPushButton[danger="true"]:hover {{
                background: {c["btn_danger_hover"]};
                border: 1px solid {c["btn_danger_hover"]};
            }}
            ManagerWindow QListWidget#skinGrid {{
                background: transparent; border: none; outline: none;
            }}
            ManagerWindow QListWidget#skinGrid::item {{
                border-radius: {RADIUS_CARD}px;
                padding: 6px;
                background: {_theme_rgba("bg_secondary", GLASS_ALPHA_SOLID)};
                font-size: 15px;
                color: {c["fg"]};
            }}
            ManagerWindow QListWidget#skinGrid::item:selected {{
                background: {_theme_rgba("accent", 55)};
                border: 1px solid {_theme_rgba("accent", 120)};
            }}
            ManagerWindow QListWidget#skinGrid::item:hover {{
                background: {c["btn_secondary_hover"]};
            }}
            ManagerWindow QScrollBar {{ background: transparent; width: 12px; }}
            ManagerWindow QScrollBar::handle:vertical {{
                background: {c["scrollbar_handle"]};
                border-radius: {RADIUS_PILL}px;
                min-height: 36px;
            }}
            ManagerWindow QScrollBar::add-line, ManagerWindow QScrollBar::sub-line {{
                height: 0; width: 0;
            }}
        """)

        try:
            cur = get_current_secretary()
        except Exception:
            cur = SECRETARY_NAMES[0]
        row = SECRETARY_NAMES.index(cur) if cur in SECRETARY_NAMES else 0
        self.nav.blockSignals(True)
        self.nav.setCurrentRow(row)
        self.nav.blockSignals(False)
        self._cur_sec = SECRETARY_NAMES[row]
        self.title_lab.setText(SecretaryPanel.DISPLAY_NAMES.get(self._cur_sec, self._cur_sec))
        self._refresh_skin_page()
        self._refresh_voice_page()

    # ── 导航 ──

    def _switch_page(self, index: int) -> None:
        """切皮肤/语音页：淡入 + 轻微上移感（透明度），避免硬切无反馈"""
        cur = self._stack.currentIndex()
        if cur == index:
            return
        self._stack.setCurrentIndex(index)
        w = self._stack.widget(index)
        if w is None:
            return
        try:
            if getattr(self, "_page_anim", None) is not None:
                try:
                    self._page_anim.stop()
                except Exception:
                    pass
            eff = QGraphicsOpacityEffect(w)
            w.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", w)
            anim.setDuration(220)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def _clear(*_args, widget=w, animation=None):
                try:
                    widget.setGraphicsEffect(None)
                except Exception:
                    pass

            anim.finished.connect(_clear)
            anim.start(QAbstractAnimation.DeleteWhenStopped)
            self._page_anim = anim
        except Exception as e:
            logger.error(f"页面切换动画失败: {e}")

    def _on_nav_changed(self, row: int) -> None:
        if not (0 <= row < len(SECRETARY_NAMES)):
            return
        if self._voice_dirty:
            if not self._confirm_discard_voice():
                prev = SECRETARY_NAMES.index(self._cur_sec)
                self.nav.blockSignals(True)
                self.nav.setCurrentRow(prev)
                self.nav.blockSignals(False)
                return
        self._cur_sec = SECRETARY_NAMES[row]
        self.title_lab.setText(
            SecretaryPanel.DISPLAY_NAMES.get(self._cur_sec, self._cur_sec))
        self._refresh_skin_page()
        self._refresh_voice_page()

    # ── 皮肤页 ──

    def _build_skin_page(self) -> QWidget:
        w = QWidget()
        clear_container_bg(w)
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(14)

        c = get_theme_colors()
        section_ss = (
            f"color: {c['fg_muted']}; font-size: 16px; font-weight: 600;"
            f" background: transparent; border: none;"
        )
        label_ss = (
            f"color: {c['fg']}; font-size: 17px; font-weight: 600;"
            f" background: transparent; border: none;"
        )

        # 缩略图画廊
        left_host = QWidget()
        clear_container_bg(left_host)
        left = QVBoxLayout(left_host)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(8)
        gallery_cap = QLabel("已拥有皮肤")
        gallery_cap.setStyleSheet(section_ss)
        left.addWidget(gallery_cap)
        gallery_hint = QLabel("单击选中 · 点「穿上这件」或双击应用")
        gallery_hint.setStyleSheet(
            f"color: {c['fg_muted']}; font-size: 16px; border: none;"
            f" background: transparent;"
        )
        left.addWidget(gallery_hint)

        gallery_tile = GlassTile(left_host, hover_glow=False)
        g_lay = QVBoxLayout(gallery_tile)
        g_lay.setContentsMargins(10, 10, 10, 10)
        self.skin_grid = QListWidget()
        self.skin_grid.setObjectName("skinGrid")
        self.skin_grid.setViewMode(QListWidget.IconMode)
        self.skin_grid.setResizeMode(QListWidget.Adjust)
        self.skin_grid.setMovement(QListWidget.Static)
        self.skin_grid.setGridSize(QSize(118, 146))
        self.skin_grid.setIconSize(QSize(96, 96))
        self.skin_grid.setSpacing(10)
        self.skin_grid.currentRowChanged.connect(self._on_skin_selected)
        self.skin_grid.itemDoubleClicked.connect(self._on_skin_double)
        g_lay.addWidget(self.skin_grid)
        left.addWidget(gallery_tile, 1)
        lay.addWidget(left_host, 1)

        # 详情：整块实体磁贴
        detail_host = GlassTile(w, hover_glow=False)
        detail_host.setFixedWidth(372)
        detail = QVBoxLayout(detail_host)
        detail.setContentsMargins(18, 16, 18, 16)
        detail.setSpacing(8)
        det_cap = QLabel("皮肤命名与映射")
        det_cap.setStyleSheet(section_ss)
        detail.addWidget(det_cap)

        self.skin_preview = QLabel("")
        self.skin_preview.setObjectName("skinPreview")
        self.skin_preview.setAlignment(Qt.AlignCenter)
        self.skin_preview.setMinimumHeight(220)
        self.skin_preview.setStyleSheet(
            f"QLabel#skinPreview {{ border: 1px solid {c['border']};"
            f" border-radius: {RADIUS_CARD}px;"
            f" background: {c['input_bg']};"
            f" color: {c['fg_muted']}; font-size: 16px; }}"
        )
        detail.addWidget(self.skin_preview, 1)

        self.skin_use_badge = QLabel("")
        self.skin_use_badge.setAlignment(Qt.AlignCenter)
        self.skin_use_badge.setStyleSheet(
            f"color: {c['accent']}; font-size: 17px; font-weight: 700;"
            f" background: {_theme_rgba('accent', 40)};"
            f" border: 1px solid {_theme_rgba('accent', 90)};"
            f" border-radius: {RADIUS_PILL}px; padding: 7px 12px;"
        )
        self.skin_use_badge.hide()
        detail.addWidget(self.skin_use_badge)

        # 主操作：穿上这件（单击选中 + 显式应用，双击仍可用）
        self.skin_wear_btn = QPushButton("穿上这件")
        self.skin_wear_btn.setProperty("primary", "true")
        self.skin_wear_btn.setCursor(Qt.PointingHandCursor)
        self.skin_wear_btn.setEnabled(False)
        self.skin_wear_btn.clicked.connect(lambda: self._wear_skin())
        detail.addWidget(self.skin_wear_btn)

        form = QVBoxLayout()
        form.setSpacing(10)

        row1 = QVBoxLayout()
        row1.setSpacing(4)
        lab1 = QLabel("皮肤名称")
        lab1.setStyleSheet(label_ss)
        row1.addWidget(lab1)
        self.skin_name_edit = QLineEdit()
        self.skin_name_edit.setPlaceholderText("例如：白鹰·誓约")
        row1.addWidget(self.skin_name_edit)
        form.addLayout(row1)

        row2 = QVBoxLayout()
        row2.setSpacing(4)
        lab2 = QLabel("语音皮肤名")
        lab2.setStyleSheet(label_ss)
        row2.addWidget(lab2)
        self.skin_jp_edit = QLineEdit()
        self.skin_jp_edit.setPlaceholderText("voice_map.json 中的 skin 字段")
        row2.addWidget(self.skin_jp_edit)
        form.addLayout(row2)

        detail.addLayout(form)

        self.skin_source_label = QLabel("源立绘：无")
        self.skin_source_label.setWordWrap(True)
        self.skin_source_label.setStyleSheet(
            f"color: {c['fg_muted']}; font-size: 16px; border: none;"
            f" background: transparent;"
        )
        detail.addWidget(self.skin_source_label)

        actions = QVBoxLayout()
        actions.setSpacing(6)
        act_row1 = QHBoxLayout()
        act_row1.setSpacing(6)
        save_btn = QPushButton("保存信息")
        save_btn.setProperty("secondary", "true")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._save_skin_meta)
        src_btn = QPushButton("源立绘")
        src_btn.setProperty("secondary", "true")
        src_btn.setCursor(Qt.PointingHandCursor)
        src_btn.clicked.connect(self._set_skin_source)
        del_btn = QPushButton("删除")
        del_btn.setProperty("danger", "true")
        del_btn.setCursor(Qt.PointingHandCursor)
        del_btn.clicked.connect(self._delete_skin)
        for b in (save_btn, src_btn, del_btn):
            act_row1.addWidget(b)
        actions.addLayout(act_row1)
        add_btn = QPushButton("＋ 添加皮肤")
        add_btn.setProperty("primary", "true")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._add_skin)
        actions.addWidget(add_btn)
        detail.addLayout(actions)

        lay.addWidget(detail_host)
        return w

    def _current_skin_row(self) -> int:
        """当前桌宠正在使用的皮肤索引；非当前秘书舰或异常时返回 -1"""
        try:
            if self._cur_sec != getattr(self.pet, "_current_secretary", None):
                return -1
            return int(getattr(self.pet, "_current_skin_idx", 0) or 0)
        except Exception:
            return -1

    @staticmethod
    def _skin_item_name(name: str) -> str:
        return (name or "").split(" · ")[0].strip()

    def _refresh_skin_page(self) -> None:
        sec = self._cur_sec
        self._skin_data = load_skin_manifest()
        entries = self._skin_data.get(sec, [])
        cur = self._current_skin_row()
        self.skin_grid.blockSignals(True)
        self.skin_grid.clear()
        for i, e in enumerate(entries):
            png = os.path.join(_proj_root(), e["png"]) if not os.path.isabs(e["png"]) else e["png"]
            pm = QPixmap(png)
            icon = QIcon()
            if not pm.isNull():
                icon = QIcon(pm.scaled(88, 88, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            base_name = e.get("name", "皮肤")
            label = f"{base_name}\n使用中" if i == cur else base_name
            item = QListWidgetItem(icon, label)
            item.setData(Qt.UserRole, e)
            item.setData(Qt.UserRole + 1, i)
            item.setSizeHint(QSize(118, 146))
            item.setTextAlignment(Qt.AlignHCenter | Qt.AlignBottom)
            self.skin_grid.addItem(item)
        self.skin_grid.blockSignals(False)
        if entries:
            sel = cur if 0 <= cur < len(entries) else 0
            self.skin_grid.setCurrentRow(sel)
        else:
            self._show_skin_empty()
        self._fade_skin_gallery()

    def _fade_skin_gallery(self) -> None:
        """皮肤缩略图入场淡入"""
        try:
            w = self.skin_grid
            if w is None:
                return
            eff = QGraphicsOpacityEffect(w)
            w.setGraphicsEffect(eff)
            anim = QPropertyAnimation(eff, b"opacity", w)
            anim.setDuration(240)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)

            def _clear(*_args):
                try:
                    w.setGraphicsEffect(None)
                except Exception:
                    pass

            anim.finished.connect(_clear)
            anim.start(QAbstractAnimation.DeleteWhenStopped)
        except Exception:
            pass

    def _show_skin_empty(self) -> None:
        self.skin_preview.clear()
        self.skin_preview.setText("暂无皮肤")
        self.skin_name_edit.clear()
        self.skin_jp_edit.clear()
        self.skin_source_label.setText("源立绘：无")
        if hasattr(self, "skin_use_badge"):
            self.skin_use_badge.hide()
        if hasattr(self, "skin_wear_btn"):
            self.skin_wear_btn.setEnabled(False)
            self.skin_wear_btn.setText("穿上这件")

    def _on_skin_selected(self, row: int) -> None:
        entries = self._skin_data.get(self._cur_sec, [])
        if not (0 <= row < len(entries)):
            self._show_skin_empty()
            if hasattr(self, "skin_wear_btn"):
                self.skin_wear_btn.setEnabled(False)
            return
        e = entries[row]
        if hasattr(self, "skin_wear_btn"):
            is_cur = row == self._current_skin_row()
            self.skin_wear_btn.setText("已在穿着" if is_cur else "穿上这件")
            self.skin_wear_btn.setEnabled(not is_cur)
        self.skin_name_edit.setText(e.get("name", ""))
        self.skin_jp_edit.setText(e.get("jp_skin", ""))
        src = e.get("source", "")
        self.skin_source_label.setText(f"源立绘：{src}" if src else "源立绘：无")
        if hasattr(self, "skin_use_badge"):
            if row == self._current_skin_row():
                self.skin_use_badge.setText(
                    f"正在使用 · {e.get('name', '皮肤')}")
                self.skin_use_badge.show()
            else:
                self.skin_use_badge.hide()
        png = os.path.join(_proj_root(), e["png"]) if not os.path.isabs(e["png"]) else e["png"]
        pm = QPixmap(png)
        if not pm.isNull():
            self.skin_preview.setPixmap(
                pm.scaled(260, 260, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            self.skin_preview.setText("")
        else:
            self.skin_preview.clear()
            self.skin_preview.setText("预览不可用")

    def _on_skin_double(self, item) -> None:
        """双击缩略图：等价于「穿上这件」"""
        self._wear_skin()

    def _wear_skin(self) -> None:
        """穿上当前选中皮肤（仅当前秘书舰在桌宠上时即时生效）"""
        try:
            row = self.skin_grid.currentRow()
            entries = self._skin_data.get(self._cur_sec, [])
            if not (0 <= row < len(entries)):
                return
            if self._cur_sec != getattr(self.pet, "_current_secretary", None):
                self.foot_status.setText(
                    "请先在桌宠/导航中切换到该秘书舰，再穿这件皮肤")
                return
            skins = get_available_skins(self._cur_sec)
            if not (0 <= row < len(skins)):
                return
            self.pet._load_skin(skins[row])
            self.pet._current_skin_idx = row
            name = entries[row].get("name", "") or f"皮肤{row + 1}"
            self.foot_status.setText(
                f"已穿上「{name}」（双击桌宠可继续换装）")
            self._refresh_skin_page()
            self.skin_grid.setCurrentRow(row)
        except Exception as e:
            logger.error(f"穿上皮肤失败: {e}")
            self.foot_status.setText(f"穿上失败：{e}")

    def _save_skin_meta(self) -> None:
        row = self.skin_grid.currentRow()
        entries = self._skin_data.setdefault(self._cur_sec, [])
        if not (0 <= row < len(entries)):
            return
        entries[row]["name"] = self.skin_name_edit.text().strip() or f"皮肤{row + 1}"
        jp = self.skin_jp_edit.text().strip()
        if jp:
            entries[row]["jp_skin"] = jp
        self._skin_data[self._cur_sec] = entries
        save_skin_manifest(self._skin_data)
        self.changed = True
        self.foot_status.setText("皮肤信息已保存")
        self._refresh_skin_page()

    def _set_skin_source(self) -> None:
        row = self.skin_grid.currentRow()
        entries = self._skin_data.setdefault(self._cur_sec, [])
        if not (0 <= row < len(entries)):
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择源立绘(不透明 JPG/PNG)",
            str(os.path.join(_proj_root(), "skins", "source")),
            "图片 (*.png *.jpg *.jpeg)")
        if not path:
            return
        suffix = "" if row == 0 else f"_{row + 1}"
        ext = os.path.splitext(path)[1]
        target = os.path.join(_proj_root(), "skins", "source",
                              f"{self._cur_sec}{suffix}{ext}")
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copyfile(path, target)
        entries[row]["source"] = f"skins/source/{os.path.basename(target)}"
        self._skin_data[self._cur_sec] = entries
        save_skin_manifest(self._skin_data)
        self.changed = True
        self.foot_status.setText("源立绘已更新")
        self._refresh_skin_page()

    def _add_skin(self) -> None:
        sec = self._cur_sec
        png, _ = QFileDialog.getOpenFileName(
            self, "选择皮肤立绘(PNG/JPG/JPEG，PNG透明更好)",
            str(os.path.join(_proj_root(), "skins")),
            "图片 (*.png *.jpg *.jpeg)")
        if not png:
            return
        name, ok = QInputDialog.getText(
            self, "皮肤名称", "新皮肤名称:",
            text=f"皮肤{len(self._skin_data.get(sec, [])) + 1}")
        if not ok or not name.strip():
            return
        src, _ = QFileDialog.getOpenFileName(
            self, "（可选）选择源立绘；取消则无",
            str(os.path.join(_proj_root(), "skins", "source")),
            "图片 (*.png *.jpg *.jpeg)")
        entry = add_secretary_skin(sec, name.strip(), png, src or None, name.strip())
        if entry:
            self.changed = True
            self.foot_status.setText(f"已添加皮肤「{name.strip()}」")
            self._refresh_skin_page()
            self.skin_grid.setCurrentRow(self.skin_grid.count() - 1)

    def _delete_skin(self) -> None:
        row = self.skin_grid.currentRow()
        entries = self._skin_data.get(self._cur_sec, [])
        if not (0 <= row < len(entries)):
            return
        e = entries[row]
        ret = QMessageBox.question(
            self, "删除皮肤",
            f"确定删除皮肤「{e.get('name', '')}」吗？\n"
            "仅删除该皮肤立绘并重排编号；对应语音与台词将保留。",
            QMessageBox.Yes | QMessageBox.No)
        if ret != QMessageBox.Yes:
            return
        delete_secretary_skin(self._cur_sec, row)
        self.changed = True
        self.foot_status.setText("皮肤已删除")
        self._refresh_skin_page()

    # ── 语音 · 台词页 ──

    def _build_voice_page(self) -> QWidget:
        w = QWidget()
        clear_container_bg(w)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 4, 0, 0)
        lay.setSpacing(8)
        c = get_theme_colors()
        section_ss = (
            f"color: {c['fg_muted']}; font-size: 16px; font-weight: 600;"
            f" background: transparent; border: none;"
        )

        # ── 顶部命令条：映射 + 计数 + 操作同行 ──
        map_strip = GlassTile(w, hover_glow=False)
        map_lay = QHBoxLayout(map_strip)
        map_lay.setContentsMargins(16, 12, 16, 12)
        map_lay.setSpacing(14)

        map_block = QVBoxLayout()
        map_block.setSpacing(4)
        map_title = QLabel("台词映射")
        map_title.setStyleSheet(section_ss)
        map_block.addWidget(map_title)
        self.voice_map_combo = QComboBox()
        self.voice_map_combo.setMinimumWidth(210)
        self.voice_map_combo.setStyleSheet(
            f"QComboBox {{ font-size: 17px; padding: 9px 14px;"
            f" background: {c['input_bg']}; border: 1px solid {c['input_border']};"
            f" border-radius: {RADIUS_CARD}px; color: {c['fg']}; }}"
            f" QComboBox:hover {{ border-color: {c['accent']}; }}"
            f" QComboBox::drop-down {{ border: none; width: 30px; }}"
            f" QComboBox QAbstractItemView {{"
            f"  background: {c['bg_secondary']}; color: {c['fg']};"
            f"  selection-background-color: {_theme_rgba('accent', 55)};"
            f"  font-size: 16px; border: 1px solid {c['border']};"
            f"  border-radius: {RADIUS_CARD}px; }}"
        )
        map_block.addWidget(self.voice_map_combo)
        map_lay.addLayout(map_block)

        count_block = QVBoxLayout()
        count_block.setSpacing(4)
        count_title = QLabel("条目")
        count_title.setStyleSheet(section_ss)
        count_block.addWidget(count_title)
        self.voice_count = QLabel("")
        self.voice_count.setStyleSheet(
            f"color: {c['fg']}; font-size: 17px; font-weight: 600; border: none;"
            f" background: {c['input_bg']}; border: 1px solid {c['input_border']};"
            f" border-radius: {RADIUS_PILL}px; padding: 9px 16px;"
        )
        count_block.addWidget(self.voice_count)
        map_lay.addLayout(count_block)

        map_lay.addStretch(1)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)
        reload_btn = QPushButton("重新载入")
        reload_btn.setProperty("secondary", "true")
        reload_btn.setCursor(Qt.PointingHandCursor)
        reload_btn.clicked.connect(self._reload_voice)
        add_btn = QPushButton("＋ 新增")
        add_btn.setProperty("secondary", "true")
        add_btn.setCursor(Qt.PointingHandCursor)
        add_btn.clicked.connect(self._voice_add_row)
        save_btn = QPushButton("保存台词")
        save_btn.setProperty("primary", "true")
        save_btn.setCursor(Qt.PointingHandCursor)
        save_btn.clicked.connect(self._voice_save)
        for b in (reload_btn, add_btn, save_btn):
            btn_row.addWidget(b)
        map_lay.addLayout(btn_row)

        lay.addWidget(map_strip)

        hint = QLabel("字段可直接编辑 · 点 ▶ 试听 · 保存后立即生效")
        hint.setStyleSheet(
            f"color: {c['fg_muted']}; font-size: 16px; border: none;"
            f" background: transparent;"
        )
        lay.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setStyleSheet(
            "QScrollArea { background: transparent; border: none; }"
            "QScrollBar { background: transparent; width: 10px; }"
            f"QScrollBar::handle:vertical {{ background: {c['scrollbar_handle']};"
            f" border-radius: {RADIUS_PILL // 2}px; min-height: 32px; }}"
            "QScrollBar::add-line, QScrollBar::sub-line { height: 0; }"
        )
        self.voice_list_host = QWidget()
        clear_container_bg(self.voice_list_host)
        self.voice_list_lay = QVBoxLayout(self.voice_list_host)
        self.voice_list_lay.setContentsMargins(0, 0, 4, 0)
        self.voice_list_lay.setSpacing(8)
        scroll.setWidget(self.voice_list_host)
        lay.addWidget(scroll, 1)

        self.voice_map_combo.currentIndexChanged.connect(self._on_map_changed)
        return w

    def _on_map_changed(self, *_):
        if self._voice_guard:
            return
        # 切换映射前：若有未保存修改，先写回旧文件
        if self._voice_dirty and self._cur_voice_path:
            if not self._voice_save():
                # 保存失败则回退选择
                self._voice_guard = True
                try:
                    idx = self.voice_map_combo.findData(
                        os.path.relpath(self._cur_voice_path, _proj_root())
                        .replace(os.sep, "/"))
                    if idx >= 0:
                        self.voice_map_combo.setCurrentIndex(idx)
                finally:
                    self._voice_guard = False
                return
        self._refresh_voice_page()

    def _voice_maps_for(self, sec: str) -> list:
        maps = []
        vm = f"voices/{sec}/voice_map.json"
        if os.path.isfile(os.path.join(_proj_root(), vm)):
            maps.append(vm)
        maps.extend(jp_voice.JP_MAP_FILES.get(sec, []))
        return maps

    def _voice_schema(self) -> str:
        rel = self.voice_map_combo.currentData() or ""
        return "cn" if os.path.basename(rel) == "voice_map.json" else "jp"

    def _reload_voice(self) -> None:
        if self._voice_dirty and not self._confirm_discard_voice():
            return
        self._refresh_voice_page()

    def _refresh_voice_page(self) -> None:
        if not hasattr(self, "voice_map_combo"):
            return
        sec = self._cur_sec
        maps = self._voice_maps_for(sec)
        self._voice_guard = True
        try:
            self.voice_map_combo.blockSignals(True)
            self.voice_map_combo.clear()
            for rel in maps:
                self.voice_map_combo.addItem(
                    "中文台词池" if os.path.basename(rel) == "voice_map.json"
                    else os.path.basename(rel), rel)
            self.voice_map_combo.blockSignals(False)
        finally:
            self._voice_guard = False

        self._clear_layout(self.voice_list_lay)
        self._voice_cards.clear()
        self._voice_dirty = False

        if not maps:
            self._cur_voice_path = None
            self._cur_voice_dir = None
            self.voice_count.setText("0 条")
            empty_host = GlassTile(self.voice_list_host, hover_glow=False)
            empty_lay = QVBoxLayout(empty_host)
            empty_lay.setContentsMargins(20, 24, 20, 24)
            empty = QLabel("该舰暂无语音映射文件")
            empty.setStyleSheet(
                f"color: {get_theme_colors()['fg']}; font-size: {FONT_BODY}px;"
                f" border: none; background: transparent;"
            )
            empty.setAlignment(Qt.AlignCenter)
            empty_lay.addWidget(empty)
            self.voice_list_lay.addWidget(empty_host)
            self.voice_list_lay.addStretch(1)
            return

        rel = self.voice_map_combo.currentData()
        path = os.path.join(_proj_root(), rel)
        self._cur_voice_path = path
        self._cur_voice_dir = os.path.dirname(path)
        data = []
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, list):
                    data = loaded
            except Exception as e:
                self.voice_count.setText("读取失败")
                self.foot_status.setText(f"读取失败: {e}")
                return

        schema = self._voice_schema()
        for it in data:
            card = _VoiceEntryCard(schema, it, self._cur_voice_dir,
                                   self._play_preview, self.voice_list_host)
            card.dirty.connect(self._mark_voice_dirty)
            self._voice_cards.append(card)
            self.voice_list_lay.addWidget(card)
        self.voice_list_lay.addStretch(1)
        kind = "中文台词池" if schema == "cn" else "日文场景映射"
        self.voice_count.setText(f"{len(data)} 条 · {kind}")
        self.foot_status.setText(os.path.relpath(path, _proj_root()))
        self._stagger_voice_cards()

    def _stagger_voice_cards(self) -> None:
        """语音磁贴错峰淡入（列表较长时只动前若干张，避免卡顿）"""
        cards = self._voice_cards[:24]
        for i, card in enumerate(cards):
            try:
                eff = QGraphicsOpacityEffect(card)
                card.setGraphicsEffect(eff)
                anim = QPropertyAnimation(eff, b"opacity", card)
                anim.setDuration(260)
                anim.setStartValue(0.0)
                anim.setEndValue(1.0)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                anim.setDelay(i * 35)

                def _clear(*_args, w=card):
                    try:
                        w.setGraphicsEffect(None)
                    except Exception:
                        pass

                anim.finished.connect(_clear)
                anim.start(QAbstractAnimation.DeleteWhenStopped)
            except Exception:
                break
        # 超出阈值的卡片直接显示
        for card in self._voice_cards[len(cards):]:
            card.setWindowOpacity(1.0)

    def _clear_layout(self, lay) -> None:
        while lay.count():
            item = lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def _mark_voice_dirty(self) -> None:
        self._voice_dirty = True
        self.foot_status.setText("语音有未保存修改 — 关闭前请保存")

    def _on_voice_card_event(self, kind: str, card: "_VoiceEntryCard") -> None:
        if kind == "delete":
            if card in self._voice_cards:
                self._voice_cards.remove(card)
            card.deleteLater()
            self._mark_voice_dirty()

    def _voice_add_row(self) -> None:
        if not self._cur_voice_dir:
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "选择语音文件(mp3)", self._cur_voice_dir, "音频 (*.mp3)")
        if not path:
            return
        schema = self._voice_schema()
        seed = {"skin": "", "text": ""}
        if schema == "cn":
            seed["mp3"] = os.path.basename(path)
            seed["jp"] = ""
        else:
            seed["scene"] = ""
            seed["file"] = os.path.basename(path)
            seed["matched"] = True
            seed["missing"] = False
        card = _VoiceEntryCard(schema, seed, self._cur_voice_dir,
                               self._play_preview, self.voice_list_host)
        card.dirty.connect(self._mark_voice_dirty)
        self._voice_cards.insert(0, card)
        self.voice_list_lay.insertWidget(0, card)
        self._mark_voice_dirty()
        card.skin_edit.setFocus()

    def _collect_voice_rows(self) -> list:
        return [c.to_row() for c in self._voice_cards]

    def _voice_save(self) -> bool:
        if not self._cur_voice_path:
            return False
        rows = self._collect_voice_rows()
        key = "mp3" if self._voice_schema() == "cn" else "file"
        bad = [r for r in rows
               if not r.get(key) or not os.path.isfile(
                   os.path.join(self._cur_voice_dir, r[key]))]
        if bad:
            QMessageBox.warning(
                self, "无法保存",
                "存在无效的音频文件（空 或 文件不存在）。请修正后再保存。")
            return False
        try:
            with open(self._cur_voice_path, "w", encoding="utf-8") as f:
                json.dump(rows, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "保存失败", str(e))
            return False
        jp_voice._CACHE.clear()
        self.changed = True
        self._voice_dirty = False
        kind = "中文台词池" if self._voice_schema() == "cn" else "日文场景映射"
        self.voice_count.setText(f"{len(rows)} 条 · {kind}")
        self.foot_status.setText(f"已保存 {len(rows)} 条")
        return True

    def _confirm_discard_voice(self) -> bool:
        """有未保存语音修改时：返回 True 表示可继续（已保存或用户选择丢弃）"""
        if not self._voice_dirty:
            return True
        ret = QMessageBox.question(
            self, "语音未保存",
            "语音 · 台词有未保存的修改。\n保存后继续？",
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
        if ret == QMessageBox.Save:
            return self._voice_save()
        if ret == QMessageBox.Discard:
            self._voice_dirty = False
            return True
        return False

    def _on_apply(self) -> None:
        if self._voice_dirty and not self._voice_save():
            return
        self.accept()

    def _on_close(self) -> None:
        if not self._confirm_discard_voice():
            return
        self.reject()

    def reject(self) -> None:
        # 兜底：Esc / ✕ 关闭
        if self._voice_dirty and not self._confirm_discard_voice():
            return
        super().reject()

    def _play_preview(self, path: str) -> None:
        if not path or not os.path.isfile(path):
            self.foot_status.setText(f"音频不存在: {os.path.basename(path or '')}")
            return
        try:
            from PyQt5.QtMultimedia import QMediaPlayer as _MP, QMediaContent as _MC
            from PyQt5.QtCore import QUrl as _QUrl
            if self._preview_player is None:
                self._preview_player = _MP(self)
            self._preview_player.setMedia(_MC(_QUrl.fromLocalFile(path)))
            self._preview_player.play()
            self.foot_status.setText(f"▶ 试听: {os.path.basename(path)}")
        except Exception as e:
            logger.error(f"试听失败: {e}")


def main() -> int:
    # 全局异常钩子，防止静默崩溃
    def _excepthook(exc_type, exc_value, tb):
        import traceback
        traceback.print_exception(exc_type, exc_value, tb)
    sys.excepthook = _excepthook

    parser = argparse.ArgumentParser(description="企业温泉桌宠")
    parser.add_argument(
        "--image",
        default=DEFAULT_IMAGE_PATH,
        help="透明 PNG 角色图路径",
    )
    parser.add_argument(
        "--api-base",
        default=DEFAULT_API_BASE,
        help="AstrBot API 根地址，例如 http://127.0.0.1:6185",
    )
    parser.add_argument(
        "--api-key",
        default=DEFAULT_API_KEY,
        help="AstrBot API Key",
    )
    args = parser.parse_args()

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)  # 关窗不退出，托盘常驻
    # 应用级样式表：让 QMenu / QToolTip 等顶层控件也获得 iOS 毛玻璃观感
    app.setStyleSheet(theme_stylesheet())
    pet = DesktopPet(image_path=args.image, api_base=args.api_base, api_key=args.api_key)
    pet.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
