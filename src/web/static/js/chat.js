// ========== 发送消息 ==========
function escapeHtml(text) {
    return String(text || "").replace(/[&<>"']/g, function (ch) {
        return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[ch];
    });
}

function renderMessageHtml(text) {
    let html = escapeHtml(text);
    html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
    return html.replace(/\n/g, "<br>");
}

function plainTextForSpeech(text) {
    return String(text || "")
        .replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g, "$1")
        .replace(/\*\*?/g, "")
        .trim();
}

function sendMessage() {
    if (!currentVillage) return;
    let input = document.getElementById("queryInput");
    let question = input.value.trim();
    if (!question) return;
    input.value = "";

    let msgs = document.getElementById("chatMessages");
    let um = document.createElement("div");
    um.className = "msg user";
    um.innerHTML = `<div class="bubble">${escapeHtml(question)}</div><div class="av-sm">👤</div>`;
    msgs.appendChild(um);

    let tm = document.createElement("div");
    tm.className = "msg agent";
    tm.id = "typing";
    tm.innerHTML = `<div class="av-sm">🎖️</div><div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>`;
    msgs.appendChild(tm);
    msgs.scrollTop = msgs.scrollHeight;

    fetch("/chat", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({village: currentVillage, question: question, mode: currentMode})
    }).then(r => r.json()).then(data => {
        const typing = document.getElementById("typing");
        if (typing) typing.remove();

        const answer = (data.answer && String(data.answer).trim()) || data.error || "服务暂时没有生成有效回答，请稍后再试一次。";
        const plan = data.plan;
        const verification = data.verification;
        const toolResults = data.tool_results || [];
        const evidence = data.evidence || [];
        if (data.mode) {
            currentMode = data.mode;
            syncModeButtons();
        }

        let am = document.createElement("div");
        am.className = "msg agent";
        am.innerHTML = `<div class="av-sm">&#127894;&#65039;</div><div class="bubble"></div>`;
        const bubble = am.querySelector(".bubble");
        msgs.appendChild(am);
        msgs.scrollTop = msgs.scrollHeight;
        
        // 打字机效果：逐字显示，完成后替换为格式化HTML并添加朗读按钮
        typeWriter(bubble, answer, 22, function() {
            bubble.innerHTML = renderMessageHtml(answer);
            const speakBtn = document.createElement("button");
            speakBtn.className = "speak-btn";
            speakBtn.title = "朗读此回答";
            speakBtn.innerHTML = ICON_VOL + " 朗读";
            speakBtn.addEventListener("click", () => speakAnswer(answer, speakBtn));
            bubble.appendChild(speakBtn);
            msgs.scrollTop = msgs.scrollHeight;
        });

        const moduleWrap = renderModuleCards(plan, toolResults, verification, evidence, question, currentVillage);
        if (moduleWrap) msgs.appendChild(moduleWrap);

        msgs.scrollTop = msgs.scrollHeight;
    }).catch(() => {
        const typing = document.getElementById("typing");
        if (typing) typing.remove();
        const msgs = document.getElementById("chatMessages");
        if (msgs) {
            const err = document.createElement("div");
            err.className = "msg agent";
            err.innerHTML = `<div class="av-sm">🎖️</div><div class="bubble">网络请求失败，请确认后端服务已启动。</div>`;
            msgs.appendChild(err);
            msgs.scrollTop = msgs.scrollHeight;
        }
    });
}

function runCompare() {
    const q = ((document.getElementById("queryInput") || {}).value || "").trim();
    if (!q) { alert("请先在输入框输入一个问题，再点「模式对照」"); return; }
    const msgs = document.getElementById("chatMessages");
    if (!msgs) return;
    const tm = document.createElement("div");
    tm.className = "msg agent";
    tm.id = "compareTyping";
    tm.innerHTML = '<div class="av-sm">🆚</div><div class="bubble"><div class="typing"><span></span><span></span><span></span></div></div>';
    msgs.appendChild(tm);
    msgs.scrollTop = msgs.scrollHeight;
    fetch("/api/chat/compare", {
        method: "POST",
        headers: authHeaders(),
        body: JSON.stringify({village: currentVillage, question: q})
    }).then(r => r.json()).then(d => {
        const t = document.getElementById("compareTyping");
        if (t) t.remove();
        const answers = (d && d.answers) || {};
        const wrap = document.createElement("div");
        wrap.className = "msg agent";
        wrap.innerHTML = '<div class="av-sm">🆚</div><div class="bubble">' +
            '<div style="font-weight:bold;margin-bottom:6px;">同一问题的三种讲解模式对照</div>' +
            '<div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;">' +
            compareCol("🧒 儿童", answers.student) +
            compareCol("🧭 游客", answers.tourist) +
            compareCol("📚 研究者", answers.researcher) +
            '</div></div>';
        msgs.appendChild(wrap);
        msgs.scrollTop = msgs.scrollHeight;
    }).catch(() => {
        const t = document.getElementById("compareTyping");
        if (t) t.remove();
        const err = document.createElement("div");
        err.className = "msg agent";
        err.innerHTML = '<div class="av-sm">🆚</div><div class="bubble">模式对照生成失败，请确认后端服务已启动。</div>';
        msgs.appendChild(err);
        msgs.scrollTop = msgs.scrollHeight;
    });
}

function compareCol(title, text) {
    return '<div style="border:1px solid rgba(196,30,58,0.4);border-radius:10px;padding:8px;background:rgba(0,0,0,0.15);">' +
        '<div style="font-weight:bold;color:#FFD700;margin-bottom:4px;">' + title + '</div>' +
        '<div>' + renderMessageHtml(text || "（无）") + '</div></div>';
}

