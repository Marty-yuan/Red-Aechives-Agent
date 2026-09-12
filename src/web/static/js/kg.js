// ========== ??????? ==========
let kgNetwork = null;

function openKnowledgeGraph() {
    document.getElementById("kgOverlay").style.display = "flex";
    if (!kgRaw) {
        loadKnowledgeGraph();          // 首次打开：拉数据并按当前模式渲染
    } else if (kgMode === "3d") {
        if (!kgGraph3D) kgRefresh(); else adapt3DSize();   // 二次打开：3D 画布跟随尺寸
    }
}

function closeKnowledgeGraph() {
    document.getElementById("kgOverlay").style.display = "none";
}

// ===== 知识图谱：类型元数据（配色/形状/中文） =====
const KG_TYPE_META = {
    person:       { label: "人物", color: "#C41E3A", shape: "dot" },
    location:     { label: "地点", color: "#3b82f6", shape: "dot" },
    event:        { label: "事件", color: "#E67E22", shape: "star" },
    army:         { label: "部队", color: "#27ae60", shape: "diamond" },
    organization: { label: "组织", color: "#9b59b6", shape: "box" },
    document:     { label: "文献", color: "#f5c842", shape: "box" },
    other:        { label: "其他", color: "#6b7280", shape: "dot" }
};
let kgRaw = null, kgDegrees = {}, kgFilterType = "all", kgShowIso = false, kgMode = "2d";
let kgNodesDS = null, kgEdgesDS = null;

// #hex → rgba（发光用）
function kgGlow(hex, a) {
    const m = hex.replace("#", "");
    return "rgba(" + parseInt(m.substr(0, 2), 16) + "," + parseInt(m.substr(2, 2), 16) + "," + parseInt(m.substr(4, 2), 16) + "," + a + ")";
}
// vis-network 9.x 的字符串 title 会被按纯文本渲染，必须传 DOM 元素才能出富文本
function kgNodeTitle(n, deg, typeLabel) {
    const div = document.createElement("div");
    div.style.maxWidth = "280px";
    div.innerHTML = '<b style="color:#f5c842;font-size:13px;">' + escapeHtml(n.name || "") + '</b>' +
        '<div style="color:#7fe7ff;font-size:11px;margin:3px 0;">◈ ' + typeLabel + ' · ' + deg + ' 条关系</div>' +
        '<div style="color:#cbd5e1;font-size:11px;line-height:1.5;">' + escapeHtml(n.description || "") + '</div>';
    return div;
}
function kgEdgeTitle(label) {
    const div = document.createElement("div");
    div.innerHTML = '<span style="color:#7fe7ff;">⇢ ' + escapeHtml(label || "关联") + '</span>';
    return div;
}

function kgRenderChips() {
    const box = document.getElementById("kgTypeChips");
    if (!box || !kgRaw) return;
    const counts = {};
    (kgRaw.nodes || []).forEach(n => {
        const t = n.type || "other";
        counts[t] = (counts[t] || 0) + 1;
    });
    const mk = (key, label, color, count) =>
        '<button class="kg-chip' + (kgFilterType === key ? " active" : "") + '" data-type="' + key + '">' +
        '<i style="background:' + color + '"></i>' + label + ' <b>' + count + '</b></button>';
    let html = mk("all", "全部", "#f5c842", (kgRaw.nodes || []).length);
    Object.entries(KG_TYPE_META).forEach(([k, m]) => {
        if (counts[k]) html += mk(k, m.label, m.color, counts[k]);
    });
    box.innerHTML = html;
    box.querySelectorAll(".kg-chip").forEach(ch =>
        ch.addEventListener("click", () => { kgFilterType = ch.dataset.type; kgRenderChips(); kgRefresh(); }));
}

// 统一的筛选结果（类型过滤 + 孤立节点开关），2D 与 3D 共用
function kgFilteredData() {
    if (!kgRaw) return { nodes: [], edges: [], ids: new Set() };
    const nodes = (kgRaw.nodes || []).filter(n => {
        const t = n.type || "other";
        if (kgFilterType !== "all" && t !== kgFilterType) return false;
        if ((kgDegrees[n.id] || 0) === 0 && !kgShowIso) return false;
        return true;
    });
    const ids = new Set(nodes.map(n => n.id));
    const edges = (kgRaw.edges || []).filter(e => ids.has(e.source) && ids.has(e.target));
    return { nodes: nodes, edges: edges, ids: ids };
}

