"""
Web 服务 - 红色村寨数字代言人
----------------------------
整合地图 + 双路线 + 时间轴 + 战士行走动画 + 对话界面。

启动方式：
    python src/web/app.py
然后浏览器打开 http://localhost:5000
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify, Response

from agent.rag import VillageAgent
from agent import config
from agent.graph_store import KnowledgeGraphStore, get_graph_payload
from tts import synthesize_speech

app = Flask(__name__)

# 初始化 Agent（全局单例）
agent = VillageAgent()

# ===================== 村寨地理坐标 =====================
VILLAGE_COORDS = {
    "皎平渡":   {"lat": 26.30, "lng": 102.42, "city": "禄劝县", "event": "巧渡金沙江", "year": 1935, "army": "中央红军"},
    "石鼓":     {"lat": 26.87, "lng": 99.97,  "city": "丽江市", "event": "石鼓渡江", "year": 1936, "army": "红二、六军团"},
    "扎西":     {"lat": 27.85, "lng": 105.05, "city": "威信县", "event": "扎西会议", "year": 1935, "army": "中央红军"},
    "寻甸柯渡": {"lat": 25.68, "lng": 102.91, "city": "寻甸县", "event": "万急渡江令", "year": 1935, "army": "中央红军"},
    "柯渡":     {"lat": 25.68, "lng": 102.91, "city": "寻甸县", "event": "万急渡江令", "year": 1935, "army": "中央红军"},
    "寻甸":     {"lat": 25.68, "lng": 102.91, "city": "寻甸县", "event": "万急渡江令", "year": 1935, "army": "中央红军"},
    "楚雄":     {"lat": 25.03, "lng": 101.55, "city": "楚雄州", "event": "红军两过楚雄", "year": 1936, "army": "红二、六军团"},
    "曲靖":     {"lat": 25.49, "lng": 103.79, "city": "曲靖市", "event": "红军两次过曲靖", "year": "1935 / 1936", "army": "中央红军 · 红二、六军团"},
    "丽江":     {"lat": 26.86, "lng": 100.23, "city": "丽江市", "event": "红军过丽江", "year": 1936, "army": "红二、六军团"},
    "宣威":     {"lat": 26.22, "lng": 104.10, "city": "宣威市", "event": "红军过宣威", "year": 1936, "army": "红二、六军团"},
    "威信":     {"lat": 27.85, "lng": 105.05, "city": "威信县", "event": "扎西会议", "year": 1935, "army": "中央红军"},
    "禄劝":     {"lat": 25.56, "lng": 102.47, "city": "禄劝县", "event": "红军过禄劝", "year": 1935, "army": "中央红军"},
}

VILLAGE_AVATARS = {
    "皎平渡": "jiaopingdu",
    "石鼓": "shigu",
    "扎西": "zaxi",
    "寻甸柯渡": "xundian_kedu",
    "柯渡": "xundian_kedu",
    "寻甸": "xundian_kedu",
    "楚雄": "chuxiong",
    "曲靖": "qujing",
    "丽江": "lijiang",
    "宣威": "xuanwei",
    "威信": "zaxi",
    "禄劝": "luquan",
}

VILLAGE_GENDERS = {
    "皎平渡": "male",
    "石鼓": "female",
    "扎西": "male",
    "寻甸柯渡": "female",
    "柯渡": "female",
    "寻甸": "female",
    "楚雄": "male",
    "曲靖": "male",
    "丽江": "female",
    "宣威": "male",
    "威信": "male",
    "禄劝": "female",
}

# ===================== 两条行军路线 =====================
# 中央红军（1935）和红二、六军团（1936）是两支队伍、两个时间段
ROUTES = [
    {
        "name": "中央红军（1935年）",
        "color": "#C41E3A",
        "points": [
            [27.85, 105.05],  # 扎西/威信（1935.2 入滇）
            [25.49, 103.79],  # 曲靖（1935.4）
            [25.68, 102.91],  # 寻甸柯渡（1935.4 万急渡江令）
            [25.04, 102.71],  # 昆明（1935.4 威逼昆明）
            [25.56, 102.47],  # 禄劝（1935.5）
            [26.30, 102.42],  # 皎平渡（1935.5 巧渡金沙江）
        ],
        "direction": "西北→东南→西→北",
    },
    {
        "name": "红二、六军团（1936年）",
        "color": "#E67E22",
        "points": [
            [26.22, 104.10],  # 宣威（1936.3 入滇）
            [25.49, 103.79],  # 曲靖（1936.4）
            [25.03, 101.55],  # 楚雄（1936.4）
            [26.86, 100.23],  # 丽江（1936.4）
            [26.87, 99.97],   # 石鼓（1936.4 渡江）
        ],
        "direction": "东北→西南→西北",
    },
]

# ===================== 时间轴事件 =====================
TIMELINE = [
    {"date": "1935-02-05", "label": "扎西会议", "village": "扎西", "army": "中央红军",
     "desc": "中共中央在威信扎西召开会议，确立毛泽东实际指挥地位，进行扎西整编。"},
    {"date": "1935-04-29", "label": "万急渡江令", "village": "寻甸柯渡", "army": "中央红军",
     "desc": "中革军委在柯渡丹桂村发出万急渡江令，兵分三路抢占金沙江渡口。"},
    {"date": "1935-05-03", "label": "巧渡金沙江", "village": "皎平渡", "army": "中央红军",
     "desc": "中央红军在皎平渡用7条木船、36名船工，7天7夜将3万将士渡过金沙江。"},
    {"date": "1936-03-20", "label": "红二六军团入滇", "village": "宣威", "army": "红二、六军团",
     "desc": "贺龙、任弼时率红二、六军团从贵州进入云南宣威，突破滇军防线。"},
    {"date": "1936-04-25", "label": "石鼓渡江", "village": "石鼓", "army": "红二、六军团",
     "desc": "红二六军团在丽江石鼓至巨甸5个渡口抢渡金沙江，1.8万将士全部过江。"},
]


@app.route("/")
def index():
    """首页"""
    return render_template("index.html")


@app.route("/chat", methods=["POST"])
def chat():
    """对话接口"""
    data = request.get_json()
    village = data.get("village", "皎平渡")
    question = data.get("question", "")

    if not question:
        return jsonify({"error": "问题不能为空"}), 400

    try:
        answer = agent.ask(question, village=village)
        return jsonify({
            "village": village,
            "answer": answer,
            "plan": agent.last_plan,
            "verification": agent.last_verification,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/villages")
def get_villages():
    """返回村寨列表（含坐标、年份、所属队伍）"""
    villages = []
    seen = set()
    seen_coords = set()
    for name in config.VILLAGES:
        if name in seen or name not in VILLAGE_COORDS:
            continue
        c = VILLAGE_COORDS[name]
        coord = (round(c["lat"], 2), round(c["lng"], 2))
        if coord in seen_coords:
            continue
        seen.add(name)
        seen_coords.add(coord)
        villages.append({
            "name": name,
            "lat": c["lat"],
            "lng": c["lng"],
            "city": c["city"],
            "event": c["event"],
            "year": c["year"],
            "army": c["army"],
            "avatar": "/static/avatars/" + VILLAGE_AVATARS.get(name, "zaxi") + ".png",
            "voice_gender": VILLAGE_GENDERS.get(name, "female"),
        })
    return jsonify(villages)


@app.route("/api/routes")
def get_routes():
    """返回两条行军路线"""
    return jsonify({"routes": ROUTES})


@app.route("/api/timeline")
def get_timeline():
    """返回时间轴事件"""
    return jsonify(TIMELINE)


@app.route("/api/knowledge_graph")
def get_knowledge_graph():
    """返回档案知识图谱，供前端 vis-network 绘制。"""
    return jsonify(get_graph_payload())


@app.route("/api/kg/query", methods=["POST"])
def api_kg_query():
    """按实体/主题查询知识图谱邻居。"""
    data = request.get_json(silent=True) or {}
    store = KnowledgeGraphStore()
    result = store.query(
        topic=data.get("topic"),
        entity=data.get("entity"),
        relation=data.get("relation"),
        event=data.get("event"),
        year=data.get("year"),
        limit=int(data.get("limit") or 10),
    )
    return jsonify(result)


@app.route("/api/tts", methods=["POST"])
def api_tts():
    """把村寨代言人的回答合成为语音，返回音频。"""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    village = data.get("village") or ""
    gender = data.get("gender") or VILLAGE_GENDERS.get(village, "female")

    if not text:
        return jsonify({"error": "text????"}), 400

    result = synthesize_speech(text, gender=gender)
    if not result:
        return jsonify({"error": "TTS????"}), 503

    audio_bytes, voice, mime = result
    return Response(
        audio_bytes,
        mimetype=mime,
        headers={
            "X-Voice": voice,
            "Cache-Control": "no-store",
        },
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)