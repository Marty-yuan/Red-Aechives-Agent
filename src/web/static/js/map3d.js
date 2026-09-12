// ============================================================
// ========== 3D 地形地图（MapLibre GL JS） ====================
// ============================================================
const MAPTILER_KEY = "uwoxViCeY0IJyq46b6DA";
let map3d = null;          // MapLibre 实例
let is3DMode = false;
let map3dReady = false;
let map3dPlayTimer = null;

function init3DMap() {
    if (map3d || typeof maplibregl === "undefined") return;
    const el = document.getElementById("map3d");
    map3d = new maplibregl.Map({
        container: "map3d",
        style: "https://api.maptiler.com/maps/topo/style.json?key=" + MAPTILER_KEY,
        center: [101.5, 25.5],
        zoom: 7,
        pitch: 55,
        bearing: 0,
        attributionControl: false,
        maxPitch: 75
    });

    map3d.on("load", () => {
        // 导航控件（缩放/旋转/俯仰）
        map3d.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), "top-right");

        // 加载 3D 地形起伏
        map3d.addSource("terrainSource", {
            type: "raster-dem",
            url: "https://api.maptiler.com/tiles/terrain-rgb/tiles.json?key=" + MAPTILER_KEY,
            tileSize: 256,
            maxzoom: 14
        });
        map3d.setTerrain({ source: "terrainSource", exaggeration: 1.4 });

        // 加两条长征路线
        if (Array.isArray(routes)) {
            routes.forEach((route, ri) => {
                const coords = (route.points || []).map(p => [p[1], p[0]]);
                if (coords.length < 2) return;
                map3d.addSource("r3d-" + ri, {
                    type: "geojson",
                    data: { type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } }
                });
                map3d.addLayer({
                    id: "r3d-line-" + ri,
                    type: "line",
                    source: "r3d-" + ri,
                    paint: { "line-color": route.color || "#C41E3A", "line-width": 4, "line-opacity": 0.92 }
                });
            });
        }

        // 加村寨标记（billboard 风格的 HTML 标记）
        if (Array.isArray(window.__villagesData)) {
            window.__villagesData.forEach(v => {
                if (!v.lat || !v.lng) return;
                const el = document.createElement("div");
                el.style.cssText = "width:16px;height:16px;border-radius:50%;background:#C41E3A;border:2px solid #FFD700;cursor:pointer;box-shadow:0 0 8px rgba(255,215,0,0.6);";
                el.title = v.name;
                el.addEventListener("click", () => { if (typeof selectVillage === "function") selectVillage(v.name); });
                new maplibregl.Marker({ element: el })
                    .setLngLat([v.lng, v.lat])
                    .setPopup(new maplibregl.Popup({ offset: 25 }).setHTML("<b>" + v.name + "</b><br>" + (v.event||"") + " · " + (v.year||"")))
                    .addTo(map3d);
            });
        }

        // 红军战士 billboard 精灵
        const soldierEl = document.createElement("div");
        soldierEl.style.cssText = "width:50px;height:50px;background:url('/static/soldier.png') center/contain no-repeat;pointer-events:none;filter:drop-shadow(0 4px 6px rgba(0,0,0,0.5));";
        window.__soldier3d = new maplibregl.Marker({ element: soldierEl, anchor: "bottom" })
            .setLngLat([101.5, 25.5])
            .addTo(map3d);

        map3dReady = true;
    });
}

// 切换 2D / 3D
function toggle3D() {
    is3DMode = !is3DMode;
    const leafletDiv = document.getElementById("map");
    const map3dDiv = document.getElementById("map3d");
    const btn = document.getElementById("toggle3DBtn");

    if (is3DMode) {
        leafletDiv.style.display = "none";
        map3dDiv.style.display = "block";
        btn.style.borderColor = "#f5c842";
        btn.style.color = "#f5c842";
        if (!map3d) init3DMap();
        else map3d.resize();
        // 把 2D 当前视野同步到 3D
        if (map && map3d) {
            const c = map.getCenter();
            const z = map.getZoom();
            map3d.jumpTo({ center: [c.lng, c.lat], zoom: z, pitch: 55 });
        }
    } else {
        map3dDiv.style.display = "none";
        leafletDiv.style.display = "block";
        btn.style.borderColor = "";
        btn.style.color = "";
        if (map) map.invalidateSize();
        if (map3dPlayTimer) { cancelAnimationFrame(map3dPlayTimer); map3dPlayTimer = null; }
    }
}

