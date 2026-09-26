# -*- coding: utf-8 -*-
"""桌宠「精进」数据层：日程 / 主动陪伴 两套自包含能力。

- ScheduleManager  日程：一次性/每日提醒，克制提醒（每天一次/迟到 2 小时内补提醒）
- ProactiveEngine  主动陪伴：空闲超时后主动开口，话题不重复、有冷却与每日上限

设计原则：仅依赖标准库，任何读写失败都静默降级，绝不抛异常影响主程序。
"""
import datetime
import json
import os
import random
import re
import threading
import uuid

def _resolve_data_dir() -> str:
    """优先 %APPDATA%\\DesktopPet（首次使用时创建）；不可用时回退到脚本目录。"""
    appdata = os.environ.get("APPDATA", "").strip()
    if appdata:
        d = os.path.join(appdata, "DesktopPet")
        try:
            os.makedirs(d, exist_ok=True)
            return d
        except Exception:
            pass
    return os.path.dirname(os.path.abspath(__file__))


_DATA_DIR = _resolve_data_dir()


def ensure_data_dir() -> str:
    try:
        os.makedirs(_DATA_DIR, exist_ok=True)
    except Exception:
        pass
    return _DATA_DIR


def data_path(name: str) -> str:
    return os.path.join(ensure_data_dir(), name)


# ── 自然语言日程解析 ──
# 支持：提醒我 明天 早上9点 开会 / 每天早上8点打卡 / 今晚10点睡觉 / 后天下午3点交作业
_CN_NUM = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
           "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
           "十": 10, "十一": 11, "十二": 12, "十三": 13, "十四": 14,
           "十五": 15, "十六": 16, "十七": 17, "十八": 18, "十九": 19,
           "二十": 20, "二十一": 21, "二十二": 22, "二十三": 23}

_TIME_TOKEN = re.compile(
    r"(?P<h>[0-9一二两三四五六七八九十]{1,3})\s*[点时]\s*"
    r"(?:(?P<m>[0-9一二两三四五六七八九十]{1,2})\s*分?|(?P<hal>[半]))?"
    r"|(?P<hh>[01]?[0-9]|2[0-3]):(?P<mm>[0-5][0-9])"
)
_DAILY_RE = re.compile(r"(每天|每日|每晚|每早|每天早上|每天晚上)")
_DATE_RE = re.compile(r"(大后天|后天|明天|明早|明日|今天|今晚|今日)")
_PM_RE = re.compile(r"(下午|晚上|今晚|夜里|傍晚|夜晚)")
_AM_RE = re.compile(r"(凌晨|清晨|深夜)")
_CLEAN_RE = re.compile(
    r"(提醒我|提醒|帮我|请|麻烦|设个提醒|设置提醒|添加提醒|加个提醒|帮我安排|安排|"
    r"每天|每日|每晚|每早|每天早上|每天晚上|大后天|后天|明天|明早|明日|今天|今晚|今日|"
    r"早上|上午|中午|下午|晚上|凌晨|夜里|傍晚|夜晚)"
)


def parse_schedule_nl(text: str):
    """从自然语言解析日程。成功返回 (when, content)；无法解析返回 None。

    示例：
      '提醒我 明天 早上9点 交报告'  -> ('2026-08-09 09:00', '交报告')
      '每天早上8点打卡'            -> ('08:00', '打卡')
      '今晚10点睡觉'               -> ('2026-08-08 22:00', '睡觉')
      '后天下午3点交作业'          -> ('2026-08-10 15:00', '交作业')
    """
    t = text.strip()
    if not t:
        return None
    daily = bool(_DAILY_RE.search(t))
    day_delta = None
    if not daily:
        m = _DATE_RE.search(t)
        if m:
            kw = m.group(1)
            if kw == "大后天":
                day_delta = 3
            elif kw in ("后天",):
                day_delta = 2
            elif kw in ("明天", "明早", "明日"):
                day_delta = 1
            else:
                day_delta = 0
    m = _TIME_TOKEN.search(t)
    if not m:
        return None
    if m.group("hh") is not None:
        hour, minute = int(m.group("hh")), int(m.group("mm"))
    else:
        try:
            hour = _CN_NUM.get(m.group("h"))
            if hour is None:
                hour = int(m.group("h"))
        except Exception:
            return None
        if m.group("hal"):
            minute = 30
        elif m.group("m"):
            minute = _CN_NUM.get(m.group("m"))
            if minute is None:
                try:
                    minute = int(m.group("m"))
                except Exception:
                    minute = 0
        else:
            minute = 0
        head = t[:m.start()]
        if _PM_RE.search(head):
            if hour < 12:
                hour += 12
        elif _AM_RE.search(head):
            if hour == 12:
                hour = 0
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    if daily:
        when = "%02d:%02d" % (hour, minute)
    else:
        delta = 0 if day_delta is None else day_delta
        d = datetime.date.today() + datetime.timedelta(days=delta)
        when = "%s %02d:%02d" % (d.strftime("%Y-%m-%d"), hour, minute)
    content = _TIME_TOKEN.sub("", t)
    content = _CLEAN_RE.sub(" ", content)
    content = re.sub(r"[，,。.！!？?；;：:\s]+", " ", content).strip()
    if not content:
        return None
    return when, content