// ===== 三维模式（3d-force-graph） =====
let kgGraph3D = null;
const KG_REDUCED_MOTION = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function kgBuild3D() {
    const container = document.getElementById("kgNetwork");
    if (typeof ForceGraph3D === "undefined") {
        container.innerHTML = '<div class="kg-loading">3D 库未加载成功（需联网 + WebGL 支持），请切回 2D</div>';
        return;
    }
    const { nodes: list, edges: es } = kgFilteredData();
    const data = {
        nodes: list.map(n => {
            const deg = kgDegrees[n.id] || 0;
            const meta = KG_TYPE_META[n.type || "other"] || KG_TYPE_META.other;
            return {
                id: n.id, name: n.name, typeLabel: meta.label, deg: deg,
                color: meta.color, desc: n.description || "",
                val: 0.6 + Math.min(deg, 26) * 0.16      // 度数决定球体大小
            };
        }),
        links: es.map(e => ({ source: e.source, target: e.target, name: e.label || e.relation || "关联" }))
    };

    if (kgGraph3D) { try { if (kgGraph3D._destructor) kgGraph3D._destructor(); } catch (e) {} kgGraph3D = null; }
    container.innerHTML = "";
    {
        kgGraph3D = ForceGraph3D()(container)
            .backgroundColor("#05080F")
            .showNavInfo(false)
            .nodeRelSize(3.4)
            .nodeVal("val")
            .nodeColor("color")
            .nodeOpacity(0.92)
            .nodeResolution(12)
            .linkColor(() => "rgba(110,180,255,0.28)")
            .linkWidth(0.5)
            .linkOpacity(0.35)
            .linkDirectionalArrowLength(2.6)
            .linkDirectionalArrowRelPos(1)
            .nodeLabel(n =>
                '<div style="background:rgba(8,12,20,0.94);padding:6px 9px;border-radius:6px;border:1px solid rgba(127,231,255,0.35);">' +
                '<b style="color:#f5c842">' + escapeHtml(n.name) + '</b>' +
                '<div style="color:#7fe7ff;font-size:11px;margin:2px 0;">◈ ' + n.typeLabel + ' · ' + n.deg + ' 条关系</div>' +
                '<div style="color:#cbd5e1;font-size:11px;max-width:240px">' + escapeHtml(n.desc) + '</div></div>')
            .linkLabel(l => '<div style="background:rgba(8,12,20,0.94);padding:3px 7px;border-radius:5px;color:#7fe7ff;font-size:11px;">⇢ ' + escapeHtml(l.name) + '</div>');

        // 中文标签（SpriteText）；度数越高字越大，低度节点小字不喧宾夺主
        if (typeof SpriteText !== "undefined") {
            const showAll = kgFilterType !== "all" || list.length <= 80;
            kgGraph3D
                .nodeThreeObjectExtend(true)
                .nodeThreeObject(n => {
                    if (!showAll && n.deg < 3) return false;
                    const h = 2.8 + Math.min(n.deg, 20) * 0.2;
                    const sprite = new SpriteText(n.name);
                    sprite.color = n.deg >= 10 ? "#7fe7ff" : "#cfe3ff";
                    sprite.textHeight = h;
                    sprite.material.depthWrite = false;
                    // 标签抬到球体上方，避免与节点球体互相遮挡
                    const r = 3.4 * Math.pow(n.val, 1 / 3);
                    sprite.position.set(0, r + h * 0.75, 0);
                    return sprite;
                });
        }
        // 缓慢自转，演示时更有科技感（1.73+ 的 controls 已换成 TrackballControls，
        // 不再有 autoRotate 属性，改为在引擎 tick 中让相机每帧绕目标点 Y 轴微转）
        try {
            let kgSpinLast = 0;
            kgGraph3D.onEngineTick(() => {
                if (KG_REDUCED_MOTION) return;
                const cam = kgGraph3D.camera(), ctl = kgGraph3D.controls();
                if (!cam || !ctl) return;
                const now = performance.now();
                const dt = kgSpinLast ? Math.min((now - kgSpinLast) / 1000, 0.1) : 0;
                kgSpinLast = now;
                const t = ctl.target;
                const dx = cam.position.x - t.x, dz = cam.position.z - t.z;
                const ang = 0.18 * dt; // 约 35 秒一圈
                const cs = Math.cos(ang), sn = Math.sin(ang);
                cam.position.set(t.x + dx * cs - dz * sn, cam.position.y, t.z + dx * sn + dz * cs);
            });
        } catch (e) {}
    }
    // 弱向心引力：把断连小岛拉向主体，避免取景被外围孤点撑远
    try {
        kgGraph3D.d3Force("pull", alpha => {
            for (const n of kgGraph3D.graphData().nodes) {
                const g = 0.03 * alpha;
                n.vx -= (n.x || 0) * g; n.vy -= (n.y || 0) * g; n.vz -= (n.z || 0) * g;
            }
        });
    } catch (e) {}
    kgGraph3D.graphData(data);
    // 收缩斥力作用半径，让互不相连的小岛不至于被斥力推得四散，整体取景更紧凑
    try { kgGraph3D.d3Force("charge").strength(-16).distanceMax(420); } catch (e) {}
    adapt3DSize();
    setTimeout(() => { if (kgMode === "3d" && kgGraph3D) { try { kgGraph3D.zoomToFit(900, 60); } catch (e) {} } }, 700);
    setTimeout(() => { if (kgMode === "3d" && kgGraph3D) { try { kgGraph3D.zoomToFit(1200, 60); } catch (e) {} } }, 4500);

    const stat = document.getElementById("kgStat");
    if (stat) stat.textContent = "3D · " + data.nodes.length + " 节点 / " + data.links.length + " 关系";
}

