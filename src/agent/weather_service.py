# -*- coding: utf-8 -*-
"""实时天气服务（和风天气 QWeather 免费个人版）。

设计要点：
- 免费订阅 1000 次/天、1 次/秒，因此必须做内存缓存（默认 15 分钟），
  9 个教学点每 15 分钟刷新一次 ≈ 864 次/天，在免费额度内；
- API 失败 / 未配置 key 时返回 None，上层客流热力照常显示（优雅降级）；
- QWeather 坐标顺序是 经度,纬度（lng,lat），与常见的 lat,lng 相反，这里已封装。
"""
import gzip
import json
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional, Tuple

from . import config

_CACHE_TTL = 15 * 60  # 15 分钟
_cache: Dict[str, Dict[str, Any]] = {}

# 和风天气 icon code → emoji（覆盖常用码，其余回退 🌡️）
_ICON_EMOJI = {
    "100": "☀️", "101": "⛅", "102": "⛅", "103": "☁️", "104": "☁️",
    "150": "🌙", "151": "☁️", "152": "☁️", "153": "☁️", "154": "☁️",
    "300": "🌦️", "301": "🌧️", "302": "🌧️", "303": "⛈️", "304": "⛈️",
    "305": "🌧️", "306": "🌧️", "307": "🌧️", "308": "🌧️", "309": "🌧️",
    "310": "🌧️", "311": "🌧️", "312": "🌧️", "313": "🌧️", "314": "🌧️",
    "315": "🌧️", "316": "🌧️", "317": "🌧️", "318": "🌧️", "350": "🌧️",
    "351": "🌧️", "399": "🌧️",
    "400": "🌨️", "401": "❄️", "402": "❄️", "403": "❄️", "404": "❄️",
    "405": "🌨️", "406": "🌨️", "407": "🌨️", "408": "❄️", "409": "❄️",
    "410": "❄️", "456": "🌨️", "457": "❄️", "499": "❄️",
    "500": "🌫️", "501": "🌫️", "502": "🌫️", "503": "🌫️", "504": "🌫️",
    "507": "🌫️", "508": "🌫️", "509": "🌫️", "510": "🌫️", "511": "🌫️",
    "512": "🌫️", "513": "🌫️", "514": "🌫️", "515": "🌫️", "900": "🌡️",
    "901": "🌡️", "999": "🌡️",
}


def _cache_key(lat: float, lng: float) -> str:
    return f"{round(lat, 2)},{round(lng, 2)}"


def get_weather(lat: float, lng: float, timeout: float = 5.0) -> Optional[Dict[str, Any]]:
    """获取单个坐标的实时天气；失败或未配置 key 返回 None。"""
    if not config.QWEATHER_API_KEY:
        return None
    key = _cache_key(lat, lng)
    cached = _cache.get(key)
    if cached and time.time() - cached["fetched_at"] < _CACHE_TTL:
        return cached["data"]
    try:
        # QWeather location 参数顺序为 经度,纬度
        qs = urllib.parse.urlencode({"location": f"{lng},{lat}", "key": config.QWEATHER_API_KEY})
        url = f"{config.QWEATHER_BASE_URL}/v7/weather/now?{qs}"
        req = urllib.request.Request(url, headers={"User-Agent": "red-archives-agent/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                return None
            raw = resp.read()
            # 和风天气专属域名可能返回 gzip 压缩，必须先解压
            if resp.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            payload = json.loads(raw.decode("utf-8"))
        if str(payload.get("code", "")) != "200":
            return None
        now = payload.get("now") or {}
        icon_code = str(now.get("icon", ""))
        data = {
            "temp": now.get("temp"),
            "feels_like": now.get("feelsLike"),
            "text": now.get("text", ""),
            "icon": icon_code,
            "icon_emoji": _ICON_EMOJI.get(icon_code, "🌡️"),
            "wind_dir": now.get("windDir", ""),
            "wind_scale": now.get("windScale", ""),
            "humidity": now.get("humidity", ""),
            "obs_time": now.get("obsTime", ""),
            "source": "qweather",
        }
        _cache[key] = {"data": data, "fetched_at": time.time()}
        return data
    except Exception:
        return None


def get_weather_batch(sites: List[Tuple[str, float, float]]) -> Dict[str, Dict[str, Any]]:
    """批量获取多个地点天气，并发请求；返回 {地点名: weather}，失败的点不出现。"""
    result: Dict[str, Dict[str, Any]] = {}
    if not sites or not config.QWEATHER_API_KEY:
        return result
    with ThreadPoolExecutor(max_workers=min(4, len(sites))) as pool:
        futures = {pool.submit(get_weather, lat, lng): name for name, lat, lng in sites}
        for fut in as_completed(futures):
            name = futures[fut]
            try:
                w = fut.result()
                if w:
                    result[name] = w
            except Exception:
                continue
    return result


def weather_factor(weather: Optional[Dict[str, Any]]) -> float:
    """天气对客流的影响系数：雨雪降温、极端高温/低温都会抑制出游。"""
    if not weather:
        return 1.0
    text = str(weather.get("text", ""))
    if any(k in text for k in ("雨", "雪", "雷", "冰雹")):
        return 0.6
    if any(k in text for k in ("雾", "霾", "沙", "浮尘")):
        return 0.75
    if any(k in text for k in ("阴", "多云")):
        return 0.9
    try:
        temp = float(weather.get("temp"))
        if temp >= 33:
            return 0.8
        if temp <= 0:
            return 0.85
    except (TypeError, ValueError):
        pass
    return 1.0


def clear_cache() -> None:
    """测试用：清空天气缓存。"""
    _cache.clear()
