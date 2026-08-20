r"""
语音合成模块
------------
优先使用 edge-tts 合成中文/近似西南官话语音。
如果 edge-tts 网络不可用，则回退到 Windows 本地语音（Microsoft Huihui）。
最后返回 None，由前端回退到浏览器 SpeechSynthesis。

安装方式：
    python -m pip install edge-tts
"""
import asyncio
import os
import subprocess
import tempfile

try:
    import edge_tts
    HAS_EDGE_TTS = True
except Exception:
    edge_tts = None
    HAS_EDGE_TTS = False

# 普通话版声线：
#   男声：YunxiNeural / YunjianNeural
#   女声：XiaoxiaoNeural / XiaoyiNeural
# 后续方言版可在这里加入 zh-CN-sichuan-YunxiNeural 等口音声线，并在 synthesize_speech 中按村寨切换。
VOICE_CANDIDATES = {
    "mandarin": {
        "male": ["zh-CN-YunxiNeural", "zh-CN-YunjianNeural"],
        "female": ["zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural"],
    },
    "sichuan": {
        # edge-tts 没有四川话口音声线，这里用普通话声线朗读“川味改写文本”。
        "male": ["zh-CN-YunxiNeural", "zh-CN-YunjianNeural"],
        "female": ["zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural"],
    },
}

SPEECH_RATE = "-8%"

SICHUAN_REPLACEMENTS = [
    ("什么", "啥子"),
    ("为什么", "为啥子"),
    ("没有", "没得"),
    ("是不是", "是不是嘛"),
    ("好的", "要得"),
    ("谢谢", "多谢"),
    ("非常", "硬是"),
]


def _sichuan_style_text(text: str) -> str:
    """把普通话文本做轻度川味改写，用于当前缺少真实四川话声线时的演示。"""
    result = text
    for src, dst in SICHUAN_REPLACEMENTS:
        result = result.replace(src, dst)

    if not result:
        return result

    last = result[-1]
    if last in "。！？!?~～":
        result = result[:-1] + "嘛" + last
    else:
        result += "嘛"
    return result


def _synth_with_edge(text: str, voice: str):
    """用 edge-tts 指定声音合成 mp3，返回二进制内容。"""
    tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        communicate = edge_tts.Communicate(
            text,
            voice=voice,
            rate=SPEECH_RATE,
            pitch="+0Hz",
            volume="+0%",
        )
        asyncio.run(communicate.save(tmp_path))

        with open(tmp_path, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _synth_with_windows_sapi(text: str, gender: str = "female"):
    """使用 Windows 本地中文语音合成 wav。"""
    text_path = None
    wav_path = None
    script_path = None

    try:
        # 把中文文本写入临时文件，避免命令行编码问题
        text_file = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
        text_file.write(text)
        text_file.close()
        text_path = text_file.name

        wav_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        wav_path = wav_file.name
        wav_file.close()

        ps_gender = "Male" if gender == "male" else "Female"
        script = f'''
Add-Type -AssemblyName System.Speech
$text = [IO.File]::ReadAllText('{text_path}', [Text.Encoding]::UTF8)
$gender = '{ps_gender}'
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$wantGender = 'Male'
if ($gender -eq 'female') {{ $wantGender = 'Female' }}
$voice = $synth.GetInstalledVoices() | Where-Object {{ $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN' -and $_.VoiceInfo.Gender -eq $wantGender }} | Select-Object -First 1
if (-not $voice) {{ $voice = $synth.GetInstalledVoices() | Where-Object {{ $_.Enabled -and $_.VoiceInfo.Culture.Name -eq 'zh-CN' }} | Select-Object -First 1 }}
if ($voice) {{ $synth.SelectVoice($voice.VoiceInfo.Name) }}
$synth.Rate = -2
$synth.SetOutputToWaveFile('{wav_path}')
$synth.Speak($text)
$synth.Dispose()
'''

        script_file = tempfile.NamedTemporaryFile("w", suffix=".ps1", delete=False, encoding="utf-8")
        script_file.write(script)
        script_file.close()
        script_path = script_file.name

        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", script_path],
            capture_output=True,
            timeout=30,
            check=True,
        )

        with open(wav_path, "rb") as f:
            audio = f.read()
        return audio if audio else None
    except Exception:
        return None
    finally:
        for path in (text_path, wav_path, script_path):
            if path:
                try:
                    os.unlink(path)
                except OSError:
                    pass


def synthesize_speech(text: str, gender: str = "female", accent: str = "mandarin"):
    """
    把文字合成为语音。

    返回:
        (audio_bytes, voice_name, mime_type)
        如果 TTS 不可用，返回 None。
    """
    text = (text or "").strip()
    if not text:
        return None

    text = text[:500]
    accent = accent if accent in VOICE_CANDIDATES else "mandarin"
    speech_text = _sichuan_style_text(text) if accent == "sichuan" else text

    if HAS_EDGE_TTS:
        preset = VOICE_CANDIDATES[accent]
        voices = preset["male" if gender == "male" else "female"]
        for voice in voices:
            try:
                audio = _synth_with_edge(speech_text, voice)
                if audio:
                    return audio, voice, "audio/mpeg"
            except Exception:
                continue

    # 网络或 edge-tts 不可用时，用 Windows 本地中文语音兜底
    audio = _synth_with_windows_sapi(speech_text, gender=gender)
    if audio:
        return audio, "windows-sapi-zh-CN", "audio/wav"

    return None
