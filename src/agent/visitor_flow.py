# -*- coding: utf-8 -*-
"""景区客流热力（治理层）：确定性仿真数据层。

- 数据来自 data/governance/visitor_flow.json，明确标注为仿真演示数据；
- 当前客流 = 村寨日基础客流 × 时段权重，"实时"由系统当前小时驱动；
- 拥堵等级、预警阈值等判断全部在本模块用代码计算，不经过 LLM；
- 生产环境只需把 load_flow_config 的数据源换成票务闸机/LBS 接口，上层 API 与前端不变。
"""
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from . import config, holidays
from .knowledge import VILLAGE_COORDS

FLOW_PATH = os.path.join(config.PROJECT_DIR, "data", "governance", "visitor_flow.json")

# 等级 code → 中文标签与展示颜色（与前端图例保持一致）
LEVEL_META = {
    "comfortable": {"label": "宽松", "color": "#22c55e"},
    "moderate": {"label": "适中", "color": "#eab308"},
    "crowded": {"label": "拥挤", "color": "#f97316"},
    "alert": {"label": "预警", "color": "#ef4444"},
}

# 文件缺失时的内置兜底配置（权重曲线在 16-17 点达到峰值）
_FALLBACK_CONFIG: Dict[str, Any] = {
    "hourly_weight": [
        0.02, 0.01, 0.0, 0.0, 0.0, 0.01, 0.05, 0.15, 0.35, 0.55, 0.75, 0.85,
        0.7, 0.6, 0.65, 0.8, 0.95, 1.0, 0.85, 0.6, 0.4, 0.25, 0.12, 0.05,
    ],
    "slot_names": {"morning": [8, 9, 10, 11], "afternoon": [12, 13, 14, 15, 16],
                   "evening": [17, 18, 19]},
    "level_thresholds": {"comfortable": 0.4, "moderate": 0.7, "crowded": 0.9},
    "villages": {},
    "default_village": {"base_daily": 450, "capacity": 1000},
}


