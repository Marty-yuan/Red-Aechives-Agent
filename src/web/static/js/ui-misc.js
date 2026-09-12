// ========== 项目框架全屏展示 ==========
document.getElementById("openFrameworkBtn").addEventListener("click", function() {
    document.getElementById("frameworkOverlay").classList.add("open");
});
document.getElementById("frameworkCloseBtn").addEventListener("click", function() {
    document.getElementById("frameworkOverlay").classList.remove("open");
});
document.getElementById("frameworkOverlay").addEventListener("click", function(e) {
    if (e.target && e.target.id === "frameworkOverlay") this.classList.remove("open");
});
document.getElementById("authOverlay").addEventListener("click", function (e) {
    if (e.target && e.target.id === "authOverlay") closeAuth();
});
// ========== 欢迎落地页 ==========
const landingScreen = document.getElementById("landingScreen");
let landingVisible = true;
const LANDING_HIDE_MS = 650;

function enterFromLanding(mode) {
    if (!landingScreen || !landingVisible) return;
    landingVisible = false;
    landingScreen.classList.add("hide");
    setTimeout(() => {
        landingScreen.style.display = "none";
        if (map) map.invalidateSize();
        if (mode === "archive") {
            enterHall();
        } else if (mode === "map") {
            if (routes && routes.length) {
                playRoute(0);
            } else if (map) {
                map.flyTo([25.5, 101.5], 7, { duration: 0.8 });
            }
        } else if (mode === "chat") {
            if (!currentVillage) selectVillage("皎平渡");
            focusChatInput();
        }
    }, LANDING_HIDE_MS);
}

function showWelcome() {
    if (!landingScreen || landingVisible) return;
    landingVisible = true;
    stopRoutePlayback();
    landingScreen.style.display = "flex";
    landingScreen.classList.remove("hide", "landing-in");
    void landingScreen.offsetWidth;
    landingScreen.classList.add("landing-in");
}

// ========== 轻提示 ==========
function showToast(msg, type) {
    type = type || "info";
    let c = document.getElementById("toastContainer");
    if (!c) {
        c = document.createElement("div");
        c.className = "toast-container";
        c.id = "toastContainer";
        document.body.appendChild(c);
    }
    const t = document.createElement("div");
    t.className = "toast " + type;
    t.textContent = msg;
    c.appendChild(t);
    setTimeout(() => { if (t.parentNode) t.parentNode.removeChild(t); }, 3000);
}

refreshUser();
setupAvatar();
setupVoiceButton();
setupPdfOverlay();
initCharacterInteractions();

