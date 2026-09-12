// ============================================================
// ========== 数字档案馆门厅（Three.js 程序化 3D） ==============
// ============================================================
let hallReady = false, hallVisible = false;
let hallScene = null, hallCamera = null, hallRenderer = null, hallRAF = null;
let hallOrb = null, hallOrbSphere = null, hallBeam = null;
let hallGuides = [];
let hallRaycaster = null, hallNDC = null;
let hallOrbLoaded = false, hallGuidesLoaded = false;

const HALL_NODE_COLORS = {
    person: 0xE8384F, location: 0x2F80ED, event: 0xE67E22,
    army: 0x27AE60, organization: 0x9B59B6, document: 0xF5C842
};

function hallFloorTexture() {
    const c = document.createElement("canvas"); c.width = c.height = 512;
    const g = c.getContext("2d");
    g.fillStyle = "#0A0E17"; g.fillRect(0, 0, 512, 512);
    const rg = g.createRadialGradient(256, 256, 16, 256, 256, 256);
    rg.addColorStop(0, "rgba(212,32,44,0.30)");
    rg.addColorStop(0.55, "rgba(139,0,0,0.10)");
    rg.addColorStop(1, "rgba(0,0,0,0)");
    g.fillStyle = rg; g.fillRect(0, 0, 512, 512);
    g.strokeStyle = "rgba(245,200,66,0.10)"; g.lineWidth = 1;
    for (let i = 0; i <= 32; i++) {
        const p = i * 16;
        g.beginPath(); g.moveTo(p, 0); g.lineTo(p, 512); g.stroke();
        g.beginPath(); g.moveTo(0, p); g.lineTo(512, p); g.stroke();
    }
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    t.wrapS = t.wrapT = THREE.RepeatWrapping;
    t.repeat.set(3, 4);
    return t;
}

function hallWallTexture() {
    const c = document.createElement("canvas"); c.width = 1024; c.height = 512;
    const g = c.getContext("2d");
    const bg = g.createLinearGradient(0, 0, 0, 512);
    bg.addColorStop(0, "#22070d"); bg.addColorStop(1, "#0a0e17");
    g.fillStyle = bg; g.fillRect(0, 0, 1024, 512);
    g.strokeStyle = "rgba(245,200,66,0.38)"; g.lineWidth = 4; g.strokeRect(36, 36, 952, 440);
    g.strokeStyle = "rgba(245,200,66,0.16)"; g.lineWidth = 1; g.strokeRect(52, 52, 920, 408);
    g.save(); g.translate(512, 205);
    g.beginPath();
    for (let i = 0; i < 5; i++) {
        const a = -Math.PI / 2 + i * 2 * Math.PI / 5;
        g.lineTo(Math.cos(a) * 78, Math.sin(a) * 78);
        const b = a + Math.PI / 5;
        g.lineTo(Math.cos(b) * 31, Math.sin(b) * 31);
    }
    g.closePath();
    g.fillStyle = "#C41E3A"; g.fill();
    g.strokeStyle = "#F5C842"; g.lineWidth = 3; g.stroke();
    g.restore();
    g.textAlign = "center";
    g.fillStyle = "rgba(245,200,66,0.92)";
    g.font = "bold 56px 'Microsoft YaHei', 'PingFang SC', sans-serif";
    g.fillText("红 色 档 案", 512, 372);
    g.fillStyle = "rgba(241,245,249,0.5)";
    g.font = "22px 'Microsoft YaHei', sans-serif";
    g.fillText("ARCHIVE  ·  LONG  MARCH  ·  1935—1936", 512, 418);
    const t = new THREE.CanvasTexture(c);
    t.colorSpace = THREE.SRGBColorSpace;
    return t;
}

