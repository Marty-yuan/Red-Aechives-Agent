// ========== 客流热力（治理层 L2） ==========
let flowLayer = null;
let flowActive = false;
let flowLastParams = null;
let flowLastSnapshot = null;

async function loadFlowHeatmap(params) {
    flowLastParams = params || null;
    const qs = params ? "?" + new URLSearchParams(params).toString() : "";
    try {
        const resp = await fetch("/api/governance/heatmap" + qs);
        if (!resp.ok) return;
        const snap = await resp.json();
        flowLastSnapshot = snap;
        renderFlowHeatmap(snap);
        renderFlowPanel(snap, params);
    } catch (e) { console.warn("客流数据加载失败", e); }
}

function renderFlowHeatmap(snap) {
    if (!flowLayer) flowLayer = L.layerGroup().addTo(map);
    flowLayer.clearLayers();
    const maxVal = Math.max(1, ...snap.points.map(p => p.value));
    snap.points.forEach(p => {
        const coreR = 10 + 22 * (p.value / maxVal);
        // 三层热力光晕，全部绘制在 flowPane（路线层之下）：
        //   外圈：大而淡的扩散晕  →  中圈：主体色块  →  核心点：小而清晰的交互标记
        // 外/中圈 interactive:false，点击会穿透到下面的路线与村寨标记。
        L.circleMarker([p.lat, p.lng], {
            radius: coreR + 16, pane: "flowPane",
            stroke: false, fillColor: p.color, fillOpacity: 0.15,
            interactive: false
        }).addTo(flowLayer);
        L.circleMarker([p.lat, p.lng], {
            radius: coreR, pane: "flowPane",
            stroke: false, fillColor: p.color, fillOpacity: 0.28,
            interactive: false
        }).addTo(flowLayer);
        const marker = L.circleMarker([p.lat, p.lng], {
            radius: 5.5, color: "#ffffff", weight: 1.2, opacity: 0.9,
            fillColor: p.color, fillOpacity: 0.95
        });
        marker.bindPopup(buildFlowPopup(p));
        marker.bindTooltip(p.name + " · " + p.level_label + " " + p.value + "人", { direction: "top" });
        marker.addTo(flowLayer);
    });
}

function buildFlowPopup(p) {
    const pct = Math.round(p.load_ratio * 100);
    const w = p.weather;
    const weatherRow = w
        ? '<div class="row"><span>实时天气</span><b>' + (w.icon_emoji || "🌡️") + ' ' +
          escapeHtml(w.text || "") + ' ' + escapeHtml(String(w.temp != null ? w.temp : "--")) + '°C</b></div>'
        : '';
    return '<div class="flow-popup">' +
        '<b style="color:#f5c842">' + p.name + '</b>（' + p.city + '）' +
        weatherRow +
        '<div class="row"><span>当前客流</span><b>' + p.value + ' 人次</b></div>' +
        '<div class="row"><span>承载率</span><b style="color:' + p.color + '">' + pct + '% · ' + p.level_label + '</b></div>' +
        '<div class="row"><span>最大承载</span><span>' + p.capacity + ' 人</span></div>' +
        '<div id="flowCurveBox_' + p.name + '"></div>' +
        '<div style="margin-top:4px;"><a href="javascript:loadFlowCurve(\'' + p.name + '\')">▸ 查看 24 小时曲线</a></div>' +
        '</div>';
}

async function loadFlowCurve(name) {
    const box = document.getElementById("flowCurveBox_" + name);
    if (!box || box.dataset.loaded) return;
    box.dataset.loaded = "1";
    try {
        const resp = await fetch("/api/governance/flow-curve?village=" + encodeURIComponent(name));
        if (!resp.ok) return;
        const c = await resp.json();
        const max = Math.max(1, c.peak_value);
        const nowHour = new Date().getHours();
        const bars = c.series.map(s => {
            const h = Math.max(2, Math.round(46 * s.value / max));
            const outline = s.hour === nowHour ? "outline:1px solid #fff;" : "";
            return '<i style="height:' + h + 'px;' + outline + '" title="' + s.hour + '时 ' + s.value + '人"></i>';
        }).join("");
        box.innerHTML = '<div style="margin-top:6px;font-size:10px;color:#9ca3af;">24h 曲线（峰值 ' +
            c.peak_hour + '时 ' + c.peak_value + '人，白框为当前小时）</div><div class="flow-curve-bars">' + bars + '</div>';
    } catch (e) { console.warn("曲线加载失败", e); }
}

