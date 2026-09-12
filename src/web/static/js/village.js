// ========== 选择村寨 ==========
function selectVillage(name) {
    currentVillage = name;
    currentVillageVoiceGender = villageVoiceGenders[name] || "female";
    setVillageAvatar(name);
    document.getElementById("chatName").textContent = name + " 代言人";
    document.getElementById("chatMeta").textContent = "战士正在前往...";

    // 高亮
    Object.values(villageMarkers).forEach(m => m.setStyle({ fillColor: "#C41E3A" }));
    if (villageMarkers[name]) {
        villageMarkers[name].setStyle({ fillColor: "#FFD700" });
        const latlng = villageMarkers[name].getLatLng();
        // 放大到更近的缩放级别
        map.flyTo(latlng, 8, { duration: 1.1 });  // 10：保留周边路线和地名信息，不放得过大
        // 3D 模式下同步摄像机
        if (is3DMode && map3dReady && map3d) {
            map3d.flyTo({ center: [latlng.lng, latlng.lat], zoom: 9, pitch: 60, duration: 1500 });
        }
        const routeIdx = villageArmy[name] !== undefined ? villageArmy[name] : 0;
        walkSoldierTo([latlng.lat, latlng.lng], routeIdx);

        // Open the popup after map movement ends, so it never disappears on repeated clicks.
        map.once("moveend", () => {
            if (!villageMarkers[name]) return;
            Object.values(villageMarkers).forEach(m => m.closePopup());
            villageMarkers[name].openPopup();
        });
    }

    // 欢迎语 + 历史记忆
    loadVillageHistory(name);
    // 打开数字代言人左侧面板
    openAvatarPanel(name);
    // 设置对话框背景图
    setChatBackground(name);
    // 渲染快捷问题
    renderQuickQuestions(name);
    // 显示2D数字人角色
    showCharacter(name);
    // 选完村寨后收起图例，避免遮挡地图与代言人面板
    collapseLegend();
}

// 村寨对话框背景图映射
const CHAT_BG_MAP = {
    "皎平渡": "/static/chat_bg/jiaopingdu.jpg",
    "石鼓": "/static/chat_bg/shigu.jpg",
    "扎西": "/static/chat_bg/zaxi.jpg",
    "威信": "/static/chat_bg/zaxi.jpg",
    "寻甸柯渡": "/static/chat_bg/xundian_kedu.jpg",
    "寻甸": "/static/chat_bg/xundian_kedu.jpg",
    "柯渡": "/static/chat_bg/xundian_kedu.jpg",
    "楚雄": "/static/chat_bg/chuxiong.jpg",
    "曲靖": "/static/chat_bg/qujing.jpg",
    "丽江": "/static/chat_bg/lijiang.jpg",
    "宣威": "/static/chat_bg/xuanwei.jpg",
    "禄劝": "/static/chat_bg/luquan.jpg"
};

// 快捷问题列表
const QUICK_QUESTIONS = [
    "这里发生了什么历史事件？",
    "给我讲一个红色故事",
    "有哪些值得参观的红色景点？",
    "红军在这里经历了什么？"
];

// 渲染快捷问题按钮
function renderQuickQuestions(village) {
    const container = document.getElementById("qqButtons");
    if (!container) return;
    container.innerHTML = "";
    QUICK_QUESTIONS.forEach(q => {
        const btn = document.createElement("button");
        btn.className = "qq-btn";
        btn.textContent = q;
        btn.onclick = function() {
            const input = document.getElementById("queryInput");
            if (input) input.value = q;
            sendMessage();
        };
        container.appendChild(btn);
    });
}

// 打字机效果
function typeWriter(element, text, speed, callback) {
    let i = 0;
    element.innerHTML = "";
    const cursor = document.createElement("span");
    cursor.className = "typing-cursor";
    element.appendChild(cursor);
    
    // 开始说话动画
    const avatarWrap = document.getElementById("avatarWrap");
    if (avatarWrap) avatarWrap.classList.add("speaking");
    
    function type() {
        if (i < text.length) {
            const char = text.charAt(i);
            cursor.insertAdjacentText("beforebegin", char);
            i++;
            setTimeout(type, speed || 25);
        } else {
            cursor.remove();
            // 停止说话动画
            if (avatarWrap) avatarWrap.classList.remove("speaking");
            if (callback) callback();
        }
    }
    type();
}

// 全局时间轴Tooltip显示
function showTlTooltip(e) {
    const el = e.currentTarget;
    const tooltip = document.getElementById("globalTlTooltip");
    if (!tooltip) return;
    
    document.getElementById("gttDate").textContent = el.getAttribute("data-date") || "";
    document.getElementById("gttLabel").textContent = el.getAttribute("data-label") || "";
    document.getElementById("gttArmy").textContent = el.getAttribute("data-army") || "";
    document.getElementById("gttDesc").textContent = el.getAttribute("data-desc") || "";
    
    // 先显示以获取尺寸（透明但可见）
    tooltip.style.visibility = "visible";
    tooltip.style.opacity = "0";
    
    const rect = el.getBoundingClientRect();
    const tipRect = tooltip.getBoundingClientRect();
    
    // 计算位置：上方居中
    let left = rect.left + rect.width / 2 - tipRect.width / 2;
    let top = rect.top - tipRect.height - 12;
    
    // 边界处理
    left = Math.max(8, Math.min(left, window.innerWidth - tipRect.width - 8));
    if (top < 8) top = rect.bottom + 12;
    
    tooltip.style.left = left + "px";
    tooltip.style.top = top + "px";
    
    // 淡入显示（用内联样式，避免类选择器优先级问题）
    requestAnimationFrame(() => {
        tooltip.style.opacity = "1";
    });
}

function hideTlTooltip() {
    const tooltip = document.getElementById("globalTlTooltip");
    if (!tooltip) return;
    tooltip.style.opacity = "0";
    // 过渡结束后隐藏
    setTimeout(() => {
        if (tooltip.style.opacity === "0") {
            tooltip.style.visibility = "hidden";
        }
    }, 200);
}

