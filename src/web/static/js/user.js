// ========== 用户画像与长期记忆 ==========
function modeName(mode) {
    return {"student":"儿童模式","tourist":"游客模式","researcher":"研究者模式"}[mode] || "游客模式";
}

function syncModeButtons() {
    document.querySelectorAll(".mode-btn").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.mode === currentMode);
    });
}

function setMode(mode) {
    currentMode = mode;
    syncModeButtons();
    if (currentUser) {
        fetch("/api/memory/mode", {
            method: "POST",
            headers: authHeaders(),
            body: JSON.stringify({mode: mode})
        }).catch(() => {});
    }
    updateAuthUI();
}

function openAuth() {
    document.getElementById("authOverlay").classList.add("open");
    updateAuthUI();
}

function closeAuth() {
    document.getElementById("authOverlay").classList.remove("open");
}

function updateAuthUI() {
    const btn = document.getElementById("authBtn");
    const chip = document.getElementById("userChip");
    const status = document.getElementById("authStatus");
    const logoutBtn = document.getElementById("logoutBtn");
    const deleteBtn = document.getElementById("deleteConversationBtn");
    if (!btn) return;

    if (currentUser) {
        btn.innerHTML = ICON_USER + " 账户";
        chip.textContent = currentUser;
        chip.title = currentUser;
        if (status) {
            status.style.display = "block";
            status.innerHTML = `已登录：${escapeHtml(currentUser)}<br>当前讲解人格：${escapeHtml(modeName(currentMode))}`;
        }
        if (logoutBtn) logoutBtn.style.display = "block";
    } else {
        btn.innerHTML = ICON_USER + " 登录 / 注册";
        chip.textContent = "";
        chip.title = "";
        if (status) status.style.display = "none";
        if (logoutBtn) logoutBtn.style.display = "none";
    }
    if (deleteBtn) deleteBtn.style.display = currentUser ? "inline-block" : "none";
}

async function refreshUser() {
    try {
        const r = await fetch("/api/auth/me", {headers: authHeaders()});
        const data = await r.json();
        if (!data.logged_in) setToken("");
        currentUser = data.logged_in ? data.username : null;
        if (data.profile) {
            currentMode = data.profile.persona_mode || "tourist";
        }
        syncModeButtons();
        updateAuthUI();
        if (currentUser && currentVillage) {
            loadVillageHistory(currentVillage);
        }
    } catch (e) {}
}

async function loginUser() {
    const username = document.getElementById("authUsername").value.trim();
    const password = document.getElementById("authPassword").value;
    if (!username || !password) {
        alert("请输入用户名和密码");
        return;
    }
    const r = await fetch("/api/auth/login", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({username: username, password: password})
    });
    const data = await r.json();
    if (!r.ok) {
        alert(data.error || "登录失败");
        return;
    }
    if (data.token) setToken(data.token);
    currentUser = data.username;
    document.getElementById("authPassword").value = "";
    updateAuthUI();
    closeAuth();
    await refreshUser();
    if (currentVillage) loadVillageHistory(currentVillage);
}

async function registerUser() {
    const username = document.getElementById("authUsername").value.trim();
    const password = document.getElementById("authPassword").value;
    if (!username || !password) {
        alert("请输入用户名和密码");
        return;
    }
    const r = await fetch("/api/auth/register", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({username: username, password: password})
    });
    const data = await r.json();
    if (!r.ok) {
        alert(data.error || "注册失败");
        return;
    }
    if (data.token) setToken(data.token);
    currentUser = data.username;
    document.getElementById("authPassword").value = "";
    updateAuthUI();
    closeAuth();
    await refreshUser();
    if (currentVillage) loadVillageHistory(currentVillage);
}

async function logoutUser() {
    await fetch("/api/auth/logout", {method: "POST", headers: authHeaders()}).catch(() => {});
    setToken("");
    currentUser = null;
    updateAuthUI();
    closeAuth();
    if (currentVillage) loadVillageHistory(currentVillage);
}

async function loadVillageHistory(name) {
    const msgs = document.getElementById("chatMessages");
    msgs.innerHTML = "";

    const msg = document.createElement("div");
    msg.className = "msg agent";
    msg.innerHTML = `<div class="av-sm">🎖️</div><div class="bubble">你好，我是${escapeHtml(name)}的代言人。想了解这里的红军长征故事吗？</div>`;
    msgs.appendChild(msg);

    if (!name) return;
    try {
        const r = await fetch(`/api/memory/history?village=${encodeURIComponent(name)}`, {headers: authHeaders(), credentials: "same-origin"});
        const data = await r.json();
        if (!data.logged_in || !Array.isArray(data.messages)) return;
        data.messages.forEach(appendHistoryMessage);
    } catch (e) {}
}

function appendHistoryMessage(m) {
    if (!m || !m.content) return;
    const msgs = document.getElementById("chatMessages");
    const div = document.createElement("div");
    const safe = escapeHtml(m.content).replace(/\n/g, "<br>");
    if (m.role === "user") {
        div.className = "msg user";
        div.innerHTML = `<div class="bubble">${safe}</div><div class="av-sm">👤</div>`;
    } else {
        div.className = "msg agent";
        div.innerHTML = `<div class="av-sm">🎖️</div><div class="bubble">${renderMessageHtml(m.content)}</div>`;
    }
    msgs.appendChild(div);
}

async function deleteCurrentConversation() {
    if (!currentVillage) {
        alert("请先选择一个村寨");
        return;
    }
    if (!currentUser) {
        alert("请先登录后再删除对话");
        return;
    }
    const ok = confirm(`确定删除“${currentVillage}代言人”的所有历史对话吗？`);
    if (!ok) return;
    try {
        const r = await fetch(`/api/memory/history?village=${encodeURIComponent(currentVillage)}`, {
            method: "DELETE",
            headers: authHeaders(),
            credentials: "same-origin"
        });
        const data = await r.json();
        if (!r.ok) {
            alert(data.error || "删除失败");
            return;
        }
        await loadVillageHistory(currentVillage);
    } catch (e) {
        alert("删除失败，请检查后端服务是否已启动");
    }
}