class _JsonStore:
    """带锁的 JSON 持久化基类，读写异常均静默"""

    def __init__(self, filename: str, default: object):
        self._path = data_path(filename)
        # RLock 可重入：edit/mark_fired 会在持锁时调用 _save 再次加锁，Lock 会造成死锁
        self._lock = threading.RLock()
        self._data = self._load(default)

    def _load(self, default):
        try:
            if os.path.isfile(self._path):
                with open(self._path, encoding="utf-8") as f:
                    d = json.load(f)
                    if isinstance(d, type(default)):
                        return d
        except Exception:
            pass
        return default

    def _save(self):
        try:
            with self._lock:
                with open(self._path, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass


class ScheduleManager(_JsonStore):
    """日程：reminders = [{id, text, when, fired, last_fired_date, created_at}]
    when 支持两种：'HH:MM' 每日；'YYYY-MM-DD HH:MM' 一次性。"""

    def __init__(self):
        super().__init__("schedule.json", {"reminders": []})

    def add(self, text: str, when: str) -> dict:
        when = when.strip()
        text = text.strip()
        if not text or not when:
            return {}
        item = {
            "id": uuid.uuid4().hex[:12],
            "text": text,
            "when": when,
            "fired": False,          # 一次性是否已触发
            "last_fired_date": "",   # 每日：当天已触发的日期
            "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        with self._lock:
            self._data["reminders"].append(item)
        self._save()
        return item

    def delete(self, rid: str) -> bool:
        with self._lock:
            before = len(self._data["reminders"])
            self._data["reminders"] = [r for r in self._data["reminders"] if r.get("id") != rid]
            ok = len(self._data["reminders"]) < before
        if ok:
            self._save()
        return ok

    def list(self) -> list:
        with self._lock:
            return list(self._data.get("reminders", []))

    @staticmethod
    def _minutes(hhmm: str):
        try:
            h, m = hhmm.split(":")
            return int(h) * 60 + int(m)
        except Exception:
            return -1

    def due(self, now: datetime.datetime = None) -> list:
        """返回当前应提醒的项（克制：一次性每天只一次；每日迟到 2 小时内补提醒）"""
        now = now or datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")
        cur_min = now.hour * 60 + now.minute
        due_items = []
        for r in self.list():
            w = r.get("when", "")
            try:
                if " " in w and len(w) >= 16:      # 一次性 YYYY-MM-DD HH:MM
                    d, t = w.split(" ", 1)
                    if d == today and not r.get("fired", False) and self._minutes(t) <= cur_min:
                        due_items.append(r)
                else:                               # 每日 HH:MM
                    tm = self._minutes(w)
                    if 0 <= cur_min - tm <= 120 and r.get("last_fired_date", "") != today:
                        due_items.append(r)
            except Exception:
                continue
        return due_items

    def mark_fired(self, rid: str, now: datetime.datetime = None) -> None:
        now = now or datetime.datetime.now()
        today = now.strftime("%Y-%m-%d")
        with self._lock:
            for r in self._data["reminders"]:
                if r.get("id") == rid:
                    if " " in r.get("when", "") and len(r.get("when", "")) >= 16:
                        r["fired"] = True
                    else:
                        r["last_fired_date"] = today
                    self._save()
                    return

    def set_done(self, rid: str, done: bool) -> bool:
        """手动标记完成/取消完成：一次性改 fired；每日改 last_fired_date（今天）"""
        today = datetime.date.today().strftime("%Y-%m-%d")
        with self._lock:
            for r in self._data["reminders"]:
                if r.get("id") == rid:
                    if " " in r.get("when", "") and len(r.get("when", "")) >= 16:
                        r["fired"] = bool(done)
                    else:
                        r["last_fired_date"] = today if done else ""
                    self._save()
                    return True
            return False

    def rename(self, rid: str, text: str) -> bool:
        text = (text or "").strip()
        if not text:
            return False
        with self._lock:
            for r in self._data["reminders"]:
                if r.get("id") == rid:
                    r["text"] = text
                    self._save()
                    return True
            return False


class ProactiveEngine:
    """主动陪伴引擎：空闲超时 + 冷却 + 每日上限，话题去重。"""

    DEFAULT_IDLE_MIN = 30          # 空闲多久后考虑主动开口
    DEFAULT_COOLDOWN_MIN = 20      # 两次主动之间的最短间隔
    DEFAULT_MAX_PER_DAY = 6        # 每日主动开口上限

    # 通用话题池（按时段加权）
    _TOPICS = [
        ("关怀", ["指挥官，忙了这么久，记得起来活动一下肩膀哦。",
                  "记得喝口水休息一下，我会在这里陪着你的。",
                  "看你的样子有点累了，要不要稍微放空一会儿？"]),
        ("询问", ["指挥官，今天有什么特别想做的事吗？",
                  "最近有没有遇到什么有趣的事，说给我听听？",
                  "今天的进度如何？遇到麻烦的话我可以帮你想想办法。"]),
        ("提醒", ["别一直盯着屏幕啦，偶尔看看远处放松一下眼睛吧。",
                  "长时间坐着对腰不好，起来走两步再继续吧。"]),
        ("分享", ["听说适度的小憩能让思路更清晰，要不要试试？",
                  "我这边一直在关注你的状态哦，状态不错呢。"]),
    ]

    def __init__(self, secretary: str = "enterprise", secretary_lines: list = None):
        self.secretary = secretary
        self._lines = secretary_lines or []
        self._last_interaction = datetime.datetime.now()
        self._last_proactive = datetime.datetime.now() - datetime.timedelta(hours=1)
        self._recent = []            # 最近说过的句子（去重）
        self._fired_today = 0
        self._today = datetime.date.today()
        self.idle_min = self.DEFAULT_IDLE_MIN
        self.cooldown_min = self.DEFAULT_COOLDOWN_MIN
        self.max_per_day = self.DEFAULT_MAX_PER_DAY

    def on_interaction(self) -> None:
        self._last_interaction = datetime.datetime.now()

    def _roll_day(self) -> None:
        today = datetime.date.today()
        if today != self._today:
            self._today = today
            self._fired_today = 0

    def should_fire(self, now: datetime.datetime = None, visible: bool = True,
                    talking: bool = False) -> bool:
        """是否该主动开口"""
        if not visible or talking:
            return False
        now = now or datetime.datetime.now()
        self._roll_day()
        if self._fired_today >= self.max_per_day:
            return False
        idle_min = (now - self._last_interaction).total_seconds() / 60.0
        cool_min = (now - self._last_proactive).total_seconds() / 60.0
        if idle_min < self.idle_min or cool_min < self.cooldown_min:
            return False
        # 已满足条件后仍有随机性，避免机械感
        return random.random() < 0.6

    def pick(self) -> str:
        """选一句主动台词（优先角色语音，其次通用话题；避开最近说过的）"""
        self._roll_day()
        candidates = []
        if self._lines:
            candidates += self._lines
        # 通用话题：优先当前时段相关
        for _, pool in self._TOPICS:
            candidates += pool
        random.shuffle(candidates)
        # 优先选最近 12 句里没出现过的
        for c in candidates:
            if c not in self._recent:
                break
        else:
            c = candidates[0]
        self._recent.append(c)
        if len(self._recent) > 12:
            self._recent = self._recent[-12:]
        self._last_proactive = datetime.datetime.now()
        self._fired_today += 1
        return c
