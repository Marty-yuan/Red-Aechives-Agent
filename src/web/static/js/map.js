// ========== 初始化地图 ==========
map = L.map("map", { center: [25.5, 101.5], zoom: 7, attributionControl: false });
L.tileLayer("https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}", { subdomains: ["1","2","3","4"], maxZoom: 14 }).addTo(map);

// 客流热力专用图层容器：zIndex 350（低于路线/标记的 overlayPane 400），
// 热力光晕永远垫在长征路线与村寨标记下面，不再互相遮挡。
map.createPane("flowPane");
map.getPane("flowPane").style.zIndex = 350;

// ---- 图层容器：统一收纳散落的要素，供左侧「图层控制」面板开关 ----
// routeLayers 已在上方声明（每条长征路线一个；途径点归 waypointLayer，村寨归 villageLayer）
let waypointLayer = L.layerGroup().addTo(map);   // 长征途径站点（吸附到道路的小圆点）
let villageLayer = L.layerGroup().addTo(map);    // 村寨代言人标记

// ========== 战士标记 ==========
function createSoldierMarker(latlng) {
    const probe = new Image();
    probe.src = "/static/soldier.png";
    probe.onload = function() {
        const icon = L.divIcon({ className: "soldier-marker", html: `<img class="soldier-img" src="/static/soldier.png" alt="红军战士">`, iconSize: [80, 80], iconAnchor: [40, 72] });
        soldierMarker = L.marker(latlng, { icon: icon, zIndexOffset: 1000 }).addTo(map);
        soldierMarker.bindTooltip("红军战士", { direction: "top", offset: [0, -24] });
    };
    probe.onerror = function() {
        const icon = L.divIcon({ className: "soldier-marker", html: `<div class="soldier-badge">⭐</div>`, iconSize: [44, 44], iconAnchor: [22, 22] });
        soldierMarker = L.marker(latlng, { icon: icon, zIndexOffset: 1000 }).addTo(map);
        soldierMarker.bindTooltip("红军战士", { direction: "top", offset: [0, -20] });
    };
    return soldierMarker;
}

// ========== 加载两条路线 ==========
// 绘制某条路线的折线与方向箭头（使用当前 route.points，数据为详细路网）
function drawRouteGeometry(route, ri) {
    if (!map || !route || !Array.isArray(route.points) || route.points.length < 2) return;
    if (!routeLayers[ri]) routeLayers[ri] = L.layerGroup().addTo(map);
    const layer = routeLayers[ri];
    layer.clearLayers();

    // 白色描边增强层次，主线用军团颜色
    L.polyline(route.points, { color: "#000000", weight: 7, opacity: 0.18 }).addTo(layer);
    L.polyline(route.points, { color: route.color, weight: 4, opacity: 0.92 }).addTo(layer);

    // 沿路径均匀放置方向箭头
    const count = Math.min(6, route.points.length - 1);
    for (let a = 0; a < count; a++) {
        const idx = Math.max(0, Math.min(route.points.length - 2, Math.round((a + 0.5) * (route.points.length - 1) / count)));
        const p1 = map.project(route.points[idx], 10);
        const p2 = map.project(route.points[idx + 1], 10);
        const mid = p1.add(p2.subtract(p1).divideBy(2));
        const latlng = map.unproject(mid, 10);
        const angle = Math.atan2(p2.y - p1.y, p2.x - p1.x) * 180 / Math.PI;
        const arrowIcon = L.divIcon({ className: "route-arrow", html: `<div style="transform: rotate(${angle}deg); font-size:18px;">➤</div>`, iconSize: [20, 20], iconAnchor: [10, 10] });
        L.marker(latlng, { icon: arrowIcon, interactive: false }).addTo(layer);
    }
}

// ========== 详细途径点 ==========
// 每支队伍在云南境内的主要途经城镇，按顺序给出（仅用于在路线邻近处标注，不改变路线几何）。
const ROUTE_WAYPOINTS = [
    [ // 中央红军（1935年）
        { "name": "马龙",   "lat": 25.43, "lng": 103.58 },
        { "name": "嵩明",   "lat": 25.34, "lng": 103.03 },
        { "name": "昆明",   "lat": 25.04, "lng": 102.71 },
        { "name": "富民",   "lat": 25.22, "lng": 102.50 },
    ],
    [ // 红二、六军团（1936年）
        { "name": "昆明",   "lat": 25.04, "lng": 102.71 },
        { "name": "安宁",   "lat": 24.92, "lng": 102.48 },
        { "name": "禄丰",   "lat": 25.15, "lng": 102.08 },
        { "name": "大理",   "lat": 25.61, "lng": 100.27 },
        { "name": "鹤庆",   "lat": 26.56, "lng": 100.18 },
    ],
];