def load_flow_config() -> Dict[str, Any]:
    """读取客流配置；文件损坏/缺失时返回内置兜底，保证接口不报错。"""
    try:
        with open(FLOW_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        if isinstance(cfg.get("hourly_weight"), list) and len(cfg["hourly_weight"]) == 24:
            return cfg
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return _FALLBACK_CONFIG


def current_hour() -> int:
    """系统当前小时（0-23），单独成函数便于测试时 monkeypatch。"""
    return datetime.now().hour


def classify_level(load_ratio: float, thresholds: Dict[str, float]) -> str:
    """按瞬时承载率（当前人数/最大承载量）划分拥堵等级。"""
    if load_ratio >= thresholds.get("crowded", 0.9):
        return "alert"
    if load_ratio >= thresholds.get("moderate", 0.7):
        return "crowded"
    if load_ratio >= thresholds.get("comfortable", 0.4):
        return "moderate"
    return "comfortable"


def _village_cfg(name: str, cfg: Dict[str, Any]) -> Dict[str, Any]:
    return cfg.get("villages", {}).get(name) or cfg.get("default_village", {})


def hourly_flow(name: str, hour: int, cfg: Optional[Dict[str, Any]] = None) -> int:
    """单个村寨在指定小时的仿真客流人数。"""
    cfg = cfg or load_flow_config()
    weights = cfg["hourly_weight"]
    base = int(_village_cfg(name, cfg).get("base_daily", 450))
    return round(base * weights[hour % 24])


def slot_hours(slot: str, cfg: Dict[str, Any]) -> List[int]:
    """把 morning/afternoon/evening 翻译成小时列表；无法识别时返回当前小时。"""
    hours = cfg.get("slot_names", {}).get(slot)
    return hours if hours else [current_hour()]


def heatmap_snapshot(
    hour: Optional[int] = None,
    slot: Optional[str] = None,
    cfg: Optional[Dict[str, Any]] = None,
    weather_map: Optional[Dict[str, Dict[str, Any]]] = None,
    day_type_value: Optional[str] = None,
    weather_status: str = "ok",
) -> Dict[str, Any]:
    """返回所有村寨在指定小时（或时段均值）的热力快照。

    weather_map: {地点名: 天气dict}，来自 weather_service；为 None 时不做天气修正。
    day_type_value: holiday/weekend/workday/workday_makeup，为 None 时按系统当前日期判断。
    """
    from .weather_service import weather_factor  # 延迟导入，避免无 requests 环境报错

    cfg = cfg or load_flow_config()
    thresholds = cfg.get("level_thresholds", _FALLBACK_CONFIG["level_thresholds"])
    weather_map = weather_map or {}
    dt = day_type_value or holidays.day_type()
    day_factor = holidays.DAY_FACTOR.get(dt, 1.0)

    if slot:
        hours = slot_hours(slot, cfg)
    else:
        hours = [current_hour() if hour is None else int(hour) % 24]

    points: List[Dict[str, Any]] = []
    total = 0
    weather_available = bool(weather_map)
    for name, coord in VILLAGE_COORDS.items():
        vcfg = _village_cfg(name, cfg)
        capacity = int(vcfg.get("capacity", 1000))
        base_values = [hourly_flow(name, h, cfg) for h in hours]
        base_value = round(sum(base_values) / len(base_values))
        w = weather_map.get(name)
        wf = weather_factor(w)
        value = round(base_value * wf * day_factor)
        ratio = value / capacity if capacity else 0.0
        level = classify_level(ratio, thresholds)
        total += value
        points.append({
            "name": name,
            "lat": coord.get("lat"),
            "lng": coord.get("lng"),
            "city": coord.get("city", ""),
            "event": coord.get("event", ""),
            "value": value,
            "base_value": base_value,
            "capacity": capacity,
            "load_ratio": round(ratio, 3),
            "level": level,
            "level_label": LEVEL_META[level]["label"],
            "color": LEVEL_META[level]["color"],
            "weather": w,
            "weather_factor": wf,
            "day_factor": day_factor,
        })

    alerts = [p["name"] for p in points if p["level"] == "alert"]
    if weather_available:
        note = "模型估算·已结合实时天气与节假日（客流基数为仿真，天气/节假日为真实因子）"
    else:
        note = "仿真演示数据，非真实客流（未配置天气API时不做天气修正）"
    return {
        "data_note": note,
        "query_hours": hours,
        "slot": slot,
        "day_type": dt,
        "day_type_label": holidays.day_type_label(),
        "day_factor": day_factor,
        "weather_available": weather_available,
        "weather_status": weather_status if weather_available else ("no_key" if weather_status == "no_key" else "api_error"),
        "total_visitors": total,
        "alert_sites": alerts,
        "points": points,
    }


def flow_curve(name: str, cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """单个村寨 24 小时客流曲线，供前端详情图使用。"""
    cfg = cfg or load_flow_config()
    thresholds = cfg.get("level_thresholds", _FALLBACK_CONFIG["level_thresholds"])
    capacity = int(_village_cfg(name, cfg).get("capacity", 1000))
    series = []
    peak_hour, peak_value = 0, -1
    for h in range(24):
        value = hourly_flow(name, h, cfg)
        if value > peak_value:
            peak_hour, peak_value = h, value
        series.append({"hour": h, "value": value})
    coord = VILLAGE_COORDS.get(name, {})
    return {
        "name": name,
        "city": coord.get("city", ""),
        "capacity": capacity,
        "peak_hour": peak_hour,
        "peak_value": peak_value,
        "current_value": hourly_flow(name, current_hour(), cfg),
        "current_level": classify_level(
            hourly_flow(name, current_hour(), cfg) / capacity if capacity else 0,
            thresholds,
        ),
        "series": series,
    }
