// ========== 数字人语音 ==========
function setupAvatar() {
    const img = document.getElementById("avatarImg");
    const fallback = document.getElementById("avatarFallback");

    img.onload = function () {
        img.style.display = "block";
        fallback.style.display = "none";
    };

    img.onerror = function () {
        if (!img.dataset.triedSoldier) {
            img.dataset.triedSoldier = "1";
            img.src = "/static/soldier.png";
        } else {
            img.style.display = "none";
            fallback.style.display = "flex";
        }
    };
}

function setVillageAvatar(name) {
    const img = document.getElementById("avatarImg");
    const fallback = document.getElementById("avatarFallback");
    if (!img) return;

    const avatarUrl = villageAvatars[name] || "/static/soldier.png";
    img.dataset.triedSoldier = "";
    img.src = avatarUrl;
    img.onload = function () {
        img.style.display = "block";
        fallback.style.display = "none";
    };
    img.onerror = function () {
        if (!img.dataset.triedSoldier) {
            img.dataset.triedSoldier = "1";
            img.src = "/static/soldier.png";
        } else {
            img.style.display = "none";
            fallback.style.display = "flex";
        }
    };
}

function setSpeaking(speaking) {
    const wrap = document.getElementById("avatarWrap");
    if (wrap) wrap.classList.toggle("speaking", speaking);
}

function stopAudio() {
    audioPlayer.pause();
    audioPlayer.currentTime = 0;
    if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
    }
}

const ICON_VOL = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>';
const ICON_STOP = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><rect x="5" y="5" width="14" height="14" rx="2"/></svg>';
const ICON_USER = '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="M19 21v-2a4 4 0 0 0-4-4H9a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>';

function resetSpeakBtn(btn) {
    if (!btn) return;
    btn.classList.remove("playing");
    btn.innerHTML = ICON_VOL + " 朗读";
    if (activeSpeakBtn === btn) activeSpeakBtn = null;
    setSpeaking(false);
}

async function speakAnswer(text, btn) {
    const raw = String(text || "").trim();
    if (!raw) return;
    // 正在朗读这条回答 -> 再点一次停止
    if (activeSpeakBtn === btn) {
        stopAudio();
        resetSpeakBtn(btn);
        return;
    }
    stopAudio();
    if (activeSpeakBtn) resetSpeakBtn(activeSpeakBtn);

    btn.classList.add("playing");
    btn.innerHTML = ICON_STOP + " 停止";
    activeSpeakBtn = btn;
    setSpeaking(true);

    try {
        const response = await fetch("/api/tts", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                text: plainTextForSpeech(raw),
                village: currentVillage || "",
                gender: currentVillageVoiceGender,
                accent: "mandarin"
            })
        });
        if (response.ok) {
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            audioPlayer.src = url;
            audioPlayer.onended = () => { URL.revokeObjectURL(url); resetSpeakBtn(btn); };
            audioPlayer.onerror = () => { URL.revokeObjectURL(url); resetSpeakBtn(btn); browserSpeak(raw); };
            try {
                await audioPlayer.play();
            } catch (e) {
                resetSpeakBtn(btn);
                browserSpeak(raw);
            }
        } else {
            resetSpeakBtn(btn);
            browserSpeak(raw);
        }
    } catch (e) {
        resetSpeakBtn(btn);
        browserSpeak(raw);
    }
}

function browserSpeak(text) {
    if (!("speechSynthesis" in window)) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "zh-CN";
    utterance.rate = 0.95;
    utterance.volume = 1;

    // ????????????????????????????
    const voices = window.speechSynthesis.getVoices();
    const zhVoice = voices.find(v => v.lang && v.lang.toLowerCase().startsWith("zh"));
    if (zhVoice) utterance.voice = zhVoice;

    utterance.onend = () => setSpeaking(false);
    utterance.onerror = () => setSpeaking(false);
    window.speechSynthesis.speak(utterance);
}

async function speak(text) {
    if (!voiceEnabled || !text) return;
    stopAudio();
    setSpeaking(true);

    try {
        const response = await fetch("/api/tts", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                text: text,
                village: currentVillage || "",
                gender: currentVillageVoiceGender,
                accent: currentVoiceAccent
            })
        });

        if (response.ok) {
            const blob = await response.blob();
            const url = URL.createObjectURL(blob);
            audioPlayer.src = url;
            audioPlayer.onended = () => {
                setSpeaking(false);
                URL.revokeObjectURL(url);
            };
            audioPlayer.onerror = () => {
                URL.revokeObjectURL(url);
                browserSpeak(text);
            };
            try {
                await audioPlayer.play();
            } catch (e) {
                browserSpeak(text);
            }
        } else {
            browserSpeak(text);
        }
    } catch (e) {
        setSpeaking(false);
        browserSpeak(text);
    }
}

function syncVoiceButtons() {
    document.querySelectorAll(".voice-btn").forEach(btn => {
        const mode = btn.dataset.voice || "";
        if (mode === "off") {
            btn.classList.toggle("active", !voiceEnabled);
        } else {
            btn.classList.toggle("active", voiceEnabled && mode === currentVoiceAccent);
        }
    });
}

function setVoice(mode) {
    if (mode === "off") {
        voiceEnabled = false;
    } else {
        voiceEnabled = true;
        currentVoiceAccent = mode === "sichuan" ? "sichuan" : "mandarin";
    }
    stopAudio();
    setSpeaking(false);
    syncVoiceButtons();
}

function setupVoiceButton() {
    syncVoiceButtons();
}