function buildHallRoom() {
    const floor = new THREE.Mesh(
        new THREE.PlaneGeometry(44, 64),
        new THREE.MeshStandardMaterial({ map: hallFloorTexture(), metalness: 0.45, roughness: 0.5 })
    );
    floor.rotation.x = -Math.PI / 2;
    hallScene.add(floor);

    const colMat = new THREE.MeshStandardMaterial({ color: 0x5a0d16, metalness: 0.35, roughness: 0.55 });
    const goldMat = new THREE.MeshStandardMaterial({ color: 0xF5C842, metalness: 0.9, roughness: 0.25, emissive: 0x3a2a00 });
    [-7.6, 7.6].forEach(x => {
        [-11, -4.5, 2, 8.5].forEach(z => {
            const col = new THREE.Mesh(new THREE.CylinderGeometry(0.46, 0.56, 9.6, 18), colMat);
            col.position.set(x, 4.8, z);
            hallScene.add(col);
            [1.2, 8.2].forEach(y => {
                const ring = new THREE.Mesh(new THREE.CylinderGeometry(0.54, 0.54, 0.24, 18), goldMat);
                ring.position.set(x, y, z);
                hallScene.add(ring);
            });
        });
    });

    const wallMat = new THREE.MeshStandardMaterial({ color: 0x120a12, metalness: 0.2, roughness: 0.9, side: THREE.DoubleSide });
    const back = new THREE.Mesh(new THREE.PlaneGeometry(46, 18), wallMat);
    back.position.set(0, 9, -17);
    hallScene.add(back);

    const banner = new THREE.Mesh(new THREE.PlaneGeometry(15, 7.5), new THREE.MeshBasicMaterial({ map: hallWallTexture() }));
    banner.position.set(0, 7.4, -16.7);
    hallScene.add(banner);

    [-15, 15].forEach(x => {
        const side = new THREE.Mesh(new THREE.PlaneGeometry(60, 18), wallMat);
        side.rotation.y = Math.PI / 2;
        side.position.set(x, 9, 0);
        hallScene.add(side);
    });

    const ceil = new THREE.Mesh(
        new THREE.PlaneGeometry(46, 64),
        new THREE.MeshStandardMaterial({ color: 0x0a0d15, metalness: 0.2, roughness: 0.95, side: THREE.DoubleSide })
    );
    ceil.rotation.x = Math.PI / 2;
    ceil.position.y = 16;
    hallScene.add(ceil);
}

function buildHallBeam() {
    hallBeam = new THREE.Mesh(
        new THREE.ConeGeometry(7.2, 15, 40, 1, true),
        new THREE.MeshBasicMaterial({
            color: 0xF5C842, transparent: true, opacity: 0.05,
            side: THREE.DoubleSide, blending: THREE.AdditiveBlending, depthWrite: false
        })
    );
    hallBeam.position.set(0, 8.6, 0);
    hallScene.add(hallBeam);
}

function buildHallOrb() {
    fetch("/api/knowledge_graph").then(r => r.json()).then(data => {
        const nodes = (data && data.nodes) || [];
        const edges = (data && data.edges) || [];
        const n = nodes.length;
        if (!n) { hallOrbLoaded = true; hallMaybeReady(); return; }
        const idx = new Map(), pos = new Float32Array(n * 3), col = new Float32Array(n * 3);
        const R = 3.0, GA = Math.PI * (1 + Math.sqrt(5)), cc = new THREE.Color();
        for (let i = 0; i < n; i++) {
            const y = 1 - (i + 0.5) * 2 / n;
            const r = Math.sqrt(Math.max(0, 1 - y * y));
            const th = GA * (i + 0.5);
            pos[i * 3] = Math.cos(th) * r * R;
            pos[i * 3 + 1] = y * R * 0.72;
            pos[i * 3 + 2] = Math.sin(th) * r * R;
            cc.setHex(HALL_NODE_COLORS[nodes[i].type] || 0xF5C842);
            col[i * 3] = cc.r; col[i * 3 + 1] = cc.g; col[i * 3 + 2] = cc.b;
            idx.set(nodes[i].id, i);
        }
        const pg = new THREE.BufferGeometry();
        pg.setAttribute("position", new THREE.BufferAttribute(pos, 3));
        pg.setAttribute("color", new THREE.BufferAttribute(col, 3));
        const pts = new THREE.Points(pg, new THREE.PointsMaterial({
            size: 0.09, vertexColors: true, transparent: true, opacity: 0.95,
            sizeAttenuation: true, depthWrite: false, blending: THREE.AdditiveBlending
        }));

        const seg = [];
        edges.forEach(e => {
            const a = idx.get(e.source), b = idx.get(e.target);
            if (a === undefined || b === undefined) return;
            seg.push(pos[a * 3], pos[a * 3 + 1], pos[a * 3 + 2], pos[b * 3], pos[b * 3 + 1], pos[b * 3 + 2]);
        });
        const lg = new THREE.BufferGeometry();
        lg.setAttribute("position", new THREE.BufferAttribute(new Float32Array(seg), 3));
        const lines = new THREE.LineSegments(lg, new THREE.LineBasicMaterial({
            color: 0xF5C842, transparent: true, opacity: 0.14,
            blending: THREE.AdditiveBlending, depthWrite: false
        }));

        hallOrb = new THREE.Group();
        hallOrb.add(pts);
        hallOrb.add(lines);
        hallOrb.position.set(0, 4.7, 0);
        hallScene.add(hallOrb);

        hallOrbSphere = new THREE.Mesh(
            new THREE.SphereGeometry(3.25, 16, 12),
            new THREE.MeshBasicMaterial({ visible: false })
        );
        hallOrbSphere.position.copy(hallOrb.position);
        hallScene.add(hallOrbSphere);

        hallOrbLoaded = true;
        hallMaybeReady();
    }).catch(() => { hallOrbLoaded = true; hallMaybeReady(); });
}