// 2D / 3D 切换（销毁旧实例，避免容器冲突）
function kgSwitchMode(mode) {
    const container = document.getElementById("kgNetwork");
    if (kgNetwork) { try { kgNetwork.destroy(); } catch (e) {} kgNetwork = null; kgNodesDS = null; kgEdgesDS = null; }
    if (kgGraph3D) { try { if (kgGraph3D._destructor) kgGraph3D._destructor(); } catch (e) {} kgGraph3D = null; }
    container.innerHTML = "";
    kgMode = mode;
    document.querySelectorAll("[data-kg-mode]").forEach(b =>
        b.classList.toggle("active", b.dataset.kgMode === mode));
    if (mode === "3d") kgBuild3D(); else kgBuild();
}

// 按当前模式重建（筛选项变化时调用）
function kgRefresh() {
    if (kgMode === "3d") kgBuild3D(); else kgBuild();
}

// 3D 画布跟随容器尺寸（弹窗打开时容器才有真实宽高）
function adapt3DSize() {
    if (!kgGraph3D) return;
    const c = document.getElementById("kgNetwork");
    if (!c) return;
    try { kgGraph3D.width(c.clientWidth || 900).height(c.clientHeight || 560); } catch (e) {}
}
window.addEventListener("resize", adapt3DSize);

