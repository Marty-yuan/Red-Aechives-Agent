# -*- coding: utf-8 -*-
"""天气服务测试：系数规则、缓存、未配置 key 优雅降级。"""
from agent import weather_service as ws


def test_weather_factor_rain_reduces():
    assert ws.weather_factor({"text": "小雨", "temp": "20"}) == 0.6
    assert ws.weather_factor({"text": "雷阵雨", "temp": "22"}) == 0.6


def test_weather_factor_extreme_temp():
    assert ws.weather_factor({"text": "晴", "temp": "35"}) == 0.8
    assert ws.weather_factor({"text": "晴", "temp": "-3"}) == 0.85


def test_weather_factor_clear_normal():
    assert ws.weather_factor({"text": "晴", "temp": "24"}) == 1.0
    assert ws.weather_factor({"text": "多云", "temp": "24"}) == 0.9
    assert ws.weather_factor(None) == 1.0


def test_no_key_returns_none(monkeypatch):
    monkeypatch.setattr(ws.config, "QWEATHER_API_KEY", "")
    assert ws.get_weather(26.3, 102.4) is None
    assert ws.get_weather_batch([("测试", 26.3, 102.4)]) == {}


def test_cache_returns_cached_without_request(monkeypatch):
    monkeypatch.setattr(ws.config, "QWEATHER_API_KEY", "fake-key")
    ws.clear_cache()
    fake = {"temp": "18", "text": "晴", "icon": "100"}
    ws._cache[ws._cache_key(26.3, 102.4)] = {"data": fake, "fetched_at": 9e18}
    # 缓存命中，不会真的发请求
    assert ws.get_weather(26.3, 102.4) is fake
    ws.clear_cache()