// ========== 2D数字人角色 ==========
const CHARACTER_DATA = {
    "皎平渡": { img: "/static/characters/jiaopingdu.png", name: "皎平渡老船工", greeting: "同志，我是皎平渡的老船工，当年就是我划着船送红军过江的！" },
    "石鼓": { img: "/static/characters/shigu.png", name: "石鼓纳西姑娘", greeting: "你好呀，我是石鼓的纳西族姑娘，长江第一湾的故事我最清楚啦！" },
    "扎西": { img: "/static/characters/zaxi.png", name: "扎西苗族小伙", greeting: "欢迎来到扎西！我是苗族小伙，扎西会议的故事听我慢慢讲。" },
    "寻甸柯渡": { img: "/static/characters/xundian_kedu.png", name: "柯渡回族姑娘", greeting: "色俩目，我是柯渡的回族姑娘，红军长征过柯渡的故事我都知道。" },
    "寻甸": { img: "/static/characters/xundian_kedu.png", name: "柯渡回族姑娘", greeting: "色俩目，我是柯渡的回族姑娘，红军长征过柯渡的故事我都知道。" },
    "楚雄": { img: "/static/characters/chuxiong.png", name: "楚雄彝族汉子", greeting: "阿老表，我是楚雄的彝族汉子，红军两过楚雄的故事可多了！" },
    "曲靖": { img: "/static/characters/qujing.png", name: "曲靖红军战士", greeting: "同志好！我是红军战士，曲靖是红军入滇的重要一站。" },
    "丽江": { img: "/static/characters/lijiang.png", name: "丽江纳西奶奶", greeting: "孩子，我是丽江的纳西族奶奶，红军过丽江的故事，奶奶给你讲。" },
    "宣威": { img: "/static/characters/xuanwei.png", name: "宣威彝族大哥", greeting: "老表，我是宣威的彝族大哥，宣威战役的故事，我最清楚！" },
    "禄劝": { img: "/static/characters/luquan.png", name: "禄劝彝族姑娘", greeting: "你好呀，我是禄劝的彝族姑娘，红军过禄劝的故事，我来讲给你听。" }
};

const CHARACTER_RANDOM_LINES = [
    "你好呀，同志！",
    "有什么想知道的吗？",
    "红军的故事，我最清楚啦！",
    "来，我给你讲个故事！",
    "欢迎来到我们的村寨！",
    "长征路上的故事，三天三夜讲不完！",
    "想了解更多，可以在右边和我对话哦！"
];

let currentCharacterVillage = null;
let characterBubbleTimer = null;

function showCharacter(village) {
    const data = CHARACTER_DATA[village];
    if (!data) return;
    
    const sprite = document.getElementById("characterSprite");
    const img = document.getElementById("characterImg");
    const bubble = document.getElementById("characterBubble");
    const bubbleText = document.getElementById("bubbleText");
    
    if (!sprite || !img || !bubble) return;
    
    if (currentCharacterVillage === village) {
        sayCharacterLine(data.greeting);
        return;
    }
    
    currentCharacterVillage = village;
    sprite.classList.remove("show");
    
    setTimeout(() => {
        img.src = data.img;
        img.alt = data.name;
        
        requestAnimationFrame(() => {
            sprite.classList.add("show");
        });
        
        setTimeout(() => {
            sayCharacterLine(data.greeting);
        }, 1600);
    }, 300);
}

function sayCharacterLine(text) {
    const sprite = document.getElementById("characterSprite");
    const bubble = document.getElementById("characterBubble");
    const bubbleText = document.getElementById("bubbleText");
    
    if (!sprite || !bubble || !bubbleText) return;
    
    if (characterBubbleTimer) {
        clearTimeout(characterBubbleTimer);
        characterBubbleTimer = null;
    }
    
    sprite.classList.add("speaking");
    bubbleText.textContent = text;
    bubble.classList.add("visible");
    
    characterBubbleTimer = setTimeout(() => {
        bubble.classList.remove("visible");
        sprite.classList.remove("speaking");
    }, 3500);
}

function initCharacterInteractions() {
    const sprite = document.getElementById("characterSprite");
    if (!sprite) return;
    
    sprite.addEventListener("click", function() {
        this.classList.remove("jump");
        void this.offsetWidth;
        this.classList.add("jump");
        
        const randomLine = CHARACTER_RANDOM_LINES[Math.floor(Math.random() * CHARACTER_RANDOM_LINES.length)];
        sayCharacterLine(randomLine);
    });
}

// 图例面板收起/展开
function toggleLegend() {
    const legend = document.getElementById("mapLegend");
    const btn = document.getElementById("legendToggle");
    if (!legend || !btn) return;
    legend.classList.toggle("collapsed");
    if (legend.classList.contains("collapsed")) {
        btn.textContent = "◀";
        btn.title = "展开面板";
    } else {
        btn.textContent = "▶";
        btn.title = "收起面板";
        // 右上角互斥：展开图例时关闭客流热力面板，避免重叠
        if (typeof flowActive !== "undefined" && flowActive) toggleFlow(false);
    }
}

// 收起图例（供客流面板打开时调用，避免右上角重叠）
function collapseLegend() {
    const legend = document.getElementById("mapLegend");
    const btn = document.getElementById("legendToggle");
    if (!legend || legend.classList.contains("collapsed")) return;
    legend.classList.add("collapsed");
    if (btn) { btn.textContent = "◀"; btn.title = "展开面板"; }
}

// 设置对话框背景图
function setChatBackground(name) {
    const chatPanel = document.querySelector(".chat-panel");
    if (!chatPanel) return;
    const bgUrl = CHAT_BG_MAP[name];
    if (bgUrl) {
        chatPanel.style.backgroundImage = `linear-gradient(180deg, rgba(15,22,35,0.22) 0%, rgba(17,24,39,0.3) 100%), url("${bgUrl}")`;
        chatPanel.style.backgroundSize = "cover";
        chatPanel.style.backgroundPosition = "center";
        chatPanel.style.backgroundRepeat = "no-repeat";
    } else {
        chatPanel.style.backgroundImage = "";
    }
}

