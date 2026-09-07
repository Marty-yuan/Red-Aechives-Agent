# -*- coding: utf-8 -*-
"""研学课程包测试：确定性价格/学段/兜底课程表，以及工具离线主流程（不调 LLM）。"""
import json

from agent import study_course
from agent.tools import ToolRegistry


def test_normalize_stage():
    assert study_course.normalize_stage("小学高年级") == "小学"
    assert study_course.normalize_stage("高中") == "高中"
    assert study_course.normalize_stage("党员干部培训") == "党校/成人"
    assert study_course.normalize_stage(None) == "初中"
    assert study_course.normalize_stage("火星学段") == "初中"


def test_estimate_price_math():
    pricing = study_course.load_pricing_model()
    result = study_course.estimate_price("小学", days=2, group_size=40, pricing=pricing)
    per_day = pricing["stages"]["小学"]["per_student_day"]
    assert result["per_student_fee"] == per_day * 2
    assert result["total_fee"] == per_day * 2 * 40
    # 40 人、1:20 师生比 -> 2 名导师
    assert result["required_guides"] == 2
    assert result["currency"] == "元"


def test_fallback_curriculum_groups_stops_by_day():
    route = {
        "stops": [
            {"day": 1, "name": "扎西", "event": "扎西会议", "visit_time": "上午",
             "timeline_events": [{"label": "扎西会议召开"}]},
            {"day": 1, "name": "皎平渡", "event": "巧渡金沙江", "visit_time": "下午",
             "timeline_events": []},
            {"day": 2, "name": "石鼓", "event": "石鼓渡江", "visit_time": "上午",
             "timeline_events": []},
        ]
    }
    curriculum = study_course.build_fallback_curriculum(route, "初中")
    assert len(curriculum["daily_plans"]) == 2
    day1 = curriculum["daily_plans"][0]
    assert [a["site"] for a in day1["activities"]] == ["扎西", "皎平渡"]
    assert "扎西会议召开" in day1["activities"][0]["knowledge"]
    assert curriculum["source"] == "template_fallback"


def test_tool_course_pack_offline():
    """工具主流程：路线骨架用桩数据，LLM 强制失败走兜底，验证价格由代码算、结构完整。"""
    registry = ToolRegistry()
    canned_route = {
        "days": 1,
        "stops": [
            {"day": 1, "name": "扎西", "event": "扎西会议", "visit_time": "上午", "timeline_events": []},
        ],
    }
    registry._generate_study_route = lambda **kwargs: json.dumps(canned_route, ensure_ascii=False)
    registry._llm_curriculum = lambda *a, **k: None  # 模拟 LLM 不可用

    raw = registry.execute(
        "generate_course_pack",
        {"villages": ["扎西"], "days": 1, "stage": "高中", "group_size": 30},
    )
    data = json.loads(raw)
    assert data["tool"] == "generate_course_pack"
    assert data["pricing"]["stage"] == "高中"
    assert data["curriculum_source"] == "template_fallback"
    assert data["pricing"]["group_size"] == 30
    assert len(data["curriculum"]["daily_plans"]) == 1


def test_fallback_curriculum_pads_to_requested_total_days():
    """2 个现场教学点、用户要 3 天：兜底课程表必须补齐第 3 天的非移动教学环节。"""
    route = {
        "stops": [
            {"day": 1, "name": "皎平渡", "event": "巧渡金沙江", "visit_time": "上午",
             "timeline_events": []},
            {"day": 2, "name": "石鼓", "event": "石鼓渡江", "visit_time": "上午",
             "timeline_events": []},
        ]
    }
    curriculum = study_course.build_fallback_curriculum(route, "初中", total_days=3)
    plans = curriculum["daily_plans"]
    assert [p["day"] for p in plans] == [1, 2, 3]
    assert len(plans) == 3


def test_tool_course_pack_honors_more_days_than_sites():
    """用户要 3 天但只有 2 个教学点：费用按 3 天算、课程覆盖 3 天，且保留现场天数信息。"""
    registry = ToolRegistry()
    canned_route = {
        "days": 2,
        "stops": [
            {"day": 1, "name": "皎平渡", "event": "巧渡金沙江", "visit_time": "上午",
             "timeline_events": []},
            {"day": 2, "name": "石鼓", "event": "石鼓渡江", "visit_time": "上午",
             "timeline_events": []},
        ],
    }
    registry._generate_study_route = lambda **kwargs: json.dumps(canned_route, ensure_ascii=False)
    registry._llm_curriculum = lambda *a, **k: None  # 强制走兜底

    raw = registry.execute(
        "generate_course_pack",
        {"villages": ["皎平渡", "石鼓"], "days": 3, "stage": "初中", "group_size": 40},
    )
    data = json.loads(raw)
    assert data["days"] == 3           # 课程总天数听用户的
    assert data["route_days"] == 2     # 现场教学点实际覆盖 2 天
    pricing = study_course.load_pricing_model()
    per_day = pricing["stages"]["初中"]["per_student_day"]
    assert data["pricing"]["per_student_fee"] == per_day * 3
    assert len(data["curriculum"]["daily_plans"]) == 3


