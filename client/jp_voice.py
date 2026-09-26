# -*- coding: utf-8 -*-
"""台词↔日文语音：场景化语音映射加载与查询模块。

数据来源：碧蓝航线官方 WIKI 原始 dump，文本未经机翻、未经编造。
每个舰娘可在项目 voices/{secretary}/ 下放置一份或多份带 scene 字段的
voice_map.json（与 mp3 同目录）。本模块负责：

  - load_jp_map(secretary)  -> {skin: {scene: entry}}
  - get_jp_voice(secretary, skin, scene) -> entry | None
  - resolve_event(secretary, skin, event) -> entry | None

entry = {"file": 文件名, "text": 台词, "path": 绝对路径}

容错规则（静默跳过，不抛错、不编造）：
  - matched == False          -> 无权威台词，跳过
  - missing == True           -> 音频缺失，跳过
  - scene / file 为空         -> 跳过
  - 对应 mp3 文件不存在        -> 跳过
"""
import os
import sys
import json


def _base_dir() -> str:
    """项目根目录：开发态为脚本所在目录，打包态为 _MEIPASS。"""
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


# 各舰娘的 jp 语音映射文件（相对项目根，与 mp3 同目录）；支持多份
JP_MAP_FILES = {
    "anshan": ["voices/anshan/voice_map_jp.json"],
    "belfast": ["voices/belfast/voice_map_belfast_mod.json"],
}

# 事件 -> 候选 scene 名（按顺序尝试，命中第一个可用项）
EVENT_SCENE_MAP = {
    "login": ["登录", "登录台词"],
    "main": ["主界面1", "主界面2", "主界面3", "主界面"],
    "touch": ["触摸", "主界面"],
    "special_touch": ["特殊触摸"],
    "return": ["回港"],
    "oath": ["誓约"],
    "strengthen": ["强化成功", "强化"],
    "affinity": [
        "好感度-爱",
        "好感度-喜欢",
        "好感度-萌",
        "好感度-陌生",
        "好感度-失望",
    ],
    "head_pat": ["摸头台词", "摸头"],
}

_CACHE: dict = {}


def _load_file(rel: str):
    path = os.path.join(_base_dir(), rel)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def load_jp_map(secretary: str) -> dict:
    """返回 {skin: {scene: entry}}，entry 已做完整容错过滤。"""
    if secretary in _CACHE:
        return _CACHE[secretary]
    result: dict = {}
    for rel in JP_MAP_FILES.get(secretary, []):
        data = _load_file(rel)
        if not data:
            continue
        json_dir = os.path.dirname(os.path.join(_base_dir(), rel))
        for item in data:
            if not isinstance(item, dict):
                continue
            if item.get("matched", True) is False:
                continue
            if item.get("missing", False) is True:
                continue
            scene = (item.get("scene") or "").strip()
            file = (item.get("file") or "").strip()
            if not scene or not file:
                continue
            full = os.path.join(json_dir, file)
            if not os.path.isfile(full):
                continue
            skin = item.get("skin", "")
            result.setdefault(skin, {})[scene] = {
                "file": file,
                "text": item.get("text", "") or "",
                "path": full,
            }
    _CACHE[secretary] = result
    return result


def get_jp_voice(secretary: str, skin: str, scene: str):
    return load_jp_map(secretary).get(skin, {}).get(scene)


def resolve_event(secretary: str, skin: str, event: str):
    """按 EVENT_SCENE_MAP 顺序返回第一个命中条目，否则 None。"""
    for scene in EVENT_SCENE_MAP.get(event, []):
        entry = get_jp_voice(secretary, skin, scene)
        if entry:
            return entry
    return None