// ========== 数字代言人面板数据 ==========
const VILLAGE_PROFILES = {
    "皎平渡": {
        full_avatar: "/static/avatars/full_jiaopingdu.png",
        city: "云南省禄劝县",
        event: "巧渡金沙江 · 1935年5月",
        army: "中央红军",
        intro: "1935年5月，中央红军在皎平渡仅凭7条木船、36名船工，历时7天7夜将3万将士全部渡过金沙江，彻底摆脱了数十万国民党军的围追堵截。皎平渡是长征史上以少胜多、出奇制胜的经典战例，现为全国爱国主义教育基地，红军长征渡江纪念馆坐落于此。"
    },
    "石鼓": {
        full_avatar: "/static/avatars/full_shigu.png",
        city: "云南省丽江市",
        event: "石鼓渡江 · 1936年4月",
        army: "红二、六军团",
        intro: "1936年4月，贺龙、任弼时率红二、六军团从丽江石鼓至巨甸5个渡口抢渡金沙江。1.8万将士全部顺利过江，继续北上抗日。石鼓渡口因红军长征而名扬天下，\"金沙水拍云崖暖\"描绘的正是这段历史。现为全国爱国主义教育基地，红军长征纪念碑巍然矗立。"
    },
    "扎西": {
        full_avatar: "/static/avatars/full_zaxi.png",
        city: "云南省威信县",
        event: "扎西会议 · 1935年2月",
        army: "中央红军",
        intro: "1935年2月，中共中央在威信扎西召开著名的\"扎西会议\"。会议确立了毛泽东在党和红军中的实际指挥地位，完成了遵义会议后党中央最高领导权的调整，并进行了著名的\"扎西整编\"。扎西会议是中国革命史上的重要转折点，为四渡赤水、巧渡金沙江奠定了基础。"
    },
    "寻甸柯渡": {
        full_avatar: "/static/avatars/full_xundian_kedu.png",
        city: "云南省寻甸县",
        event: "万急渡江令 · 1935年4月",
        army: "中央红军",
        intro: "1935年4月，中央红军进驻寻甸柯渡丹桂村。中革军委在此发出\"万急渡江令\"，决定兵分三路抢占金沙江渡口。毛泽东、周恩来、朱德等老一辈革命家在柯渡部署指挥了渡江战役。丹桂村现为全国重点文物保护单位，红军长征柯渡纪念馆保存着珍贵的革命文物。"
    },
    "柯渡": {
        full_avatar: "/static/avatars/full_xundian_kedu.png",
        city: "云南省寻甸县",
        event: "万急渡江令 · 1935年4月",
        army: "中央红军",
        intro: "1935年4月，中央红军进驻寻甸柯渡丹桂村。中革军委在此发出\"万急渡江令\"，决定兵分三路抢占金沙江渡口。毛泽东、周恩来、朱德等老一辈革命家在柯渡部署指挥了渡江战役。丹桂村现为全国重点文物保护单位，红军长征柯渡纪念馆保存着珍贵的革命文物。"
    },
    "寻甸": {
        full_avatar: "/static/avatars/full_xundian_kedu.png",
        city: "云南省寻甸县",
        event: "万急渡江令 · 1935年4月",
        army: "中央红军",
        intro: "1935年4月，中央红军进驻寻甸柯渡丹桂村。中革军委在此发出\"万急渡江令\"，决定兵分三路抢占金沙江渡口。毛泽东、周恩来、朱德等老一辈革命家在柯渡部署指挥了渡江战役。丹桂村现为全国重点文物保护单位，红军长征柯渡纪念馆保存着珍贵的革命文物。"
    },
    "楚雄": {
        full_avatar: "/static/avatars/full_chuxiong.png",
        city: "云南省楚雄州",
        event: "红军两过楚雄 · 1936年",
        army: "红二、六军团",
        intro: "1936年4月，红二、六军团长征两次经过楚雄。红军在楚雄地区播下革命火种，得到彝族群众的大力支持。楚雄各族人民为红军长征胜利作出了重要贡献，留下了\"红军不怕远征难\"的英雄史诗和军民鱼水情深的动人故事。楚雄彝族自治州现为全国民族团结进步示范州。"
    },
    "曲靖": {
        full_avatar: "/static/avatars/full_qujing.png",
        city: "云南省曲靖市",
        event: "红军两次过曲靖 · 1935/1936年",
        army: "中央红军 · 红二六军团",
        intro: "1935年和1936年，中央红军与红二、六军团先后两次经过曲靖。1935年4月，红军在曲靖西山关下村缴获国民党军一辆军车，获得了珍贵的云南军用地图，为巧渡金沙江提供了关键情报。曲靖是红军长征入滇的重要通道，三元宫会议旧址、关下村战斗遗址等红色遗迹保存完好。"
    },
    "丽江": {
        full_avatar: "/static/avatars/full_lijiang.png",
        city: "云南省丽江市",
        event: "红军过丽江 · 1936年4月",
        army: "红二、六军团",
        intro: "1936年4月，红二、六军团长征经过丽江。丽江各族群众热情迎接红军，为红军渡江提供了大量物资和人力支持。纳西族群众与红军结下了深厚情谊，留下了\"军民鱼水情\"的动人篇章。丽江古城现为世界文化遗产，红军长征纪念馆是重要的红色教育基地，石鼓镇红军渡江纪念碑巍然屹立。"
    },
    "宣威": {
        full_avatar: "/static/avatars/full_xuanwei.png",
        city: "云南省宣威市",
        event: "红军过宣威 · 1936年3月",
        army: "红二、六军团",
        intro: "1936年3月，红二、六军团从贵州进入云南宣威，发起了著名的\"宣威战役\"（也称虎头山战斗）。红军在宣威虎头山与滇军展开激战，重创敌军，为红军继续北上打开了通道。宣威是红二、六军团入滇的第一站，虎头山红军烈士陵园现为省级爱国主义教育基地，安葬着在战斗中牺牲的红军烈士。"
    },
    "禄劝": {
        full_avatar: "/static/avatars/full_luquan.png",
        city: "云南省禄劝县",
        event: "红军过禄劝 · 1935年5月",
        army: "中央红军",
        intro: "1935年5月，中央红军长征经过禄劝。禄劝各族群众积极支援红军，为红军巧渡金沙江提供了重要的人力、物力支持。皎平渡、洪门渡、龙街渡等金沙江渡口均在禄劝境内，禄劝是红军长征巧渡金沙江的核心区域，留下了丰富的红色文化遗产。红军长征渡江纪念馆、毛主席长征路居旧址等红色景点每年吸引大量游客前来瞻仰。"
    },
    "威信": {
        full_avatar: "/static/avatars/full_zaxi.png",
        city: "云南省威信县",
        event: "扎西会议 · 1935年2月",
        army: "中央红军",
        intro: "1935年2月，中共中央在威信扎西召开著名的\"扎西会议\"。会议确立了毛泽东在党和红军中的实际指挥地位，完成了遵义会议后党中央最高领导权的调整，并进行了著名的\"扎西整编\"。扎西会议是中国革命史上的重要转折点，为四渡赤水、巧渡金沙江奠定了基础。"
    }
};

