let currentVillage = null;
let villageMarkers = {};
let villageArmy = {};   // 村寨 -> 所属路线索引
let map;
let soldierMarker = null;
let routes = [];        // 两条路线数据
let soldierPos = { route: 0, idx: 0 };
let soldierLatLng = null;   // 战士当前实际坐标 [lat, lng]
let walkAnimationId = null; // 当前行走动画句柄，避免两段动画同时抢位置
let studyRouteLayer = null;  // 研学路线图层
let routePlayLayer = null;         // 路线播放图层
let routePlayAnimationId = null;   // 路线播放动画句柄
let routePlayActive = false;       // 当前正在播放的路线索引，-1 表示未播放
let routeLegendBtns = [];          // 路线图例按钮引用
let routeLayers = [];              // 每条路线的图层容器（折线+箭头）
let routeWaypoints = [];          // 每条路线的途径点 [{name, latlng, idx, marker, passed}]
let timelineEvents = [];          // 时间轴事件（原始数据）
let timelineItems = [];           // { el, route, village, fraction } 用于路线播放同步
let timelineGroupEls = [];        // 时间轴上的路线分组标签（播放高亮）
let villageCoords = {};           // 村寨 -> { lat, lng }

let voiceEnabled = true;   // 是否开启数字人语音
let currentVoiceAccent = "mandarin";   // mandarin / sichuan
let audioPlayer = new Audio();  // 播放 edge-tts 返回的音频
let activeSpeakBtn = null;      // 当前正在朗读的“朗读”按钮
let villageAvatars = {};        // ?? -> ?? URL
let villageVoiceGenders = {};   // ?? -> male / female
let currentVillageVoiceGender = "female";
let currentUser = null;
let currentMode = "tourist";
const TOKEN_KEY = "red_archive_token";

let memoryToken = "";

function getToken() {
    try {
        return localStorage.getItem(TOKEN_KEY) || memoryToken;
    } catch (e) {
        return memoryToken;
    }
}

function setToken(token) {
    memoryToken = token || "";
    try {
        if (token) {
            localStorage.setItem(TOKEN_KEY, token);
        } else {
            localStorage.removeItem(TOKEN_KEY);
        }
    } catch (e) {
        // 浏览器阻止 localStorage 时，仅保留当前页面内存中的 token
    }
}

function authHeaders() {
    const headers = {"Content-Type": "application/json"};
    const token = getToken();
    if (token) headers["Authorization"] = "Bearer " + token;
    return headers;
}

