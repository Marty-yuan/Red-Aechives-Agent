r"""
语音合成模块
------------
优先使用 edge-tts 合成中文/近似西南官话语音。
如果 edge-tts 网络不可用，则回退到 Windows 本地语音（Microsoft Huihui）。
最后返回 None，由前端回退到浏览器 SpeechSynthesis。

安装方式：
    & "D:\agent kf\venv\Scripts\python.exe" -m pip install edge-tts
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

# 不同性别使用不同声线
VOICE_CANDIDATES_MALE = [
    "zh-CN-sichuan-YunxiNeural",
    "zh-CN-YunxiNeural",
]

VOICE_CANDIDATES_FEMALE = [
    "zh-CN-XiaoxiaoNeural",
    "zh-CN-XiaoyiNeural",
]

SPEECH_RATE = "-8%"


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


def synthesize_speech(text: str, gender: str = "female"):
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

    if HAS_EDGE_TTS:
        voices = VOICE_CANDIDATES_MALE if gender == "male" else VOICE_CANDIDATES_FEMALE
        for voice in voices:
            try:
                audio = _synth_with_edge(text, voice)
                if audio:
                    return audio, voice, "audio/mpeg"
            except Exception:
                continue

    # 网络或 edge-tts 不可用时，用 Windows 本地中文语音兜底
    audio = _synth_with_windows_sapi(text, gender=gender)
    if audio:
        return audio, "windows-sapi-zh-CN", "audio/wav"

    return None