// 打开数字代言人面板
function openAvatarPanel(name) {
    const panel = document.getElementById("avatarPanel");
    const profile = VILLAGE_PROFILES[name];
    if (!panel || !profile) return;

    document.getElementById("avatarPanelImage").src = profile.full_avatar;
    document.getElementById("avatarPanelName").textContent = name;
    document.getElementById("avatarPanelCity").textContent = profile.city;
    document.getElementById("avatarPanelEvent").textContent = profile.event;
    document.getElementById("avatarPanelArmy").textContent = profile.army;
    document.getElementById("avatarPanelIntro").textContent = profile.intro;

    panel.classList.add("open");
}

// 关闭数字代言人面板
function closeAvatarPanel() {
    const panel = document.getElementById("avatarPanel");
    if (panel) panel.classList.remove("open");
}

// 聚焦聊天输入框
function focusChatInput() {
    toggleChat(true);
    const input = document.getElementById("queryInput");
    if (input) setTimeout(()=>input.focus(), 350);
}

function renderStudyRouteFromResult(raw) {
    let data = raw;
    if (typeof raw === "string") {
        try { data = JSON.parse(raw); } catch (e) { return; }
    }
    if (!data || !Array.isArray(data.stops) || data.stops.length === 0) return;
    renderStudyRoute(data);
}

function renderStudyRoute(routeData) {
    const msgs = document.getElementById("chatMessages");
    const days = {};
    routeData.stops.forEach(stop => {
        const day = stop.day || 1;
        if (!days[day]) days[day] = [];
        days[day].push(stop);
    });

    const div = document.createElement("div");
    div.className = "msg agent";
    let html = `<div class="av-sm">&#129517;</div><div class="bubble study-route-bubble"><div class="study-route-title">&#128506;&#65039; ${escapeHtml(routeData.route_name || "红旅路线")}</div>`;

    Object.keys(days).sort((a, b) => Number(a) - Number(b)).forEach(day => {
        html += `<div class="study-route-day">第 ${escapeHtml(day)} 天</div>`;
        days[day].forEach(stop => {
            const eventLabel = Array.isArray(stop.timeline_events) && stop.timeline_events.length ? stop.timeline_events[0].label : "";
            html += `<div class="study-route-stop"><b>${escapeHtml(stop.name || "")}</b>｜${escapeHtml(stop.city || "")}｜${escapeHtml(stop.event || "")}｜${escapeHtml(String(stop.year || ""))}｜${escapeHtml(stop.army || "")}${eventLabel ? " · " + escapeHtml(eventLabel) : ""}</div>`;
        });
    });

    html += `</div>`;
    div.innerHTML = html;
    msgs.appendChild(div);
    drawStudyRouteOnMap(routeData);
}

function drawStudyRouteOnMap(routeData) {
    if (!map) return;
    if (studyRouteLayer) {
        map.removeLayer(studyRouteLayer);
        studyRouteLayer = null;
    }

    const points = [];
    const stops = [];
    (routeData.stops || []).forEach(stop => {
        if (typeof stop.lat === "number" && typeof stop.lng === "number") {
            points.push([stop.lat, stop.lng]);
            stops.push(stop);
        }
    });
    if (!points.length) return;

    studyRouteLayer = L.layerGroup().addTo(map);
    if (points.length > 1) {
        L.polyline(points, { color: "#FFD700", weight: 4, opacity: 0.95, dashArray: "6 8" }).addTo(studyRouteLayer);
    }

    points.forEach((p, idx) => {
        const stop = stops[idx];
        const icon = L.divIcon({
            className: "study-stop",
            html: `<div>${idx + 1}</div>`,
            iconSize: [26, 26],
            iconAnchor: [13, 13]
        });
        const marker = L.marker(p, { icon: icon }).addTo(studyRouteLayer);
        marker.bindPopup(`<b>${escapeHtml(stop.name || "")}</b><br>${escapeHtml(stop.event || "")}`);
    });

    if (points.length > 1) {
        map.fitBounds(L.polyline(points).getBounds().pad(0.2));
    }
}

function renderCompareVillagesFromResult(raw) {
    let data = raw;
    if (typeof raw === "string") {
        try { data = JSON.parse(raw); } catch (e) { return; }
    }
    if (!data || !data.village_a || !data.village_b) return;
    renderCompareVillages(data);
}