const WAYPOINT_MAX_OFFSET = 320;  // 城镇坐标距路线几何的最大投影像素（zoom10），超出则说明不在该路线走廊上，忽略
const WAYPOINT_REVEAL_PX = 24;    // 战士经过时触发显示的判据（zoom10 投影像素）

// 显示并高亮某个途径点
function revealWaypoint(w) {
    if (!w || w.passed) return;
    w.passed = true;
    w.marker.setStyle({ radius: 7, color: "#FFD700", fillColor: "#FFD700", fillOpacity: 1 });
    w.marker.unbindTooltip();
    w.marker.bindTooltip(w.name, { permanent: true, direction: "top", className: "waypoint-tip", offset: L.point(0, -8) });
    w.marker.openTooltip();
}

// 根据战士当前位置，显示附近尚未经过的途径点（“经过则展示”）
function revealNearbyWaypoints(routeIdx, latlng) {
    const list = routeWaypoints[routeIdx] || [];
    if (!list.length || !latlng) return;
    const p = map.project(latlng, 10);
    list.forEach(w => {
        if (w.passed) return;
        const q = map.project(w.latlng, 10);
        if (p.distanceTo(q) < WAYPOINT_REVEAL_PX) revealWaypoint(w);
    });
}

// 把某条途经道路线邻近的详细途经点落在地图上（吸附到最近道路点，保证在线上）
function createRouteWaypoints(route, ri) {
    const data = ROUTE_WAYPOINTS[ri] || [];
    const entries = [];
    data.forEach(w => {
        const ll = [w.lat, w.lng];
        const idx = nearestPointIndexOnRoute(ll, route.points);
        const snapped = route.points[idx];
        const p1 = map.project(ll, 10);
        const p2 = map.project(snapped, 10);
        if (p1.distanceTo(p2) > WAYPOINT_MAX_OFFSET) return;  // 距路线过远，忽略避免错位
        entries.push({ name: w.name, latlng: snapped, idx });
    });

    // 按路线前进顺序排序，并剔除顺序重复项，保证“经过”顺序正确
    entries.sort((a, b) => a.idx - b.idx);
    const final = [];
    entries.forEach(w => {
        if (final.length && w.idx <= final[final.length - 1].idx) return;
        final.push(w);
    });

    final.forEach(w => {
        const m = L.circleMarker(w.latlng, {
            radius: 5, color: "#fff", weight: 2, fillColor: route.color, fillOpacity: 0.9, interactive: true
        }).addTo(waypointLayer);
        m.bindTooltip(w.name, { permanent: false, direction: "top", className: "waypoint-tip", offset: L.point(0, -8) });
        m.on("click", () => revealWaypoint(w));
        w.marker = m;
        w.passed = false;
    });

    routeWaypoints[ri] = final;
}

// 一次显示某条路线上全部剩余途径点（播放/行走结束兜底）
function revealAllWaypoints(routeIdx) {
    (routeWaypoints[routeIdx] || []).forEach(w => revealWaypoint(w));
}

// ========== 左侧图层控制面板（长征路线可隐藏 / 可播放） ==========
const layerState = { route: {}, waypoint: true, village: true, flow: false };
const _eye = on => (on ? "👁" : "🚫");

function buildLayerPanel() {
    const list = document.getElementById("layerRouteList");
    if (!list) return;
    list.innerHTML = "";
    routes.forEach((route, ri) => {
        if (layerState.route[ri] === undefined) layerState.route[ri] = true;
        const row = document.createElement("div");
        row.className = "layer-row";
        row.dataset.routeRow = ri;
        row.title = "点击隐藏/显示该路线；点 ▶ 播放行军时序";
        row.innerHTML =
            '<i class="swatch" style="background:' + route.color + '"></i>' +
            '<span class="layer-label">' +
              '<span class="layer-name">' + route.name + '</span>' +
              '<span class="layer-sub">方向：' + (route.direction || '-') + '</span>' +
            '</span>' +
            '<span class="play-badge">▶</span>' +
            '<span class="eye">' + _eye(layerState.route[ri]) + '</span>';
        row.querySelector(".play-badge").addEventListener("click", e => {
            e.stopPropagation();
            playRoute(ri);
        });
        row.addEventListener("click", () => toggleRouteLayer(ri));
        list.appendChild(row);
        routeLegendBtns[ri] = row;   // 复用原有的播放高亮逻辑
    });

    const extra = [
        { key: "waypoint", name: "长征途径站点", sub: "路线上的行军要点" },
        { key: "village",  name: "村寨代言人标记", sub: "12 个红色村寨" },
        { key: "flow",     name: "景区客流热力", sub: "天气/节假日修正" }
    ];
    const box = document.getElementById("layerExtraList");
    if (!box) return;
    box.innerHTML = "";
    extra.forEach(item => {
        const row = document.createElement("div");
        row.className = "layer-row" + (layerState[item.key] ? "" : " off");
        row.dataset.layer = item.key;
        row.innerHTML =
            '<i class="swatch" style="background:#FFD700"></i>' +
            '<span class="layer-label"><span class="layer-name">' + item.name + '</span>' +
            '<span class="layer-sub">' + item.sub + '</span></span>' +
            '<span class="eye">' + _eye(layerState[item.key]) + '</span>';
        row.addEventListener("click", () => toggleExtraLayer(item.key, row));
        box.appendChild(row);
    });
}

