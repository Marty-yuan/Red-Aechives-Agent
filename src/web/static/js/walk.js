// ========== 平滑行走动画 ==========
function toLatLngArray(p) {
    if (Array.isArray(p)) return [p[0], p[1]];
    return [p.lat, p.lng];
}

function nearestPointIndexOnRoute(latlng, points) {
    let idx = 0;
    let minDist = Infinity;
    points.forEach((p, i) => {
        const d = Math.abs(p[0] - latlng[0]) + Math.abs(p[1] - latlng[1]);
        if (d < minDist) { minDist = d; idx = i; }
    });
    return idx;
}

// ========== 平滑行走动画 ==========
function walkSoldierAlongPath(path, routeIdx, targetIdx, durationMs) {
    if (!soldierMarker) return;

    // 若正在播放路线，先停止，避免两段动画同时抢位置
    stopRoutePlayback();

    // 新指令到达时，取消上一次还没走完的动画
    if (walkAnimationId !== null) {
        cancelAnimationFrame(walkAnimationId);
        walkAnimationId = null;
    }

    if (!Array.isArray(path) || path.length === 0) return;

    if (path.length === 1) {
        soldierMarker.setLatLng(path[0]);
        soldierLatLng = toLatLngArray(path[0]);
        soldierPos = { route: routeIdx, idx: targetIdx };
        return;
    }

    // 计算每段投影距离
    const segments = [];
    let totalDist = 0;
    for (let i = 0; i < path.length - 1; i++) {
        const p1 = map.project(toLatLngArray(path[i]), 10);
        const p2 = map.project(toLatLngArray(path[i + 1]), 10);
        const d = p1.distanceTo(p2);
        segments.push({
            start: toLatLngArray(path[i]),
            end: toLatLngArray(path[i + 1]),
            dist: d,
            cumStart: totalDist
        });
        totalDist += d;
    }

    const SPEED = 30;  // 像素/秒（在 zoom=10 投影下）
    const duration = durationMs || Math.max(1800, totalDist / SPEED);
    const startTime = performance.now();

    function animateFrame(now) {
        const t = Math.min((now - startTime) / duration, 1);
        const targetDist = t * totalDist;

        let newPos = null;
        for (let si = 0; si < segments.length; si++) {
            const seg = segments[si];
            const isLast = si === segments.length - 1;
            if (targetDist <= seg.cumStart + seg.dist || isLast) {
                const segT = seg.dist > 0 ? Math.min(1, (targetDist - seg.cumStart) / seg.dist) : 1;
                const p1 = map.project(seg.start, 10);
                const p2 = map.project(seg.end, 10);
                const mid = p1.add(p2.subtract(p1).multiplyBy(segT));
                newPos = map.unproject(mid, 10);
                break;
            }
        }

        if (newPos) {
            soldierMarker.setLatLng(newPos);
            soldierLatLng = [newPos.lat, newPos.lng];
            revealNearbyWaypoints(routeIdx, soldierLatLng);
        }

        if (t < 1) {
            walkAnimationId = requestAnimationFrame(animateFrame);
        } else {
            const last = toLatLngArray(path[path.length - 1]);
            soldierMarker.setLatLng(last);
            soldierLatLng = last;
            soldierPos = { route: routeIdx, idx: targetIdx };
            walkAnimationId = null;
            revealAllWaypoints(routeIdx);
        }
    }

    walkAnimationId = requestAnimationFrame(animateFrame);
}

function walkSoldierTo(targetLatlng, routeIdx) {
    const route = routes[routeIdx];
    if (!route) return;

    const target = toLatLngArray(targetLatlng);

    if (!soldierLatLng) {
        soldierLatLng = [route.points[0][0], route.points[0][1]];
    }

    const targetIdx = nearestPointIndexOnRoute(target, route.points);
    let path = [];

    if (soldierPos.route === routeIdx) {
        // 同一条路线：从当前坐标出发，沿路线走到目标
        const startIdx = nearestPointIndexOnRoute(soldierLatLng, route.points);
        path = [soldierLatLng];
        if (startIdx < targetIdx) {
            path.push(...route.points.slice(startIdx + 1, targetIdx + 1));
        } else if (startIdx > targetIdx) {
            path.push(...route.points.slice(targetIdx, startIdx).reverse());
        } else {
            path.push(route.points[targetIdx]);
        }
    } else {
        // 切换到另一条路线：先从当前位置走到目标路线最近入口，再沿路线走到目标
        const entryIdx = nearestPointIndexOnRoute(soldierLatLng, route.points);
        path = [soldierLatLng];
        if (entryIdx < targetIdx) {
            path.push(...route.points.slice(entryIdx, targetIdx + 1));
        } else if (entryIdx > targetIdx) {
            path.push(...route.points.slice(targetIdx, entryIdx + 1).reverse());
        } else {
            path.push(route.points[targetIdx]);
        }
    }

    walkSoldierAlongPath(path, routeIdx, targetIdx);
}