function renderCompareVillages(data) {
    const msgs = document.getElementById("chatMessages");
    const div = document.createElement("div");
    div.className = "msg agent";

    const col = function (v) {
        if (!v || !v.found) {
            return `<div class="compare-col"><h5>${escapeHtml((v && v.name) || "未知村寨")}</h5><div class="compare-item">未找到村寨信息</div></div>`;
        }
        const p = v.profile || {};
        const events = (v.timeline_events || []).map(e => `${escapeHtml(e.date || "")} ${escapeHtml(e.label || "")}`).join("<br>");
        const relations = (v.knowledge_graph && Array.isArray(v.knowledge_graph.relations) ? v.knowledge_graph.relations : []);
        const relText = relations.slice(0, 4).map(r => escapeHtml(r.label || r.relation || "关联")).join(" / ");
        return `<div class="compare-col"><h5>${escapeHtml(v.name || "")}</h5>
            <div class="compare-item">${escapeHtml(p.city || "")}｜${escapeHtml(p.event || "")}</div>
            <div class="compare-item"><b>年份：</b>${escapeHtml(String(p.year || ""))}</div>
            <div class="compare-item"><b>部队：</b>${escapeHtml(p.army || "")}</div>
            <div class="compare-item"><b>时间线：</b><br>${events || "暂无"}</div>
            <div class="compare-item"><b>图谱关系：</b>${relText || "暂无"}</div>
        </div>`;
    };

    div.innerHTML = `<div class="av-sm">&#128269;</div><div class="bubble compare-bubble"><div class="compare-title">&#9878;&#65039; ${escapeHtml(data.aspect || "跨村寨对比")}</div><div class="compare-grid">${col(data.village_a)}${col(data.village_b)}</div></div>`;
    msgs.appendChild(div);
}

function parseToolJson(raw) {
    if (raw && typeof raw === "object") return raw;
    try { return JSON.parse(raw); } catch (e) { return null; }
}

function findToolResult(toolResults, toolName) {
    return (toolResults || []).find(item => item && item.tool === toolName);
}

function planModuleBody(plan) {
    let html = `<div class="plan-title">规划理由：${escapeHtml(plan.reasoning || "未提供")}</div>`;
    (plan.steps || []).forEach((step, idx) => {
        const toolName = step.tool ? `（${escapeHtml(step.tool)}）` : "";
        html += `<div class="plan-step">${idx + 1}. ${escapeHtml(step.purpose || step.tool || "执行工具")}${toolName}</div>`;
    });
    return html;
}

function switchStudyPlan(btn, idx) {
    const container = btn.closest(".study-plan-container");
    if (!container) return;
    container.querySelectorAll(".study-plan-tab").forEach(t => t.classList.remove("active"));
    container.querySelectorAll(".study-plan-panel").forEach(p => p.style.display = "none");
    btn.classList.add("active");
    const panel = container.querySelector(`[data-plan-panel="${idx}"]`);
    if (panel) panel.style.display = "block";
}

function energyText(level) {
    const n = Number(level);
    if (n <= 1) return "轻松";
    if (n >= 3) return "较耗体力";
    return "适中";
}

function renderLinkList(label, links) {
    if (!Array.isArray(links) || !links.length) return "";
    const items = links.map(l => `<a class="study-link" href="${escapeHtml(l.url || "#")}" target="_blank" rel="noopener noreferrer">${escapeHtml(l.name || "查看")}</a>`).join("");
    return `<div class="study-route-links"><span>${escapeHtml(label)}：</span>${items}</div>`;
}

function renderStudyPlanBody(plan) {
    const segmentMap = {};
    (plan.travel_segments || []).forEach(seg => {
        segmentMap[seg.from + "->" + seg.to] = seg;
    });

    let html = `<div class="study-plan-head"><b>${escapeHtml(plan.label || "方案")}</b><span>${escapeHtml(plan.strategy || "")}</span></div>`;
    if (plan.reason) html += `<div class="study-tip">💡 ${escapeHtml(plan.reason)}</div>`;

    let currentDay = null;
    (plan.stops || []).forEach((stop, idx) => {
        if (stop.day !== currentDay) {
            currentDay = stop.day;
            html += `<div class="study-route-day">第 ${escapeHtml(String(currentDay))} 天</div>`;
        }

        const attractions = Array.isArray(stop.attractions) ? stop.attractions.join("、") : "";
        const food = Array.isArray(stop.food) ? stop.food.join("、") : "";
        const attractionLinks = Array.isArray(stop.attraction_links) ? stop.attraction_links : [];
        const foodLinks = Array.isArray(stop.food_links) ? stop.food_links : [];

        const next = plan.stops[idx + 1];
        html += `<div class="study-route-stop">
            <div class="study-stop-head"><b>${escapeHtml(stop.name || "")}</b><span>${escapeHtml(stop.visit_time || "")}</span></div>
            <div>${escapeHtml(stop.city || "")}｜${escapeHtml(stop.event || "")}｜${escapeHtml(String(stop.year || ""))}｜${escapeHtml(stop.army || "")}</div>
            <div><b>景点：</b>${escapeHtml(attractions || "暂无")} <b>游玩：</b>${escapeHtml(String(stop.duration_hours || 3))}小时</div>
            ${renderLinkList("景点参考", attractionLinks)}
            <div><b>美食：</b>${escapeHtml(food || "暂无")}</div>
            ${renderLinkList("美食参考", foodLinks)}
            <div class="study-energy">⚡ 体力消耗：${escapeHtml(energyText(stop.energy_level))}</div>
            ${(!next || next.day !== stop.day) && stop.lodging ? `<div class="study-lodging">🏨 住宿建议：${escapeHtml(stop.lodging)}</div>` : ""}
            ${(!next || next.day !== stop.day) && stop.lodging_link ? renderLinkList("住宿参考", [stop.lodging_link]) : ""}
            ${stop.tips ? `<div class="study-tip">💡 ${escapeHtml(stop.tips)}</div>` : ""}
        </div>`;

        if (next) {
            const seg = segmentMap[stop.name + "->" + next.name];
            if (seg) html += `<div class="study-travel">🚗 ${escapeHtml(stop.name)} → ${escapeHtml(next.name)}：约${escapeHtml(seg.estimated_travel_time || "")} / ${escapeHtml(String(seg.estimated_road_km || ""))}公里</div>`;
        }
    });

    const energy = Array.isArray(plan.daily_energy) ? plan.daily_energy : [];
    if (energy.length) {
        html += `<div class="study-route-day">每日体力值</div><div class="study-energy">${energy.map(e => `第${escapeHtml(String(e.day))}天：${escapeHtml(String(e.score))}分（${escapeHtml(e.level || "")}）`).join("；")}</div>`;
    }

    return html;
}