function _paintRouteRow(ri) {
    const row = document.querySelector('[data-route-row="' + ri + '"]');
    if (!row) return;
    row.classList.toggle("off", !layerState.route[ri]);
    const eye = row.querySelector(".eye");
    if (eye) eye.textContent = _eye(layerState.route[ri]);
}

function toggleRouteLayer(ri) {
    const on = !layerState.route[ri];
    layerState.route[ri] = on;
    const layer = routeLayers[ri];
    if (layer) { on ? layer.addTo(map) : map.removeLayer(layer); }
    // 该路线的途径点随之显隐（仍受「长征途径站点」总开关约束）
    (routeWaypoints[ri] || []).forEach(w => {
        if (!w.marker) return;
        if (on && layerState.waypoint) waypointLayer.addLayer(w.marker);
        else waypointLayer.removeLayer(w.marker);
    });
    _paintRouteRow(ri);
}

function toggleExtraLayer(key, row) {
    const on = !layerState[key];
    layerState[key] = on;
    if (key === "village") {
        on ? villageLayer.addTo(map) : map.removeLayer(villageLayer);
    } else if (key === "waypoint") {
        Object.keys(routeWaypoints).forEach(ri => {
            if (!layerState.route[ri]) return;   // 路线本身已隐藏的保持隐藏
            (routeWaypoints[ri] || []).forEach(w => {
                if (!w.marker) return;
                on ? waypointLayer.addLayer(w.marker) : waypointLayer.removeLayer(w.marker);
            });
        });
    } else if (key === "flow") {
        toggleFlow(on);   // 复用原有热力面板开关
    }
    row.classList.toggle("off", !on);
    const eye = row.querySelector(".eye");
    if (eye) eye.textContent = _eye(on);
}

fetch("/api/routes").then(r => r.json()).then(data => {
    routes = data.routes;
    const allPoints = [];

    routes.forEach((route, ri) => {
        allPoints.push(...route.points);

        // 绘制详细路网（真实公路走向，不再只是直线）
        drawRouteGeometry(route, ri);
        // 标注详细途径点（吸附到道路上）
        createRouteWaypoints(route, ri);
    });

    // 左侧图层面板（长征路线在此列出，可隐藏 / 可播放）
    buildLayerPanel();

    // 地图视野
    map.fitBounds(L.polyline(allPoints).getBounds().pad(0.15));
    // 战士初始位置
    createSoldierMarker(routes[0].points[0]);
    soldierPos = { route: 0, idx: 0 };
}).catch(() => showToast("路线数据加载失败，请检查后端服务", "error"));

