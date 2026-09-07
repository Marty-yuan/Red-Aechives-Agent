# -*- coding: utf-8 -*-
"""课程包意图纠偏测试：Planner 错选/漏选时，规则层必须纠正，且不依赖网络。"""
from agent.orchestrator import OrchestratorAgent
from agent import study_course


def test_route_step_replaced_when_course_intent():
    # 用户要课程包，Planner 却错选了红旅路线 -> 必须替换成课程包工具
    plan = {
        "is_complex": True,
        "task_type": "route_plan",
        "steps": [{"tool": "generate_study_route",
                   "arguments": {"villages": [], "days": 3}, "purpose": ""}],
    }
    fixed = OrchestratorAgent._enforce_course_pack("给我一个初中学生，为期3天的研学课程包", plan)
    tools = [s["tool"] for s in fixed["steps"]]
    assert "generate_study_route" not in tools
    assert tools == ["generate_course_pack"]
    args = fixed["steps"][0]["arguments"]
    assert args["days"] == 3
    assert args["stage"] == "初中"
    assert fixed["task_type"] == "study_course"


def test_redundant_route_removed_when_course_already_planned():
    plan = {
        "is_complex": True,
        "steps": [
            {"tool": "generate_course_pack", "arguments": {"villages": ["扎西"]}, "purpose": ""},
            {"tool": "generate_study_route", "arguments": {}, "purpose": ""},
        ],
    }
    fixed = OrchestratorAgent._enforce_course_pack("扎西研学课程包和路线", plan)
    tools = [s["tool"] for s in fixed["steps"]]
    assert tools == ["generate_course_pack"]


def test_course_step_appended_when_planner_missed():
    plan = {"is_complex": False, "steps": []}
    fixed = OrchestratorAgent._enforce_course_pack("帮我备一节高中教案，2天", plan)
    assert fixed["is_complex"] is True
    assert fixed["steps"][0]["tool"] == "generate_course_pack"
    assert fixed["steps"][0]["arguments"]["stage"] == "高中"
    assert fixed["steps"][0]["arguments"]["days"] == 2


def test_plain_route_question_untouched():
    plan = {
        "is_complex": True,
        "steps": [{"tool": "generate_study_route", "arguments": {"days": 2}, "purpose": ""}],
    }
    fixed = OrchestratorAgent._enforce_course_pack("给我一条2天的旅游路线，轻松点", plan)
    assert [s["tool"] for s in fixed["steps"]] == ["generate_study_route"]


def test_departure_city_extracted_into_course_step():
    plan = {
        "is_complex": True,
        "steps": [{"tool": "generate_study_route",
                   "arguments": {"villages": ["皎平渡"], "days": 2}, "purpose": ""}],
    }
    fixed = OrchestratorAgent._enforce_course_pack("从昆明出发，做一个皎平渡2天研学课程包", plan)
    args = fixed["steps"][0]["arguments"]
    assert args["start"] == "昆明"
    assert OrchestratorAgent.detect_departure("我们在攀枝花集合") == "攀枝花"
    assert OrchestratorAgent.detect_departure("就在村里") is None


def test_detect_transport_mode():
    assert OrchestratorAgent.detect_transport_mode("坐飞机去") == "air"
    assert OrchestratorAgent.detect_transport_mode("乘高铁前往") == "rail"
    assert OrchestratorAgent.detect_transport_mode("包车过去") == "road"
    assert OrchestratorAgent.detect_transport_mode("就去两天") is None
    plan = {
        "is_complex": True,
        "steps": [{"tool": "generate_course_pack",
                   "arguments": {"villages": ["皎平渡"], "days": 2, "start": "成都"}, "purpose": ""}],
    }
    fixed = OrchestratorAgent._enforce_course_pack("成都出发坐飞机，2天皎平渡研学课程包", plan)
    assert fixed["steps"][0]["arguments"]["transport_mode"] == "air"


def test_detect_stage():
    assert study_course.detect_stage("初中学生") == "初中"
    assert study_course.detect_stage("党员干部培训") == "党校/成人"
    assert study_course.detect_stage("随便走走") is None
    # normalize_stage 仍然有默认值兜底
    assert study_course.normalize_stage("火星学段") == "初中"
