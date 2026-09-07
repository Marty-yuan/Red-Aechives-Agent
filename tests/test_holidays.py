# -*- coding: utf-8 -*-
"""中国法定节假日与调休工作日查询测试（2026 年数据来自国务院办公厅通知）。"""
from datetime import date

from agent import holidays


def test_2026_holiday_dates():
    assert holidays.is_holiday("2026-02-17")  # 春节
    assert holidays.holiday_name("2026-02-17") == "春节"
    assert holidays.is_holiday("2026-10-01")
    assert holidays.holiday_name("2026-10-01") == "国庆节"
    assert holidays.is_holiday("2026-09-25")  # 中秋
    assert not holidays.is_holiday("2026-03-10")


def test_2026_makeup_workdays():
    # 调休上班日：周末但要上班
    assert holidays.is_workday_makeup("2026-02-14")
    assert holidays.is_workday_makeup("2026-10-10")
    assert holidays.day_type("2026-02-14") == "workday_makeup"


def test_day_type_categories():
    assert holidays.day_type("2026-05-01") == "holiday"
    assert holidays.day_type("2026-09-12") == "weekend"  # 周六
    assert holidays.day_type("2026-09-14") == "workday"  # 周一
    assert "节假日" in holidays.day_type_label("2026-05-01")


def test_day_factors():
    assert holidays.DAY_FACTOR["holiday"] > holidays.DAY_FACTOR["weekend"]
    assert holidays.DAY_FACTOR["workday_makeup"] == holidays.DAY_FACTOR["workday"]