function buildHallGuides() {
    fetch("/api/villages").then(r => r.json()).then(list => {
        const loader = new THREE.TextureLoader();
        const seen = new Set();
        let i = 0;
        (list || []).forEach(v => {
            const key = v.avatar || "";
            if (!v.name || !key || seen.has(key)) return;
            seen.add(key);
            const slot = i++;
            const url = key.replace("/avatars/", "/characters/");
            const side = (slot % 2 === 0) ? -1 : 1;
            const row = Math.floor(slot / 2);
            const HH = 3.6;
            const baseY = HH / 2 - 0.05;
            const phase = Math.random() * Math.PI * 2;
            loader.load(url, tex => {
                tex.colorSpace = THREE.SRGBColorSpace;
                const aspect = (tex.image && tex.image.width ? tex.image.width : 1024) /
                               (tex.image && tex.image.height ? tex.image.height : 1536);
                const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, transparent: true, depthWrite: false }));
                sp.scale.set(HH * aspect, HH, 1);
                sp.position.set(side * 5.2, baseY, -6.6 + row * 3.5);
                sp.userData = { name: v.name, baseY, phase };
                hallScene.add(sp);
                hallGuides.push({ sprite: sp, baseY, phase });
            });
        });
        hallGuidesLoaded = true;
        hallMaybeReady();
    }).catch(() => { hallGuidesLoaded = true; hallMaybeReady(); });
}

function hallMaybeReady() {
    if (!(hallOrbLoaded && hallGuidesLoaded)) return;
    const el = document.getElementById("hallLoading");
    if (el) el.classList.add("done");
}

function hallPick(ev) {
    if (!hallRaycaster || !hallCamera || !hallRenderer) return null;
    const rect = hallRenderer.domElement.getBoundingClientRect();
    hallNDC.set(
        ((ev.clientX - rect.left) / rect.width) * 2 - 1,
        -((ev.clientY - rect.top) / rect.height) * 2 + 1
    );
    hallRaycaster.setFromCamera(hallNDC, hallCamera);
    const sprites = hallGuides.map(g => g.sprite);
    if (sprites.length) {
        const hits = hallRaycaster.intersectObjects(sprites, false);
        if (hits.length) return { type: "guide", name: hits[0].object.userData.name };
    }
    if (hallOrbSphere) {
        const oh = hallRaycaster.intersectObject(hallOrbSphere, false);
        if (oh.length) return { type: "orb" };
    }
    return null;
}

function hallSummon(name) {
    selectVillage(name);       // 选中村寨（背景/快捷问题/立绘随之切换）
    toggleChat(true);          // 对话抽屉滑出（z-index 高于门厅）
    showToast("已召唤「" + name + "」代言人", "info");
}