function kgBuild() {
    const container = document.getElementById("kgNetwork");
    if (!kgRaw || typeof vis === "undefined") return;
    if (!kgDegrees._done) {
        (kgRaw.edges || []).forEach(e => {
            kgDegrees[e.source] = (kgDegrees[e.source] || 0) + 1;
            kgDegrees[e.target] = (kgDegrees[e.target] || 0) + 1;
        });
        kgDegrees._done = true;
    }
    // 过滤：类型 + 孤立节点（2D / 3D 共用同一份筛选结果）
    const { nodes: keptNodes, edges: keptEdges, ids: keep } = kgFilteredData();
    const nodesData = keptNodes.map(n => {
        const t = n.type || "other";
        const meta = KG_TYPE_META[t] || KG_TYPE_META.other;
        const deg = kgDegrees[n.id] || 0;
        const baseSize = 7 + Math.min(deg, 26) * 1.15;
        const isHub = deg >= 10;
        // 「全部」视图节点多，只给枢纽常显标签；筛选单类型时节点少，名称全部显示
        const showAllLabels = kgFilterType !== "all" || keep.size <= 80;
        return {
            id: n.id,
            label: (showAllLabels || deg >= 3) ? n.name : "",
            group: t,
            size: baseSize,
            shape: meta.shape,
            color: {
                background: meta.color,
                border: isHub ? "#7fe7ff" : kgGlow(meta.color, 0.9),
                highlight: { background: meta.color, border: "#7fe7ff" },
                hover: { background: meta.color, border: "#7fe7ff" }
            },
            // 同色光晕 = 科技感发光体
            shadow: {
                enabled: true,
                color: kgGlow(meta.color, isHub ? 0.85 : 0.5),
                size: 12 + Math.min(deg, 20) * 0.9,
                x: 0, y: 0
            },
            // hover / 选中时"充能"：放大 + 青色光环 + 光晕爆闪
            chosen: {
                node: function (values) {
                    values.size = baseSize * 1.35;
                    values.borderWidth = 2.2;
                    values.borderColor = "#7fe7ff";
                    values.shadow = { enabled: true, color: "rgba(127,231,255,0.95)", size: 30, x: 0, y: 0 };
                }
            },
            font: { size: 12, color: "#cfe3ff", face: "Microsoft YaHei", strokeWidth: 3, strokeColor: "rgba(5,10,20,0.9)" },
            borderWidth: 1.4,
            title: kgNodeTitle(n, deg, meta.label)
        };
    });
    const edgesData = keptEdges.map(e => ({
        from: e.source,
        to: e.target,
        arrows: { to: { enabled: true, scaleFactor: 0.4 } },
        color: { color: "rgba(110,180,255,0.20)", highlight: "#7fe7ff", hover: "rgba(127,231,255,0.8)" },
        hoverWidth: 1.6,
        selectionWidth: 1.8,
        width: 1,
        title: kgEdgeTitle(e.label || e.relation || "关联")   // 关系名悬停显示，画面不被文字糊满
    }));

    const options = {
        autoResize: true,
        nodes: {
            shape: "dot",
            borderWidth: 1.4,
            shadow: { enabled: true, color: "rgba(0,0,0,0.5)", size: 8, x: 0, y: 2 }
        },
        edges: { smooth: { enabled: false } },   // 直线边 + 低透明度，比 dynamic 曲线干净得多
        groups: {},
        physics: {
            solver: "barnesHut",
            barnesHut: {
                gravitationalConstant: -2800,
                centralGravity: 0.14,
                springLength: 120,
                springConstant: 0.06,
                damping: 0.42,
                avoidOverlap: 0.25
            },
            stabilization: { iterations: 300, fit: true }
        },
        interaction: {
            hover: true,
            tooltipDelay: 140,
            hoverConnectedEdges: true,
            selectConnectedEdges: true,
            keyboard: false
        }
    };

    if (!kgNetwork) {
        kgNodesDS = new vis.DataSet(nodesData);
        kgEdgesDS = new vis.DataSet(edgesData);
        kgNetwork = new vis.Network(container, { nodes: kgNodesDS, edges: kgEdgesDS }, options);
        kgNetwork.once("stabilizationIterationsDone", () => {
            kgNetwork.setOptions({ physics: { enabled: false } });
        });
    } else {
        kgNodesDS.clear(); kgNodesDS.add(nodesData);
        kgEdgesDS.clear(); kgEdgesDS.add(edgesData);
        kgNetwork.setOptions({ physics: { enabled: true } });
        kgNetwork.once("stabilizationIterationsDone", () => {
            kgNetwork.setOptions({ physics: { enabled: false } });
        });
        kgNetwork.fit();
    }
    const stat = document.getElementById("kgStat");
    if (stat) stat.textContent = "已显示 " + nodesData.length + " 节点 / " + edgesData.length + " 关系";
}

function loadKnowledgeGraph() {
    const container = document.getElementById("kgNetwork");
    if (typeof vis === "undefined") {
        container.innerHTML = '<div class="kg-loading">图谱库加载失败，请检查网络</div>';
        return;
    }

    fetch("/api/knowledge_graph").then(r => r.json()).then(data => {
        kgRaw = data;
        kgRenderChips();
        kgRefresh();
    }).catch(() => {
        container.innerHTML = '<div class="kg-loading">图谱加载失败，请检查后端服务</div>';
    });
}

document.getElementById("kgOpenBtn").addEventListener("click", openKnowledgeGraph);
document.getElementById("kgIsoToggle").addEventListener("change", e => {
    kgShowIso = e.target.checked;
    kgRefresh();
});
// 2D / 3D 模式切换
document.querySelectorAll("#kgModeSwitch [data-kg-mode]").forEach(b => {
    b.addEventListener("click", () => {
        if (b.dataset.kgMode === kgMode) return;
        kgSwitchMode(b.dataset.kgMode);
    });
});