// 真实教学点的小红书/抖音搜索跳转（只给课程 payload 里的真实村寨挂链接，营地教室等不挂）
function socialLinksForSite(site, realVillages) {
    if (!site || !Array.isArray(realVillages) || !realVillages.includes(site)) return "";
    const kw = encodeURIComponent(site + " 红色研学");
    const xhs = `https://www.xiaohongshu.com/search_result?keyword=${kw}`;
    const dy = `https://www.douyin.com/search/${kw}`;
    return `<div class="course-social">` +
        `<a class="study-link xhs" href="${xhs}" target="_blank" rel="noopener noreferrer">📕 小红书看${escapeHtml(site)}</a>` +
        `<a class="study-link dy" href="${dy}" target="_blank" rel="noopener noreferrer">🎵 抖音看${escapeHtml(site)}</a></div>`;
}

function coursePackModuleBody(data) {
    const pricing = data.pricing || {};
    const curriculum = data.curriculum || {};
    const realVillages = Array.isArray(data.villages) ? data.villages : [];
    const cur = pricing.currency || "元";

    let html = `<div class="study-route-title">📚 ${escapeHtml(data.theme || "研学课程包")}` +
        `<span class="course-source">${data.curriculum_source === "llm" ? "AI 课程化" : "模板课程"}</span></div>`;

    html += `<div class="course-meta">` +
        `<span class="course-chip">学段：${escapeHtml(pricing.stage || "")}</span>` +
        `<span class="course-chip">共 ${escapeHtml(String(data.days || ""))} 天</span>` +
        `<span class="course-chip">班额 ${escapeHtml(String(pricing.group_size || ""))} 人</span>` +
        `<span class="course-chip">师生比 1:${escapeHtml(String(pricing.guide_student_ratio || ""))}</span>` +
        `<span class="course-chip">配导师 ${escapeHtml(String(pricing.required_guides || ""))} 名</span></div>`;

    html += `<div class="course-price">💰 费用测算（代码确定性计算 · 演示价格模型）<br>` +
        `人均 <b>${escapeHtml(String(pricing.per_student_fee || ""))}${escapeHtml(cur)}</b>` +
        ` ｜ 整团约 <b>${escapeHtml(String(pricing.total_fee || ""))}${escapeHtml(cur)}</b>`;
    if (Array.isArray(pricing.included) && pricing.included.length) {
        html += `<br>费用包含：${escapeHtml(pricing.included.join("、"))}`;
    }
    if (Array.isArray(pricing.excluded) && pricing.excluded.length) {
        html += `<br>费用不含：${escapeHtml(pricing.excluded.join("、"))}`;
    }
    html += `</div>`;

    // 往返交通总览（代码按真实坐标测算）
    const logistics = data.logistics || {};
    if (logistics.departure) {
        const segLine = seg => seg ? `${escapeHtml(seg.from)} → ${escapeHtml(seg.to)}：${escapeHtml(String(seg.estimated_road_km))} km / ${escapeHtml(seg.estimated_travel_time || "")}` : "";
        html += `<div class="course-transit">🚗 往返交通（从 ${escapeHtml(logistics.departure)} 出发，` +
            `城际方式：<b>${escapeHtml(logistics.mode_label || "旅游大巴")}</b>，全程约 ` +
            `${escapeHtml(String(logistics.total_road_km || ""))} km、累计在途约 ${escapeHtml(String(logistics.total_travel_hours || ""))} 小时）<br>` +
            `<span class="course-transit-line">去程：${segLine(logistics.outbound)}</span><br>` +
            `<span class="course-transit-line">返程：${segLine(logistics.return)}</span>` +
            (logistics.mode_note ? `<br><span class="course-transit-warn">⚙️ ${escapeHtml(logistics.mode_note)}</span>` : "") +
            (logistics.trimmed_note ? `<br><span class="course-transit-warn">📌 ${escapeHtml(logistics.trimmed_note)}</span>` : "") +
            `</div>`;
    }

    const goals = Array.isArray(curriculum.course_goals) ? curriculum.course_goals : [];
    if (goals.length) {
        html += `<div class="course-goals">🎯 课程目标：${goals.map(g => escapeHtml(g)).join("；")}</div>`;
    }

    (curriculum.daily_plans || []).forEach(plan => {
        if (!plan || typeof plan !== "object") return;
        html += `<div class="study-route-day">第 ${escapeHtml(String(plan.day || ""))} 天 · ${escapeHtml(plan.theme || "")}</div>`;
        (plan.activities || []).forEach(act => {
            if (!act || typeof act !== "object") return;
            const knowledge = Array.isArray(act.knowledge) ? act.knowledge.filter(Boolean) : [];
            html += `<div class="course-activity">` +
                `<div class="course-act-head"><b>📍 ${escapeHtml(act.site || "")}</b><span>${escapeHtml(act.slot || "")}</span></div>` +
                (knowledge.length ? `<div>📖 知识点：${knowledge.map(k => escapeHtml(k)).join("；")}</div>` : "") +
                (act.task ? `<div class="course-task">✏️ 探究任务：${escapeHtml(act.task)}</div>` : "") +
                socialLinksForSite(act.site, realVillages) +
                `</div>`;
        });
        // 当日交通衔接（代码确定性计算）
        (Array.isArray(plan.transit) ? plan.transit : []).forEach(seg => {
            if (!seg || !seg.from) return;
            html += `<div class="course-day-transit">🚗 ${escapeHtml(seg.from)} → ${escapeHtml(seg.to)}：` +
                `约 ${escapeHtml(String(seg.estimated_road_km))} km / ${escapeHtml(seg.estimated_travel_time)}</div>`;
        });
        // 当日住宿 / 返程
        if (plan.return && plan.return.from) {
            html += `<div class="course-day-lodging">🏁 返程：${escapeHtml(plan.return.from)} → ${escapeHtml(plan.return.to)}，` +
                `${escapeHtml(plan.return.estimated_travel_time)}，当晚返回出发地、不安排住宿</div>`;
        } else if (plan.lodging) {
            html += `<div class="course-day-lodging">🏨 住宿：${escapeHtml(plan.lodging)}</div>`;
        }
    });

    const handbooks = Array.isArray(curriculum.handbook_tasks) ? curriculum.handbook_tasks : [];
    if (handbooks.length) {
        html += `<div class="course-goals">📓 研学手册任务：${handbooks.map(t => escapeHtml(t)).join("；")}</div>`;
    }
    if (curriculum.closing) {
        html += `<div class="course-goals">🏁 结营安排：${escapeHtml(curriculum.closing)}</div>`;
    }

    html += `<div class="course-foot">* ${escapeHtml(pricing.note || "演示数据，非真实商业报价")}；课程知识点均来自项目档案，未虚构史实。<br>` +
        `* 小红书/抖音为按地点跳转的搜索链接，可查看该地点的游客实拍与攻略参考。</div>`;
    return html;
}function studyRouteModuleBody(data) {
    const plans = Array.isArray(data.plans) && data.plans.length ? data.plans : [{
        label: "推荐方案",
        strategy: "历史顺序",
        stops: data.stops || [],
        travel_segments: data.travel_segments || [],
        daily_energy: data.daily_energy || [],
        daily_lodging: data.daily_lodging || []
    }];

    let html = `<div class="study-route-title">${escapeHtml(data.route_name || "红旅路线")}</div><div class="study-plan-container">`;

    if (plans.length > 1) {
        html += `<div class="study-plan-tabs">`;
        plans.forEach((plan, idx) => {
            html += `<button type="button" class="study-plan-tab ${idx === 0 ? "active" : ""}" data-plan-index="${idx}" onclick="switchStudyPlan(this, ${idx})">${escapeHtml(plan.label || "方案")}</button>`;
        });
        html += `</div>`;
    }

    plans.forEach((plan, idx) => {
        html += `<div class="study-plan-panel" data-plan-panel="${idx}" style="${idx === 0 ? "" : "display:none"}">${renderStudyPlanBody(plan)}</div>`;
    });

    html += `</div>`;

    if (Array.isArray(data.why_not_other_routes) && data.why_not_other_routes.length) {
        html += `<div class="study-why"><b>为什么不选其他路线</b>${data.why_not_other_routes.map(r => `<div>· ${escapeHtml(r)}</div>`).join("")}</div>`;
    }

    return html;
}

