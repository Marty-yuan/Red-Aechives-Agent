# -*- coding: utf-8 -*-
"""一次性拆分脚本：把 index.html 的内联 <script>（2911-6399 行）按注释段边界
拆成 static/js/ 下的模块文件，并把 index.html 改写为按原顺序加载的 <script src>。

安全性依据：
- 切分点全部是顶层的 `// ===...===` 段注释行，不切在函数/语句中间；
- 经典 <script> 的顶层 let/const 进入全局词法环境，跨脚本文件可见，
  function 声明挂在全局，因此按原顺序加载语义不变；
- 拆分后用 node --check 逐文件做语法校验。
"""
import io, sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "src" / "web" / "templates" / "index.html"
JS_DIR = ROOT / "src" / "web" / "static" / "js"

# (起始行, 结束行含, 输出文件)  —— 行号基于拆分前的 index.html（1 起始）
SECTIONS = [
    (2912, 2973, "state.js"),      # 全局状态 + token/auth helpers
    (2974, 3358, "map.js"),        # 地图/路线/图层/村寨/时间轴
    (3359, 3699, "walk.js"),       # 行走动画 + 路线播放 + 时间轴同步
    (3700, 3905, "tts.js"),        # 数字人语音
    (3906, 4104, "user.js"),       # 用户画像与长期记忆（含登录注册）
    (4105, 5061, "village.js"),    # 选择村寨/2D 数字人/代言人面板
    (5062, 5203, "chat.js"),       # 发送消息
    (5204, 5558, "kg.js"),         # 知识图谱可视化
    (5559, 5725, "heatmap.js"),    # 客流热力
    (5726, 5798, "ui-misc.js"),    # 项目框架/欢迎页/轻提示
    (5799, 6046, "map3d.js"),      # 3D 地形 + 对话抽屉 + 面板折叠
    (6047, 6398, "hall3d.js"),     # 数字档案馆门厅（Three.js）
]

lines = TPL.read_text(encoding="utf-8").splitlines(keepends=True)

# 基本校验：每个切分起点必须是段注释或全局声明，终点下行必须是段注释或 </script>
for start, end, name in SECTIONS:
    first = lines[start - 1]
    nxt = lines[end] if end < len(lines) else ""
    ok_start = first.lstrip().startswith("//") or start == 2912
    ok_end = nxt.lstrip().startswith("//") or "</script>" in nxt
    if not (ok_start and ok_end):
        print(f"边界校验失败 {name}: start={first!r} next={nxt!r}")
        sys.exit(1)

JS_DIR.mkdir(parents=True, exist_ok=True)
for start, end, name in SECTIONS:
    code = "".join(lines[start - 1:end])
    (JS_DIR / name).write_text(code, encoding="utf-8")
    print(f"  wrote static/js/{name}  ({end - start + 1} 行)")

# 重写 index.html：2911 行 <script> 到 6399 行 </script> 替换为一组 script src
head = lines[:2910]           # 1..2910（含 <script> 前的所有内容）
tail = lines[6399:]           # 6400.. 末尾
tags = [f'<script src="/static/js/{name}"></script>\n' for _, _, name in SECTIONS]
TPL.write_text("".join(head) + "".join(tags) + "".join(tail), encoding="utf-8")
print(f"index.html 重写完成：{len(SECTIONS)} 个模块标签")