function hallResize() {
    if (!hallReady || !hallRenderer) return;
    const overlay = document.getElementById("hallOverlay");
    if (!overlay) return;
    const W = overlay.clientWidth || window.innerWidth;
    const H = overlay.clientHeight || window.innerHeight;
    hallCamera.aspect = W / Math.max(1, H);
    hallCamera.updateProjectionMatrix();
    hallRenderer.setSize(W, H, false);
}

function hallTick(t) {
    if (!hallVisible) return;
    hallRAF = requestAnimationFrame(hallTick);
    const s = t * 0.001;
    if (hallOrb) hallOrb.rotation.y = s * 0.12;
    for (let i = 0; i < hallGuides.length; i++) {
        const g = hallGuides[i];
        g.sprite.position.y = g.baseY + Math.sin(s * 1.3 + g.phase) * 0.07;
    }
    if (hallBeam) hallBeam.material.opacity = 0.04 + 0.015 * (1 + Math.sin(s * 0.9));
    hallRenderer.render(hallScene, hallCamera);
}

function ensureHall() {
    if (hallReady) return true;
    if (typeof THREE === "undefined") { showToast("3D 库未加载，无法进入数字档案馆", "error"); return false; }
    const overlay = document.getElementById("hallOverlay");
    if (!overlay) return false;

    const W = overlay.clientWidth || window.innerWidth;
    const H = overlay.clientHeight || window.innerHeight;

    hallScene = new THREE.Scene();
    hallScene.background = new THREE.Color(0x070A10);
    hallScene.fog = new THREE.Fog(0x070A10, 30, 62);

    hallCamera = new THREE.PerspectiveCamera(52, W / Math.max(1, H), 0.1, 200);
    hallCamera.position.set(0, 6.2, 17.5);
    hallCamera.lookAt(0, 4.6, 0);

    hallRenderer = new THREE.WebGLRenderer({ antialias: true });
    hallRenderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
    hallRenderer.setSize(W, H, false);
    hallRenderer.domElement.style.width = "100%";
    hallRenderer.domElement.style.height = "100%";
    overlay.insertBefore(hallRenderer.domElement, overlay.firstChild);

    hallScene.add(new THREE.AmbientLight(0x44506a, 1.25));
    const key = new THREE.PointLight(0xF5C842, 90, 70, 2); key.position.set(0, 14, 3); hallScene.add(key);
    [-10, 10].forEach(x => {
        const l = new THREE.PointLight(0xC41E3A, 55, 42, 2);
        l.position.set(x, 5.5, 8);
        hallScene.add(l);
    });

    buildHallRoom();
    buildHallBeam();
    buildHallOrb();
    buildHallGuides();

    hallRaycaster = new THREE.Raycaster();
    hallNDC = new THREE.Vector2();
    const dom = hallRenderer.domElement;
    dom.addEventListener("pointerdown", function (ev) {
        const hit = hallPick(ev);
        if (!hit) return;
        if (hit.type === "guide") hallSummon(hit.name);
        else if (hit.type === "orb") openKnowledgeGraph();
    });
    dom.addEventListener("pointermove", function (ev) {
        dom.style.cursor = hallPick(ev) ? "pointer" : "default";
    });
    window.addEventListener("resize", hallResize);

    hallReady = true;
    return true;
}

function enterHall() {
    const overlay = document.getElementById("hallOverlay");
    if (!overlay) return;
    if (!ensureHall()) return;
    overlay.classList.add("open");
    document.body.classList.add("hall-open");
    hallVisible = true;
    requestAnimationFrame(hallResize);
    if (!hallRAF) hallRAF = requestAnimationFrame(hallTick);
}

function exitHall() {
    const overlay = document.getElementById("hallOverlay");
    if (overlay) overlay.classList.remove("open");
    document.body.classList.remove("hall-open");
    hallVisible = false;
    if (hallRAF) { cancelAnimationFrame(hallRAF); hallRAF = null; }
    requestAnimationFrame(() => { if (map) map.invalidateSize(); });
}

document.getElementById("hallBackBtn").addEventListener("click", exitHall);