function compareModuleBody(data) {
    const col = function (v) {
        if (!v || !v.found) {
            return `<div class="compare-col"><h5>${escapeHtml((v && v.name) || "未知村寨")}</h5><div class="compare-item">未找到村寨信息</div></div>`;
        }
        const p = v.profile || {};
        const events = (v.timeline_events || []).map(e => `${escapeHtml(e.date || "")} ${escapeHtml(e.label || "")}`).join("<br>");
        const relations = (v.knowledge_graph && Array.isArray(v.knowledge_graph.relations) ? v.knowledge_graph.relations : []);
        const relText = relations.slice(0, 4).map(r => escapeHtml(r.label || r.relation || "关联")).join(" / ");
        return `<div class="compare-col"><h5>${escapeHtml(v.name || "")}</h5>
            <div class="compare-item">${escapeHtml(p.city || "")}｜${escapeHtml(p.event || "")}</div>
            <div class="compare-item"><b>年份：</b>${escapeHtml(String(p.year || ""))}</div>
            <div class="compare-item"><b>部队：</b>${escapeHtml(p.army || "")}</div>
            <div class="compare-item"><b>时间线：</b><br>${events || "暂无"}</div>
            <div class="compare-item"><b>图谱关系：</b>${relText || "暂无"}</div>
        </div>`;
    };
    return `<div class="compare-grid">${col(data.village_a)}${col(data.village_b)}</div>`;
}

function verifyModuleBody(verification) {
    const issues = Array.isArray(verification.issues) ? verification.issues : [];
    const unavailable = verification.verified === null || verification.confidence === null || verification.confidence === undefined || issues.some(i => i && i.kind === "checker_unavailable");
    if (unavailable) {
        return `<div class="verify-warn">⚠️ 本轮事实校验未完成，回答未做自动纠错</div><div class="verify-meta">可信度：不适用</div>`;
    }

    const raw = Number(verification.confidence);
    const confidence = Number.isFinite(raw) ? Math.round(raw * 100) : 0;
    if (!issues.length) {
        return `<div class="verify-ok">✅ 关键事实校验通过，未发现明显冲突</div><div class="verify-meta">可信度：${confidence}%</div>`;
    }
    let html = `<div class="verify-meta">可信度：${confidence}%</div>`;
    issues.forEach(issue => {
        const claim = issue.claim || issue || "";
        const severity = issue.severity || "low";
        html += `<div class="verify-issue verify-${escapeHtml(severity)}">⚠️ ${escapeHtml(claim)}</div>`;
    });
    return html;
}

function highlightRiskClaims(answer, verification) {
    const issues = verification && Array.isArray(verification.issues) ? verification.issues : [];
    let html = escapeHtml(answer);
    issues.forEach(issue => {
        if (issue && issue.severity === "high") {
            const claim = (issue.claim || "").trim();
            if (!claim || claim.length < 2) return;
            const escaped = escapeHtml(claim);
            if (html.includes(escaped)) {
                html = html.split(escaped).join(`<span class="risk-highlight">${escaped}</span>`);
            }
        }
    });
    return html.replace(/\n/g, "<br>");
}

async function openPdfEvidence(source, text) {
    const overlay = document.getElementById("pdfOverlay");
    const img = document.getElementById("pdfPageImg");
    const info = document.getElementById("pdfPageInfo");
    if (!overlay || !img || !info) return;

    overlay.classList.add("open");
    img.src = "";
    info.textContent = "正在定位原始 PDF 页面...";

    try {
        const url = `/api/pdf/page?source=${encodeURIComponent(source || "")}&text=${encodeURIComponent(text || "")}`;
        const resp = await fetch(url);
        if (!resp.ok) {
            info.textContent = "无法定位原始 PDF 页面";
            return;
        }
        const blob = await resp.blob();
        img.src = URL.createObjectURL(blob);
        const page = resp.headers.get("X-Page") || "?";
        const count = resp.headers.get("X-Page-Count") || "?";
        info.textContent = `原始 PDF · 第 ${page} 页 / 共 ${count} 页`;
    } catch (e) {
        info.textContent = "原始 PDF 加载失败";
    }
}