// 3D 路线播放：摄像机沿路线平滑飞行（防抖动 / 防眩晕）
function playRoute3D(routeIdx) {
    if (!map3dReady || !map3d || !routes[routeIdx]) return;
    const pts = routes[routeIdx].points;   // [[lat, lng], ...]
    if (!pts || pts.length < 2) return;

    if (map3dPlayTimer) { cancelAnimationFrame(map3dPlayTimer); map3dPlayTimer = null; }

    const total = pts.length;
    const duration = Math.min(Math.max(total * 180, 16000), 32000);  // 16–32 秒，放慢
    const startTime = performance.now();
    routePlayActive = routeIdx;
    syncRouteButtons(routeIdx);

    // ① 按「累计弧长」参数化：路线点疏密不均（城市段极密、野外段稀疏），
    //    若按点序号线性推进，镜头会忽快忽慢产生顿挫。改为弧长匀速。
    const cum = new Array(total).fill(0);
    let totalLen = 0;
    for (let i = 1; i < total; i++) {
        const dLat = pts[i][0] - pts[i - 1][0];
        const dLng = (pts[i][1] - pts[i - 1][1]) * Math.cos(pts[i][0] * Math.PI / 180);
        totalLen += Math.hypot(dLat, dLng);
        cum[i] = totalLen;
    }
    function idxAt(dist) {
        let lo = 0, hi = total - 1;
        while (lo < hi) { const mid = (lo + hi) >> 1; if (cum[mid] < dist) lo = mid + 1; else hi = mid; }
        return lo;
    }

    // ② 预计算平滑朝向：固定「向前看 LA_DIST 弧长」（与点密度无关），
    //    再解缠 + 滑动平均，消除逐点噪声与 ±180° 翻转导致的镜头猛甩。
    //    罗盘角轴向：bearing = atan2(Δlng, Δlat)，东=90°。
    const LA_DIST = Math.max(totalLen * 0.010, 0.02);
    const raw = new Array(total).fill(0);
    for (let i = 0; i < total; i++) {
        const j = idxAt(Math.min(totalLen, cum[i] + LA_DIST));
        const dLat = pts[j][0] - pts[i][0];
        const dLng = pts[j][1] - pts[i][1];
        raw[i] = (Math.abs(dLat) + Math.abs(dLng) < 1e-9)
            ? raw[Math.max(0, i - 1)]
            : Math.atan2(dLng, dLat) * 180 / Math.PI;
    }
    for (let i = 1; i < total; i++) {
        while (raw[i] - raw[i - 1] > 180) raw[i] -= 360;
        while (raw[i] - raw[i - 1] < -180) raw[i] += 360;
    }
    const WIN = 28;
    const bearing = new Array(total);
    for (let i = 0; i < total; i++) {
        let sum = 0, n = 0;
        for (let k = Math.max(0, i - WIN); k <= Math.min(total - 1, i + WIN); k++) { sum += raw[k]; n++; }
        bearing[i] = sum / n;
    }

    // ③ 逐帧 jumpTo 直接设相机（不用 easeTo：逐帧 easeTo 会不断中断重启动画 = 高频抖动）。
    //    位置按弧长定位并在相邻点间插值，保证匀速、无步进。
    let startBearing = null;
    let prevBrg = null;
    function frame(now) {
        if (startBearing === null) startBearing = map3d.getBearing();
        const t = Math.min(1, (now - startTime) / duration);
        const dist = t * totalLen;
        const i1 = idxAt(dist);
        const i0 = Math.max(0, i1 - 1);
        const seg = (cum[i1] - cum[i0]) || 1;
        const f = Math.max(0, Math.min(1, (dist - cum[i0]) / seg));
        const lat = pts[i0][0] + (pts[i1][0] - pts[i0][0]) * f;
        const lng = pts[i0][1] + (pts[i1][1] - pts[i0][1]) * f;
        let brg = bearing[i0] + (bearing[i1] - bearing[i0]) * f;

        // ④ 起步 1.2 秒内把镜头从当前朝向平滑转到航线朝向，避免开局甩头
        const blend = Math.min(1, (now - startTime) / 1200);
        if (blend < 1) {
            let diff = brg - startBearing;
            while (diff > 180) diff -= 360;
            while (diff < -180) diff += 360;
            brg = startBearing + diff * blend;
        }

        // ⑤ 转向限速：每帧最多转 ROT_MAX 度，杜绝急弯处镜头猛甩（防眩晕）
        const ROT_MAX = 0.3;
        if (prevBrg !== null) {
            let d = brg - prevBrg;
            while (d > 180) d -= 360;
            while (d < -180) d += 360;
            if (Math.abs(d) > ROT_MAX) brg = prevBrg + Math.sign(d) * ROT_MAX;
        }
        prevBrg = brg;

        if (window.__soldier3d) window.__soldier3d.setLngLat([lng, lat]);
        // 抬高机位、放缓俯仰，显著降低 3D 飞行的眩晕感
        map3d.jumpTo({ center: [lng, lat], bearing: brg, pitch: 50, zoom: 8.0 });

        if (t < 1) {
            map3dPlayTimer = requestAnimationFrame(frame);
        } else {
            map3dPlayTimer = null;
            routePlayActive = false;
            syncRouteButtons(-1);
        }
    }
    map3dPlayTimer = requestAnimationFrame(frame);
}

document.getElementById("toggle3DBtn").addEventListener("click", toggle3D);

// ========== 对话抽屉开关 ==========
function toggleChat(open) {
    const panel = document.querySelector(".chat-panel");
    if (!panel) return;
    const willOpen = (open !== undefined) ? open : !panel.classList.contains("chat-open");
    panel.classList.toggle("chat-open", willOpen);
    const btn = document.getElementById("openChatBtn");
    if (btn) {
        btn.style.borderColor = willOpen ? "#f5c842" : "";
        btn.style.color = willOpen ? "#f5c842" : "";
    }
    if (willOpen) { const inp = document.getElementById("queryInput"); if (inp) setTimeout(()=>inp.focus(), 300); }
}
document.getElementById("openChatBtn").addEventListener("click", () => toggleChat());
document.getElementById("chatCloseBtn").addEventListener("click", () => toggleChat(false));

// ========== 左侧代言人面板折叠箭头 ==========
document.getElementById("avatarPanelArrow").addEventListener("click", function () {
    const panel = document.getElementById("avatarPanel");
    const collapsed = !panel.classList.contains("open");
    if (collapsed) {
        panel.classList.add("open");
        this.classList.remove("collapsed");
        this.textContent = "◀";
    } else {
        panel.classList.remove("open");
        this.classList.add("collapsed");
        this.textContent = "▶";
    }
});

