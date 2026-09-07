# -*- coding: utf-8 -*-
"""研学课程包：确定性逻辑层（价格模型、学段归一、LLM 不可用时的模板兜底）。

设计原则：价格、天数、师生比等不允许 LLM 自由发挥的内容全部在本模块用代码计算，
LLM 只负责把路线骨架润色成课程文本（见 tools.py 的 generate_course_pack）。
"""
import json
import math
import os
from typing import Any, Dict, List, Optional

from . import config

PRICING_PATH = os.path.join(config.PROJECT_DIR, "data", "study", "pricing.json")

# 学段别名 → pricing.json 中的标准学段
STAGE_ALIASES = {
    "小学": "小学",
    "初中": "初中",
    "中学": "初中",
    "高中": "高中",
    "党校": "党校/成人",
    "成人": "党校/成人",
    "干部": "党校/成人",
    "党员": "党校/成人",
}
DEFAULT_STAGE = "初中"


def load_pricing_model() -> Dict[str, Any]:
    """读取研学价格模型；文件缺失时返回内置最小兜底，保证工具不崩。"""
    fallback = {
        "currency": "元",
        "stages": {DEFAULT_STAGE: {"per_student_day": 118, "guide_student_ratio": 20}},
        "included": [],
        "excluded": [],
    }
    try:
        with open(PRICING_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return fallback


def detect_stage(text: Optional[str]) -> Optional[str]:
    """从自然语言中探测学段，未命中返回 None（区别于 normalize_stage 的默认值兜底）。"""
    if not text:
        return None
    for alias, canonical in STAGE_ALIASES.items():
        if alias in text:
            return canonical
    return None


def normalize_stage(stage: Optional[str]) -> str:
    """把'小学高年级'等口语化学段归一到价格模型里的标准键。"""
    return detect_stage(stage) or DEFAULT_STAGE


def estimate_price(stage: str, days: int, group_size: int,
                   pricing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """按学段/天数/班额确定性地估算费用与所需导师数。

    返回字段全部由代码计算，不经过 LLM，保证数字可复算、可追溯。
    """
    pricing = pricing or load_pricing_model()
    canonical_stage = normalize_stage(stage)
    stage_cfg = pricing.get("stages", {}).get(canonical_stage, {})
    per_day = int(stage_cfg.get("per_student_day", 0))
    ratio = int(stage_cfg.get("guide_student_ratio", 20)) or 20

    per_student_fee = per_day * days
    return {
        "stage": canonical_stage,
        "days": days,
        "group_size": group_size,
        "per_student_fee": per_student_fee,
        "total_fee": per_student_fee * group_size,
        "required_guides": math.ceil(group_size / ratio),
        "guide_student_ratio": ratio,
        "currency": pricing.get("currency", "元"),
        "included": pricing.get("included", []),
        "excluded": pricing.get("excluded", []),
        "note": "演示用价格模型，非真实商业报价",
    }


# 现场教学点天数不足时，用来补齐课程总天数的非移动教学环节（循环取用）
EXTRA_DAY_TEMPLATES = [
    ("专题教学与研学手册指导", "驻地教室", ["复盘前序教学点的史实脉络"],
     "分小组梳理时间线，完成研学手册探究题"),
    ("情景体验与结营汇报", "驻地/现场", ["红色情景剧与小组课题汇报"],
     "以小组为单位进行情景剧展示或课题汇报，导师点评结营"),
]


def build_fallback_curriculum(
    route: Dict[str, Any], stage: str, total_days: Optional[int] = None
) -> Dict[str, Any]:
    """LLM 不可用时的模板化课程表：把路线的扁平 stops 按天分组拼装，保证工具始终有输出。

    total_days 为用户要求的课程总天数：当它多于现场教学点覆盖的天数时，
    用专题教学/结营汇报等不换场地的环节补齐，避免"要 3 天只给 2 天"。
    """
    canonical_stage = normalize_stage(stage)
    stops_by_day: Dict[int, List[Dict[str, Any]]] = {}
    for stop in route.get("stops", []):
        stops_by_day.setdefault(int(stop.get("day", 1)), []).append(stop)

    daily_plans: List[Dict[str, Any]] = []
    for day in sorted(stops_by_day):
        activities = []
        for idx, stop in enumerate(stops_by_day[day]):
            slot = stop.get("visit_time") or ("上午" if idx == 0 else "下午")
            site = stop.get("name", "")
            event = stop.get("event", "")
            knowledge = [event]
            knowledge.extend(
                (ev.get("label") or ev.get("desc") or "")
                for ev in (stop.get("timeline_events") or [])[:2]
            )
            attractions = [a for a in (stop.get("attractions") or []) if a]
            knowledge.extend(attractions[:2])
            knowledge = [k for k in knowledge if k]
            # 任务必须绑定该教学点的具体史实与现场资源，避免不同地点任务雷同
            anchor = attractions[0] if attractions else event
            task = (
                f"在{site}实地走访「{anchor}」，围绕“{event or site}”完成研学手册："
                f"记录3个现场细节，提出1个探究问题，并与同组同学交流结论"
            )
            activities.append({
                "slot": slot,
                "site": site,
                "knowledge": knowledge,
                "task": task,
            })
        daily_plans.append({
            "day": day,
            "theme": f"第{day}天：" + "、".join(a["site"] for a in activities),
            "activities": activities,
        })

    # 用户要求的总天数多于现场教学点天数时，补齐非移动教学日
    target_days = int(total_days) if total_days else len(daily_plans)
    extra_idx = 0
    while len(daily_plans) < target_days:
        theme, site, knowledge, task = EXTRA_DAY_TEMPLATES[extra_idx % len(EXTRA_DAY_TEMPLATES)]
        extra_idx += 1
        daily_plans.append({
            "day": len(daily_plans) + 1,
            "theme": theme,
            "activities": [{
                "slot": "全天", "site": site, "knowledge": knowledge, "task": task,
            }],
        })
    return {
        "stage": canonical_stage,
        "course_goals": ["走完红色路线，理解关键历史事件", "完成研学手册探究任务"],
        "daily_plans": daily_plans,
        "handbook_tasks": ["每个教学点一段现场记录", "结营前完成一篇研学心得"],
        "closing": "结营分享会：小组汇报研学成果",
        "source": "template_fallback",
    }