function renderFlowPanel(snap, params) {
    document.getElementById("flowTotal").textContent = snap.total_visitors;
    document.getElementById("flowAlertNum").textContent = snap.alert_sites.length;
    const alertBox = document.getElementById("flowAlertBox");
    if (snap.alert_sites.length) {
        alertBox.style.display = "block";
        alertBox.textContent = "⚠ " + snap.alert_sites.join("、") + " 达到预警阈值（承载率≥90%），建议启动客流分流";
    } else {
        alertBox.style.display = "none";
    }
    // 日期类型 + 天气接入状态
    document.getElementById("flowDayType").textContent = "📅 " + (snap.day_type_label || "工作日");
    var wStatus = snap.weather_status || (snap.weather_available ? "ok" : "api_error");
    document.getElementById("flowWeatherStatus").textContent =
        wStatus === "ok" ? "🌤 已接入实时天气（客流已按天气/节假日修正）"
        : wStatus === "no_key" ? "🌡 天气未接入（未配置 QWEATHER_API_KEY，客流为纯仿真）"
        : "⚠ 天气接口调用失败（请检查 QWEATHER_BASE_URL/API_KEY，客流为纯仿真）";
    document.getElementById("flowNote").textContent = "* " + (snap.data_note || "仿真演示数据");
    const label = document.getElementById("flowHourLabel");
    if (!params) label.textContent = "实时";
    else if (params.slot) label.textContent = ({morning: "上午均值", afternoon: "下午均值", evening: "傍晚均值"})[params.slot];
    else label.textContent = params.hour + ":00 回放";
    const sorted = snap.points.slice().sort((a, b) => b.value - a.value);
    document.getElementById("flowSiteList").innerHTML = sorted.map(p => {
        const w = p.weather;
        const weatherLine = w
            ? '<div class="flow-site-weather">' + (w.icon_emoji || "🌡️") + ' ' + escapeHtml(w.text || "") +
              ' <b>' + escapeHtml(String(w.temp != null ? w.temp : "--")) + '°C</b>' +
              (w.wind_dir ? ' · ' + escapeHtml(w.wind_dir) + (w.wind_scale ? w.wind_scale + '级' : '') : '') +
              (w.humidity ? ' · 湿度' + escapeHtml(String(w.humidity)) + '%' : '') + '</div>'
            : '<div class="flow-site-weather">🌡 天气暂不可用</div>';
        return '<div class="flow-site-row" onclick="map.flyTo([' + p.lat + ',' + p.lng + '],9)">' +
            '<span style="flex:1;min-width:0;">' +
            '<span class="flow-site-name"><i class="flow-dot" style="background:' + p.color + '"></i>' + p.name + '</span>' +
            weatherLine + '</span>' +
            '<span style="text-align:right;white-space:nowrap;"><b>' + p.value + '</b> <span class="flow-badge" style="background:' + p.color + '22;color:' + p.color + '">' +
            p.level_label + '</span></span></div>';
    }).join("");
}

function toggleFlow(force) {
    flowActive = (force !== undefined) ? force : !flowActive;
    layerState.flow = flowActive;   // 与左侧图层面板保持同步
    document.getElementById("flowPanel").classList.toggle("active", flowActive);
    document.getElementById("flowToggleBtn").style.borderColor = flowActive ? "#f5c842" : "";
    const row = document.querySelector('[data-layer="flow"]');
    if (row) {
        row.classList.toggle("off", !flowActive);
        const eye = row.querySelector(".eye");
        if (eye) eye.textContent = _eye(flowActive);
    }
    if (flowActive) {
        collapseLegend();   // 右上角互斥：客流面板打开时收起图例，避免重叠
        if (!flowLastSnapshot) loadFlowHeatmap(null);
    } else if (flowLayer) {
        flowLayer.clearLayers();
    }
}

document.getElementById("layerCollapseBtn").addEventListener("click", function () {
    const panel = document.getElementById("layerPanel");
    const collapsed = panel.classList.toggle("collapsed");
    this.textContent = collapsed ? "＋" : "－";
    this.title = collapsed ? "展开面板" : "收起面板";
});
document.getElementById("flowToggleBtn").addEventListener("click", () => toggleFlow());
document.getElementById("flowCloseBtn").addEventListener("click", () => toggleFlow(false));
document.getElementById("flowHourSlider").addEventListener("input", e => loadFlowHeatmap({hour: e.target.value}));
document.querySelectorAll("[data-flow-slot]").forEach(btn =>
    btn.addEventListener("click", () => loadFlowHeatmap({slot: btn.dataset.flowSlot})));
document.querySelector('[data-flow-time="realtime"]').addEventListener("click", () => {
    document.getElementById("flowHourSlider").value = new Date().getHours();
    loadFlowHeatmap(null);
});
document.getElementById("kgCloseBtn").addEventListener("click", closeKnowledgeGraph);
document.getElementById("kgOverlay").addEventListener("click", function (e) {
    if (e.target && e.target.id === "kgOverlay") closeKnowledgeGraph();
});

document.getElementById("authBtn").addEventListener("click", openAuth);

