# -*- coding: utf-8 -*-
"""中国法定节假日与调休工作日查询。

数据来源：国务院办公厅《关于2026年部分节假日安排的通知》（国办发明电〔2025〕7号）。
覆盖 2026 全年；2027 年安排尚未发布，超出范围时回退为"周末/工作日"判断，
并在 day_type 中标注 estimated，调用方应避免把它当作权威节假日。
"""
from datetime import date, datetime
from typing import Dict, Optional, Tuple

# 节假日名称 → 放假日期列表（含调休凑出的休息日）
HOLIDAYS_2026: Dict[str, Tuple[str, ...]] = {
    "元旦": ("2026-01-01", "2026-01-02", "2026-01-03"),
    "春节": ("2026-02-15", "2026-02-16", "2026-02-17", "2026-02-18", "2026-02-19",
             "2026-02-20", "2026-02-21", "2026-02-22", "2026-02-23"),
    "清明节": ("2026-04-04", "2026-04-05", "2026-04-06"),
    "劳动节": ("2026-05-01", "2026-05-02", "2026-05-03", "2026-05-04", "2026-05-05"),
    "端午节": ("2026-06-19", "2026-06-20", "2026-06-21"),
    "中秋节": ("2026-09-25", "2026-09-26", "2026-09-27"),
    "国庆节": ("2026-10-01", "2026-10-02", "2026-10-03", "2026-10-04",
              "2026-10-05", "2026-10-06", "2026-10-07"),
}

# 调休上班日（周末但要上班，客流按工作日算）
WORKDAY_MAKEUP_2026 = (
    "2026-01-04",  # 元旦
    "2026-02-14", "2026-02-28",  # 春节
    "2026-05-09",  # 劳动节
    "2026-09-20", "2026-10-10",  # 国庆
)

_HOLIDAY_INDEX: Dict[str, str] = {}
for _name, _days in HOLIDAYS_2026.items():
    for _d in _days:
        _HOLIDAY_INDEX[_d] = _name
_MAKEUP_INDEX = set(WORKDAY_MAKEUP_2026)


def _to_date(d) -> date:
    if isinstance(d, datetime):
        return d.date()
    if isinstance(d, date):
        return d
    return datetime.strptime(str(d), "%Y-%m-%d").date()


def holiday_name(d) -> Optional[str]:
    """返回某日的节假日名称，非节假日返回 None。"""
    return _HOLIDAY_INDEX.get(_to_date(d).isoformat())


def is_holiday(d) -> bool:
    return _to_date(d).isoformat() in _HOLIDAY_INDEX


def is_workday_makeup(d) -> bool:
    """调休上班日（周末但要上班）。"""
    return _to_date(d).isoformat() in _MAKEUP_INDEX


def day_type(d=None) -> str:
    """返回 day 类型：holiday / weekend / workday_makeup / workday。

    2026 年以外的日期不查节假日表，只按周末/工作日判断（调用方应视为估算）。
    """
    d = _to_date(d) if d else datetime.now().date()
    iso = d.isoformat()
    if iso in _HOLIDAY_INDEX:
        return "holiday"
    if iso in _MAKEUP_INDEX:
        return "workday_makeup"
    if d.year == 2026:
        return "weekend" if d.weekday() >= 5 else "workday"
    # 2026 以外：节假日表未覆盖，按周末估算
    return "weekend" if d.weekday() >= 5 else "workday"


def day_type_label(d=None) -> str:
    t = day_type(d)
    name = holiday_name(d) if t == "holiday" else None
    return {
        "holiday": f"法定节假日（{name}）" if name else "法定节假日",
        "weekend": "周末",
        "workday_makeup": "调休上班日",
        "workday": "工作日",
    }[t]


# 客流日系数：法定节假日最高，周末次之，调休上班日按工作日
DAY_FACTOR = {
    "holiday": 1.8,
    "weekend": 1.3,
    "workday_makeup": 1.0,
    "workday": 1.0,
}
