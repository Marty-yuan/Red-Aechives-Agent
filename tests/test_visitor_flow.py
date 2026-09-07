# -*- coding: utf-8 -*-
"""客流热力确定性逻辑测试：等级划分、小时/时段快照、24h 曲线、峰值。"""
from agent import visitor_flow as vf


def _cfg():
    return vf.load_flow_config()


def test_classify_level_thresholds():
    t = {"comfortable": 0.4, "moderate": 0.7, "crowded": 0.9}
    assert vf.classify_level(0.1, t) == "comfortable"
    assert vf.classify_level(0.4, t) == "moderate"
    assert vf.classify_level(0.75, t) == "crowded"
    assert vf.classify_level(0.95, t) == "alert"


def test_deep_night_zero_flow():
    """凌晨 3 点权重为 0，所有点客流为 0、等级宽松。"""
    snap = vf.heatmap_snapshot(hour=3, cfg=_cfg())
    assert snap["total_visitors"] == 0
    assert all(p["value"] == 0 and p["level"] == "comfortable" for p in snap["points"])
    # 每个点都带经纬度，供前端热力层直接渲染
    assert all(p["lat"] is not None and p["lng"] is not None for p in snap["points"])


def test_peak_hour_snapshot_structure():
    """17 点为权重峰值，快照结构完整且等级分布合理。"""
    snap = vf.heatmap_snapshot(hour=17, cfg=_cfg())
    assert len(snap["points"]) >= 9
    levels = {p["level"] for p in snap["points"]}
    # 峰值时段至少出现适中及以上等级
    assert levels & {"moderate", "crowded", "alert"}
    # alert_sites 与 points 中 alert 一致
    alert_points = [p["name"] for p in snap["points"] if p["level"] == "alert"]
    assert snap["alert_sites"] == alert_points


def test_slot_averages_hours():
    """时段快照取该时段各小时均值，query_hours 正确。"""
    cfg = _cfg()
    snap = vf.heatmap_snapshot(slot="morning", cfg=cfg)
    assert snap["query_hours"] == [8, 9, 10, 11]
    # 手工复算一个村寨验证均值
    name = snap["points"][0]["name"]
    expected = round(sum(vf.hourly_flow(name, h, cfg) for h in [8, 9, 10, 11]) / 4)
    assert snap["points"][0]["value"] == expected


def test_flow_curve_24h_and_peak():
    curve = vf.flow_curve("扎西", cfg=_cfg())
    assert len(curve["series"]) == 24
    assert curve["peak_hour"] == 17  # 权重峰值在 17 点
    assert curve["peak_value"] == max(s["value"] for s in curve["series"])
    assert curve["capacity"] > 0


def test_unknown_village_uses_default():
    cfg = _cfg()
    value = vf.hourly_flow("不存在的村寨", 12, cfg)
    expected = round(cfg["default_village"]["base_daily"] * cfg["hourly_weight"][12])
    assert value == expected


def test_weather_map_adjusts_flow():
    """传入雨天天气时，客流应低于纯仿真基线，且保留 base_value 可溯源。"""
    cfg = _cfg()
    rain = {"text": "小雨", "temp": "18", "icon": "305", "icon_emoji": "🌧️"}
    snap_rain = vf.heatmap_snapshot(hour=14, cfg=cfg, weather_map={"扎西": rain},
                                    day_type_value="workday")
    snap_plain = vf.heatmap_snapshot(hour=14, cfg=cfg, day_type_value="workday")
    zx_rain = next(p for p in snap_rain["points"] if p["name"] == "扎西")
    zx_plain = next(p for p in snap_plain["points"] if p["name"] == "扎西")
    assert zx_rain["base_value"] == zx_plain["value"]
    assert zx_rain["value"] < zx_plain["value"]
    assert zx_rain["weather"] is rain
    assert zx_rain["weather_factor"] == 0.6


def test_holiday_factor_increases_flow():
    cfg = _cfg()
    snap_holiday = vf.heatmap_snapshot(hour=14, cfg=cfg, day_type_value="holiday")
    snap_workday = vf.heatmap_snapshot(hour=14, cfg=cfg, day_type_value="workday")
    assert snap_holiday["total_visitors"] > snap_workday["total_visitors"]
    assert snap_holiday["day_factor"] == 1.8


def test_snapshot_carries_weather_availability_flag():
    cfg = _cfg()
    snap = vf.heatmap_snapshot(hour=14, cfg=cfg, weather_map={"扎西": {"text": "晴"}})
    assert snap["weather_available"] is True
    assert "实时天气" in snap["data_note"]
    snap2 = vf.heatmap_snapshot(hour=14, cfg=cfg)
    assert snap2["weather_available"] is False
