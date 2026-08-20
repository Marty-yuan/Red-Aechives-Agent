"""
Web 服务 - 红色村寨数字代言人
----------------------------
整合地图 + 双路线 + 时间轴 + 战士行走动画 + 对话界面。

启动方式：
    python src/web/app.py
然后浏览器打开 http://localhost:5000
"""
import difflib
import os, re, sys, json
from pathlib import Path
from opencc import OpenCC
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template, request, jsonify, Response

from agent.rag import VillageAgent
from agent import config
from agent.graph_store import KnowledgeGraphStore, get_graph_payload
from tts import synthesize_speech

app = Flask(__name__)

# 初始化 Agent（全局单例）
agent = VillageAgent()


def _find_source_pdf(source):
    """根据证据来源文件名匹配原始 OCR PDF。"""
    base = Path(source or "").stem.lower()
    pdf_dir = Path(config.PDF_DIR)
    if not pdf_dir.exists():
        return None
    candidates = list(pdf_dir.glob("*.pdf"))
    if not candidates:
        return None

    def score(pdf_path):
        return difflib.SequenceMatcher(None, base, pdf_path.stem.lower()).ratio()

    best = max(candidates, key=score)
    return best if score(best) >= 0.55 else None


_CC = OpenCC("t2s")
_PDF_PAGE_TEXT_CACHE = {}


def _normalize_trace_text(text):
    """繁体转简体，并去掉空格和标点，减少 OCR 差异对匹配的影响。"""
    text = _CC.convert(text or "")
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", text)


def _get_pdf_page_texts(pdf_path):
    """按 PDF 缓存每页规范化后的文本，避免每次点击都重新解析整个 PDF。"""
    key = str(pdf_path)
    if key in _PDF_PAGE_TEXT_CACHE:
        return _PDF_PAGE_TEXT_CACHE[key]

    import fitz

    doc = fitz.open(pdf_path)
    try:
        texts = [_normalize_trace_text(page.get_text()) for page in doc]
    finally:
        doc.close()

    _PDF_PAGE_TEXT_CACHE[key] = texts
    return texts


def _find_page_by_text(pdf_path, text):
    """返回 (页码索引, 置信度)；若置信度过低则页码为 None。"""
    page_texts = _get_pdf_page_texts(pdf_path)
    if not page_texts:
        return None, 0.0

    q = _normalize_trace_text(text)
    if not q:
        return None, 0.0

    best_idx = None
    best_score = -1.0
    for idx, page_text in enumerate(page_texts):
        if not page_text:
            continue

        # 优先精确匹配，OCR 同源时最快也最稳
        if q in page_text:
            return idx, 1.0

        score = difflib.SequenceMatcher(None, q, page_text, autojunk=False).ratio()
        if score > best_score:
            best_score = score
            best_idx = idx

    # 阈值过低说明没找到可信页面，返回 None，不再错误落到第 1 页
    if best_score < 0.45:
        return None, best_score
    return best_idx, best_score


@app.route("/api/pdf/page")
def api_pdf_page():
    """返回证据来源 PDF 的原始页面图片。"""
    source = request.args.get("source", "")
    text = request.args.get("text", "")
    if not source:
        return jsonify({"error": "缺少 source"}), 400

    pdf_path = _find_source_pdf(source)
    if not pdf_path:
        return jsonify({"error": "找不到对应 PDF"}), 404

    try:
        import fitz
    except Exception:
        return jsonify({"error": "PyMuPDF 不可用"}), 500

    page_index, confidence = _find_page_by_text(pdf_path, text)
    if page_index is None:
        return jsonify({"error": "未能定位到相关页面"}), 404

    doc = fitz.open(pdf_path)
    try:
        page_index = max(0, min(page_index, doc.page_count - 1))
        pix = doc.load_page(page_index).get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
        resp = Response(pix.tobytes("png"), mimetype="image/png")
        resp.headers["X-Page"] = str(page_index + 1)
        resp.headers["X-Page-Count"] = str(doc.page_count)
        resp.headers["X-Confidence"] = f"{confidence:.3f}"
        return resp
    finally:
        doc.close()

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
            "tool_results": agent.last_tool_results,
            "evidence": agent.last_evidence,
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
        return jsonify({"error": "文本不能为空"}), 400

    result = synthesize_speech(text, gender=gender)
    if not result:
        return jsonify({"error": "语音合成暂不可用，请稍后重试"}), 503

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
    app.run(
        host=config.WEB_HOST,
        port=config.WEB_PORT,
        debug=config.WEB_DEBUG,
    )