function setupPdfOverlay() {
    const overlay = document.getElementById("pdfOverlay");
    const close = document.getElementById("pdfCloseBtn");
    if (!overlay) return;
    if (close) close.addEventListener("click", () => overlay.classList.remove("open"));
    overlay.addEventListener("click", function (e) {
        if (e.target && e.target.id === "pdfOverlay") overlay.classList.remove("open");
    });
}

function evidenceModuleBody(question, village, plan, toolResults, evidence, verification) {
    let html = `<div class="trace-title">🔎 审计链路</div>`;
    html += `<div class="trace-step"><b>问题：</b>${escapeHtml(question || "未记录")}</div>`;
    html += `<div class="trace-step"><b>村寨：</b>${escapeHtml(village || "未指定")}</div>`;

    if (plan && plan.reasoning) {
        html += `<div class="trace-step"><b>1. 任务规划：</b>${escapeHtml(plan.reasoning)}</div>`;
    } else if (plan && Array.isArray(plan.steps) && plan.steps.length) {
        html += `<div class="trace-step"><b>1. 任务规划：</b>共 ${plan.steps.length} 个执行步骤</div>`;
    }

    if (toolResults && toolResults.length) {
        html += `<div class="trace-step"><b>2. 工具调用：</b></div>`;
        toolResults.forEach((item, idx) => {
            html += `<div class="trace-sub">${idx + 1}. ${escapeHtml(item.tool || "未知工具")}：${escapeHtml(item.purpose || "")}</div>`;
        });
    }

    if (evidence && evidence.length) {
        html += `<div class="trace-step"><b>3. 档案证据：</b></div>`;
        evidence.slice(0, 4).forEach((e, idx) => {
            html += `<div class="trace-evidence"><b>[${idx + 1}] ${escapeHtml(e.source || "未知档案")}</b><br>${escapeHtml((e.text || "").slice(0, 220))}...<br><button type="button" class="pdf-btn" data-source="${escapeHtml(e.source || "")}" data-text="${escapeHtml((e.text || "").slice(0, 120))}" onclick="openPdfEvidence(this.dataset.source, this.dataset.text)">查看原PDF</button></div>`;
        });
    }

    if (verification) {
        const issues = Array.isArray(verification.issues) ? verification.issues : [];
        const unavailable = verification.verified === null || verification.confidence === null || verification.confidence === undefined || issues.some(i => i && i.kind === "checker_unavailable");
        html += `<div class="trace-step"><b>4. 事实校验：</b>${unavailable ? "本轮自动校验未完成" : (issues.length ? `发现 ${issues.length} 个待核查点` : "未发现明显冲突")}</div>`;
        issues.forEach(issue => {
            if (issue && issue.kind === "checker_unavailable") {
                html += `<div class="trace-risk trace-low">校验器暂不可用，回答未自动修正</div>`;
                return;
            }
            const severity = issue.severity || "low";
            html += `<div class="trace-risk trace-${escapeHtml(severity)}">${severity.toUpperCase()}：${escapeHtml(issue.claim || "")}</div>`;
        });
    }

    if (!plan && !(toolResults && toolResults.length) && !(evidence && evidence.length) && !verification) {
        html += `<div class="trace-step">本轮没有可展示的审计链路。</div>`;
    }

    return html;
}

function renderModuleCards(plan, toolResults, verification, evidence, question, village) {
    const modules = [];

    if (plan || (toolResults && toolResults.length) || (evidence && evidence.length) || verification) {
        modules.push({
            title: "🔗 证据链",
            body: evidenceModuleBody(question, village, plan, toolResults, evidence, verification)
        });
    }

    if (plan && (plan.is_complex || (Array.isArray(plan.steps) && plan.steps.length))) {
        modules.push({ title: "🧭 智能体规划", body: planModuleBody(plan) });
    }

    const routeTool = findToolResult(toolResults, "generate_study_route");
    if (routeTool) {
        const routeData = parseToolJson(routeTool.result);
        if (routeData && Array.isArray(routeData.stops) && routeData.stops.length) {
            modules.push({
                title: "🗺️ 红旅路线",
                body: studyRouteModuleBody(routeData),
                onOpen: function () { drawStudyRouteOnMap(routeData); }
            });
        }
    }

    const courseTool = findToolResult(toolResults, "generate_course_pack");
    if (courseTool) {
        const courseData = parseToolJson(courseTool.result);
        if (courseData && courseData.curriculum) {
            modules.push({ title: "📚 研学课程包", body: coursePackModuleBody(courseData) });
        }
    }    const compareTool = findToolResult(toolResults, "compare_villages");
    if (compareTool) {
        const compareData = parseToolJson(compareTool.result);
        if (compareData) {
            modules.push({ title: "🔍 村寨对比", body: compareModuleBody(compareData) });
        }
    }

    if (verification) {
        modules.push({ title: "✅ 事实校验", body: verifyModuleBody(verification) });
    }

    if (!modules.length) return null;

    const wrap = document.createElement("div");
    wrap.className = "msg agent";
    let html = `<div class="av-sm">&#128203;</div><div class="bubble module-bubble"><div class="module-title">智能体模块</div><div class="module-list">`;
    modules.forEach((m, idx) => {
        html += `<button type="button" class="module-btn" data-module-index="${idx}">${m.title}</button><div class="module-body" id="moduleBody${idx}"></div>`;
    });
    html += `</div></div>`;
    wrap.innerHTML = html;

    const buttons = wrap.querySelectorAll(".module-btn");
    const bodies = wrap.querySelectorAll(".module-body");
    buttons.forEach((btn, idx) => {
        btn.addEventListener("click", () => {
            const body = bodies[idx];
            const willOpen = !body.classList.contains("open");
            bodies.forEach(b => b.classList.remove("open"));
            if (willOpen) {
                body.innerHTML = modules[idx].body;
                body.classList.add("open");
                if (modules[idx].onOpen) modules[idx].onOpen();
            }
        });
    });

    return wrap;
}