// ========== 加载村寨 ==========
// 按长征时间线排序的村寨顺序
const VILLAGE_ORDER = ["扎西", "宣威", "曲靖", "寻甸柯渡", "寻甸", "柯渡", "楚雄", "禄劝", "皎平渡", "丽江", "石鼓", "威信"];
fetch("/api/villages").then(r => r.json()).then(villages => {
    window.__villagesData = villages;  // 缓存供 3D 地图使用
    const legend = document.getElementById("legendList");
    // 按长征时间线排序
    villages.sort((a, b) => {
        const idxA = VILLAGE_ORDER.indexOf(a.name);
        const idxB = VILLAGE_ORDER.indexOf(b.name);
        if (idxA === -1 && idxB === -1) return 0;
        if (idxA === -1) return 1;
        if (idxB === -1) return -1;
        return idxA - idxB;
    });
    villages.forEach(v => {
        if (!v.lat || !v.lng) return;
        // 找到村寨所属路线
        let armyIdx = 0;
        routes.forEach((route, ri) => {
            route.points.forEach(p => {
                if (Math.abs(p[0] - v.lat) < 0.05 && Math.abs(p[1] - v.lng) < 0.05) {
                    armyIdx = ri;
                }
            });
        });
        villageArmy[v.name] = armyIdx;
        villageAvatars[v.name] = v.avatar || "/static/soldier.png";
        villageVoiceGenders[v.name] = v.voice_gender || "female";
        villageCoords[v.name] = { lat: v.lat, lng: v.lng };

        let marker = L.circleMarker([v.lat, v.lng], {
            radius: 10, fillColor: "#C41E3A", color: "#FFD700", weight: 2, fillOpacity: 0.85
        }).addTo(villageLayer);
        // 弹窗放在下方，避免挡住战士
        marker.bindPopup(`<b>${v.name}</b><br>${v.event} · ${v.year}<br>${v.army}`, { className: "village-popup", offset: L.point(0, -70), autoPan: false, autoClose: false, closeButton: false });
        marker.on("click", () => selectVillage(v.name));
        // 悬停交互：放大发光+预览卡片
        marker.on("mouseover", function() {
            this.setStyle({ radius: 14, fillOpacity: 1, weight: 3, color: "#FFFFFF" });
            this.bindTooltip(`<div style="font-weight:bold;color:#F5C842;font-size:13px;">${v.name}</div><div style="font-size:11px;color:#e0e0e0;margin-top:2px;">${v.event}</div><div style="font-size:10px;color:#94A3B8;margin-top:2px;">${v.year} · ${v.army}</div>`, {
                direction: "top",
                offset: [0, -10],
                className: "village-hover-tooltip",
                permanent: false
            }).openTooltip();
        });
        marker.on("mouseout", function() {
            this.setStyle({ radius: 10, fillOpacity: 0.85, weight: 2, color: "#FFD700" });
            this.closeTooltip();
        });
        villageMarkers[v.name] = marker;

        let item = document.createElement("div");
        item.className = "legend-item";
        item.innerHTML = `<span class="dot"></span><span>${v.name}<br><small style="opacity:0.5">${v.event} · ${v.year}</small></span>`;
        item.onclick = () => selectVillage(v.name);
        legend.appendChild(item);
    });
}).catch(() => showToast("村寨数据加载失败，请检查后端服务", "error"));

// ========== 加载时间轴（按路线分组，播放时联动） ==========
const TIMELINE_ROUTE_META = [
    { name: "中央红军", year: "1935", color: "#C41E3A" },
    { name: "红二、六军团", year: "1936", color: "#E67E22" },
];

// 依据部队归属把时间轴事件映射到路线（0=中央红军，1=红二、六军团）
function timelineRouteForArmy(army) {
    if (/红二|六军团/.test(army || "") && !/中央红军/.test(army || "")) return 1;
    return 0;
}

function renderTimelineEvent(ev) {
    const el = document.createElement("div");
    el.className = "tl-event";
    el.setAttribute("data-date", ev.date);
    el.setAttribute("data-label", ev.label);
    el.setAttribute("data-army", ev.army);
    el.setAttribute("data-village", ev.village || "");
    el.setAttribute("data-route", String(timelineRouteForArmy(ev.army)));
    el.setAttribute("data-desc", ev.desc || "点击查看详情");
    el.innerHTML = `
        <div class="tl-dot"></div>
        <div class="tl-date">${ev.date}</div>
        <div class="tl-label">${ev.label}</div>
        <div class="tl-army">${ev.army}</div>`;
    el.title = ev.desc;
    el.onclick = () => selectVillage(ev.village);
    el.addEventListener("mouseenter", showTlTooltip);
    el.addEventListener("mouseleave", hideTlTooltip);
    return el;
}

fetch("/api/timeline").then(r => r.json()).then(events => {
    timelineEvents = events || [];
    const track = document.getElementById("tlTrack");
    track.innerHTML = "";
    timelineItems = [];
    timelineGroupEls = [];

    // 按路线分组，两条路线在时间轴上物理分开
    TIMELINE_ROUTE_META.forEach((meta, ri) => {
        const group = timelineEvents.filter(ev => timelineRouteForArmy(ev.army) === ri);
        if (group.length === 0) return;

        const label = document.createElement("div");
        label.className = "tl-group-label";
        label.setAttribute("data-route", String(ri));
        label.style.color = meta.color;
        label.style.borderColor = meta.color;
        label.style.background = "linear-gradient(135deg, " + meta.color + "4d 0%, " + meta.color + "26 100%)";
        label.innerHTML = `<span class="play-badge">▶</span><span>${meta.name} · ${meta.year}</span>`;
        label.title = "点击播放 " + meta.name + " 的行军时序";
        label.onclick = () => playRoute(ri);
        track.appendChild(label);
        timelineGroupEls[ri] = label;

        group.forEach(ev => {
            const el = renderTimelineEvent(ev);
            track.appendChild(el);
            timelineItems.push({ el, route: ri, village: ev.village || "", fraction: 1 });
        });
    });
}).catch(() => showToast("时间轴数据加载失败", "error"));