// ========== 路线时序播放 ==========
function stopRoutePlayback() {
    if (routePlayAnimationId !== null) {
        cancelAnimationFrame(routePlayAnimationId);
        routePlayAnimationId = null;
    }
    if (map3dPlayTimer) { cancelAnimationFrame(map3dPlayTimer); map3dPlayTimer = null; }
    if (routePlayLayer) {
        map.removeLayer(routePlayLayer);
        routePlayLayer = null;
    }
    routePlayActive = false;
    syncRouteButtons(-1);
    resetTimeline();
}

function syncRouteButtons(activeIdx) {
    routeLegendBtns.forEach((btn, i) => {
        if (!btn) return;
        const active = i === activeIdx;
        btn.classList.toggle("active", active);
        const badge = btn.querySelector(".play-badge");
        if (badge) badge.textContent = active ? "⏹" : "▶";
        btn.title = active ? "点击停止播放" : "点击播放该路线行军时序";
    });
    (timelineGroupEls || []).forEach((el, i) => {
        if (!el) return;
        const active = i === activeIdx;
        el.classList.toggle("active", active);
        const badge = el.querySelector(".play-badge");
        if (badge) badge.textContent = active ? "⏹" : "▶";
    });
}

// ========== 时间轴与路线同步 ==========
function computeTimelineFractions(routeIdx) {
    const route = routes[routeIdx];
    if (!route || !Array.isArray(route.points) || route.points.length < 2) return;
    const pts = route.points;
    timelineItems.forEach(item => {
        if (item.route !== routeIdx) return;
        const c = villageCoords[item.village];
        if (!c) { item.fraction = 1; return; }
        const idx = nearestPointIndexOnRoute([c.lat, c.lng], pts);
        item.fraction = Math.max(0, Math.min(1, idx / (pts.length - 1)));
    });
}

function syncTimeline(routeIdx, t) {
    const bar = document.getElementById("timelineBar");
    let activeEl = null;
    let maxFrac = -1;
    timelineItems.forEach(item => {
        if (item.route !== routeIdx) return;
        const passed = t >= item.fraction;
        item.el.classList.toggle("passed", passed);
        if (passed && item.fraction > maxFrac) {
            maxFrac = item.fraction;
            activeEl = item.el;
        }
    });
    timelineItems.forEach(item => {
        if (item.route === routeIdx) item.el.classList.toggle("active", item.el === activeEl);
    });
    if (activeEl && bar) {
        const target = activeEl.offsetLeft - bar.clientWidth / 2 + activeEl.offsetWidth / 2;
        bar.scrollTo({ left: target, behavior: "smooth" });
    }
}

function resetTimeline() {
    const bar = document.getElementById("timelineBar");
    if (bar) {
        bar.removeAttribute("data-playing");
        bar.classList.remove("tl-play");
    }
    timelineItems.forEach(item => {
        item.el.classList.remove("active", "passed");
    });
}

function toggleTimelinePin() {
    const bar = document.getElementById("timelineBar");
    const hint = document.getElementById("tlHint");
    if (!bar) return;
    const pinned = bar.classList.toggle("tl-pinned");
    if (hint) hint.textContent = pinned ? "📌 时间轴" : "⏱ 时间轴";
}