def test_fallback_tasks_are_site_specific():
    """兜底课程表不同教学点的探究任务不能雷同，必须绑定各自史实。"""
    route = {
        "days": 2,
        "stops": [
            {"day": 1, "name": "皎平渡", "event": "巧渡金沙江", "visit_time": "上午",
             "timeline_events": [], "attractions": ["皎平渡红军渡江遗址"]},
            {"day": 2, "name": "石鼓", "event": "石鼓渡江", "visit_time": "上午",
             "timeline_events": [], "attractions": ["石鼓红军长征渡江纪念碑"]},
        ],
    }
    curriculum = study_course.build_fallback_curriculum(route, "初中", total_days=2)
    tasks = [a["task"] for p in curriculum["daily_plans"] for a in p["activities"]]
    assert tasks[0] != tasks[1]
    assert "巧渡金沙江" in tasks[0] and "石鼓渡江" in tasks[1]


def test_tool_course_pack_includes_transport_and_lodging():
    """给了出发城市：课程包必须含往返交通、每日住宿，且课程表按天挂上物流。"""
    registry = ToolRegistry()
    canned_route = {
        "days": 2,
        "stops": [
            {"day": 1, "name": "皎平渡", "event": "巧渡金沙江", "city": "禄劝县",
             "visit_time": "上午", "timeline_events": [], "attractions": []},
            {"day": 2, "name": "石鼓", "event": "石鼓渡江", "city": "丽江市",
             "visit_time": "上午", "timeline_events": [], "attractions": []},
        ],
        "travel_segments": [],
    }
    registry._generate_study_route = lambda **kwargs: json.dumps(canned_route, ensure_ascii=False)
    registry._llm_curriculum = lambda *a, **k: None

    raw = registry.execute(
        "generate_course_pack",
        {"villages": ["皎平渡", "石鼓"], "days": 2, "stage": "初中", "start": "昆明"},
    )
    data = json.loads(raw)
    logistics = data["logistics"]
    assert logistics["departure"] == "昆明"
    assert logistics["outbound"]["from"] == "昆明" and logistics["outbound"]["estimated_road_km"] > 0
    assert logistics["return"]["to"] == "昆明"
    # 最后一天返程不住宿，其余天有住宿
    plans = data["curriculum"]["daily_plans"]
    assert plans[0]["lodging"]
    assert plans[1]["return"] and plans[1]["lodging"] is None


def test_far_departure_trims_sites_and_upgrades_transport():
    """成都出发2天：公路不现实 → 自动升级高铁，且只保留1个最可达教学点。"""
    registry = ToolRegistry()
    registry._llm_curriculum = lambda *a, **k: None
    raw = registry.execute(
        "generate_course_pack",
        {"villages": ["皎平渡", "石鼓"], "days": 2, "stage": "初中", "start": "成都"},
    )
    data = json.loads(raw)
    assert data["transport_mode"] == "rail"
    assert len(data["villages"]) == 1  # 两点间转场太远，精简为单点深度研学
    outbound = data["logistics"]["outbound"]
    assert outbound["mode"] == "rail"
    assert outbound["estimated_travel_hours"] <= 5.0  # 满足2天行程单程上限
    assert data["logistics"].get("trimmed_note")


def test_explicit_air_mode():
    """用户明确要坐飞机：往返段必须是 air。"""
    registry = ToolRegistry()
    registry._llm_curriculum = lambda *a, **k: None
    raw = registry.execute(
        "generate_course_pack",
        {"villages": ["皎平渡"], "days": 2, "start": "成都", "transport_mode": "air"},
    )
    data = json.loads(raw)
    assert data["transport_mode"] == "air"
    assert data["logistics"]["outbound"]["mode"] == "air"
    assert "✈" in data["logistics"]["outbound"]["estimated_travel_time"]


def test_near_departure_keeps_road():
    """昆明出发距离近：保持大巴，不盲目升级交通。"""
    registry = ToolRegistry()
    registry._llm_curriculum = lambda *a, **k: None
    raw = registry.execute(
        "generate_course_pack",
        {"villages": ["寻甸柯渡", "皎平渡"], "days": 2, "start": "昆明"},
    )
    data = json.loads(raw)
    assert data["transport_mode"] == "road"


def test_tool_spec_contains_course_pack():
    registry = ToolRegistry()
    spec_names = [s["name"] for s in registry.tool_specs()]
    assert "generate_course_pack" in spec_names