function playRoute(routeIdx) {
    const route = routes[routeIdx];
    if (!route || !map || !soldierMarker) return;

    // 3D 模式下走 3D 飞行播放
    if (is3DMode && typeof playRoute3D === "function") {
        if (routePlayActive === routeIdx) { stopRoutePlayback(); if (map3dPlayTimer) cancelAnimationFrame(map3dPlayTimer); return; }
        routePlayActive = routeIdx;
        playRoute3D(routeIdx);
        return;
    }

    // 再次点击正在播放的路线 -> 停止
    if (routePlayActive === routeIdx) {
        stopRoutePlayback();
        return;
    }

    stopRoutePlayback();
    const points = route.points.map(toLatLngArray);
    if (points.length < 2) return;

    // 聚焦到该路线范围：收紧留白，让路线尽量铺满视野（仍保证全貌可见）
    map.flyToBounds(L.polyline(points).getBounds().pad(0.06), { duration: 1.2 });

    // 播放图层：随时间逐步延展的路线 + 起点/终点标记
    routePlayLayer = L.layerGroup().addTo(map);
    const playLine = L.polyline([], {
        color: route.color, weight: 6, opacity: 0.95, lineCap: "round", lineJoin: "round"
    }).addTo(routePlayLayer);

    const startIcon = L.divIcon({ className: "route-play-start", html: "▶", iconSize: [22, 22], iconAnchor: [11, 11] });
    L.marker(points[0], { icon: startIcon }).addTo(routePlayLayer);
    const endIcon = L.divIcon({ className: "route-play-end", html: "★", iconSize: [22, 22], iconAnchor: [11, 11] });
    L.marker(points[points.length - 1], { icon: endIcon }).addTo(routePlayLayer);

    // 计算每段投影距离
    const segments = [];
    let totalDist = 0;
    for (let i = 0; i < points.length - 1; i++) {
        const p1 = map.project(points[i], 10);
        const p2 = map.project(points[i + 1], 10);
        const d = p1.distanceTo(p2);
        segments.push({ start: points[i], end: points[i + 1], dist: d, cumStart: totalDist });
        totalDist += d;
    }

    const SPEED = 100;  // 全程播放速度（像素/秒，zoom=10 投影）；放慢便于跟看行军过程
    const duration = Math.min(28000, Math.max(14000, totalDist / SPEED));
    const startTime = performance.now();
    routePlayActive = routeIdx;
    syncRouteButtons(routeIdx);

    // 时间轴：只高亮当前路线，两条路线分开
    resetTimeline();
    const timelineBarEl = document.getElementById("timelineBar");
    if (timelineBarEl) {
        timelineBarEl.setAttribute("data-playing", String(routeIdx));
        timelineBarEl.classList.add("tl-play");
    }
    computeTimelineFractions(routeIdx);

    function frame(now) {
        const t = Math.min((now - startTime) / duration, 1);
        const targetDist = t * totalDist;

        let linePoints = [];
        let headPoint = null;
        for (let si = 0; si < segments.length; si++) {
            const seg = segments[si];
            const isLast = si === segments.length - 1;
            if (targetDist <= seg.cumStart + seg.dist || isLast) {
                for (let k = 0; k <= si; k++) linePoints.push(segments[k].start);
                const segT = seg.dist > 0 ? Math.min(1, (targetDist - seg.cumStart) / seg.dist) : 1;
                if (segT >= 1 && isLast) {
                    headPoint = seg.end;
                } else {
                    const mp1 = map.project(seg.start, 10);
                    const mp2 = map.project(seg.end, 10);
                    const mid = mp1.add(mp2.subtract(mp1).multiplyBy(segT));
                    headPoint = map.unproject(mid, 10);
                }
                linePoints.push([headPoint.lat, headPoint.lng]);
                break;
            }
        }

        playLine.setLatLngs(linePoints);

        // 战士跟随路线头部行进（时序展示）
        soldierMarker.setLatLng(headPoint);
        soldierLatLng = [headPoint.lat, headPoint.lng];
        revealNearbyWaypoints(routeIdx, soldierLatLng);
        syncTimeline(routeIdx, t);

        if (t < 1) {
            routePlayAnimationId = requestAnimationFrame(frame);
        } else {
            playLine.setLatLngs(points);
            soldierMarker.setLatLng(points[points.length - 1]);
            soldierLatLng = points[points.length - 1];
            soldierPos = { route: routeIdx, idx: points.length - 1 };
            routePlayAnimationId = null;
            routePlayActive = false;
            syncRouteButtons(-1);
            revealAllWaypoints(routeIdx);
            syncTimeline(routeIdx, 1);
            const tb = document.getElementById("timelineBar");
            if (tb) tb.classList.remove("tl-play");
        }
    }

    routePlayAnimationId = requestAnimationFrame(frame);
}

