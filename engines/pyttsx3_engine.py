"""pyttsx3 后端 — 基于 pyttsx3 的本地离线语音合成。

仅限 Windows 平台（依赖 SAPI5）。
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Tuple

from loguru import logger

from engines.base import TTSEngine


class Pyttsx3Engine(TTSEngine):
    """使用 pyttsx3 将文本合成为 wav/mp3 文件。"""

    name = "pyttsx3"

    def __init__(self, voice: str = "") -> None:
        logger.debug("[TTS.pyttsx3] 初始化, 调用 pyttsx3.init()...")
        import pyttsx3

        self._engine = pyttsx3.init()
        self._voice_id = voice
        if voice:
            self._apply_voice(voice)
        logger.debug("[TTS.pyttsx3] 引擎初始化成功")

    def _apply_voice(self, voice_id: str) -> None:
        """设置 pyttsx3 语音。"""
        try:
            voices = self._engine.getProperty("voices")
            for v in voices:
                if v.id == voice_id or v.name == voice_id:
                    self._engine.setProperty("voice", v.id)
                    self._voice_id = v.id
                    logger.debug("[TTS.pyttsx3] 语音已设置: {}", v.name)
                    return
            logger.warning("[TTS.pyttsx3] 未找到语音: {}, 使用默认", voice_id)
        except Exception as e:
            logger.warning("[TTS.pyttsx3] 设置语音失败: {}", e)

    @staticmethod
    def is_available() -> bool:
        if sys.platform != "win32":
            logger.debug("[TTS.pyttsx3] is_available=False, 非 Windows 平台")
            return False
        try:
            import pyttsx3  # noqa: F401

            logger.debug("[TTS.pyttsx3] is_available=True")
            return True
        except (ImportError, RuntimeError) as e:
            logger.debug("[TTS.pyttsx3] is_available=False: {}", e)
            return False

    @staticmethod
    def list_voices() -> List[Tuple[str, str]]:
        """列出 pyttsx3 所有可用语音。"""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            result = []
            for v in voices:
                lang = ""
                if hasattr(v, "languages") and v.languages:
                    lang = str(v.languages[0]) if v.languages[0] else ""
                display = f"{v.name} ({lang})" if lang else v.name
                result.append((v.id, display, lang))
            engine.stop()
            return result
        except Exception as e:
            logger.warning("[TTS.pyttsx3] list_voices 失败: {}", e)
            return []

    def set_voice(self, voice_id: str) -> None:
        self._apply_voice(voice_id)

    def get_current_voice(self) -> str:
        return self._voice_id

    def synthesize(self, text: str, out_path: Path) -> None:
        logger.debug("[TTS.pyttsx3] 开始合成, 文本长度={}, 输出={}", len(text), out_path)
        self._engine.save_to_file(text, str(out_path))
        self._engine.runAndWait()
        logger.debug("[TTS.pyttsx3] 合成完成: {} ({} bytes)", out_path,
                      out_path.stat().st_size if out_path.exists() else 0)

    def stop(self) -> None:
        logger.debug("[TTS.pyttsx3] stop 调用")
        try:
            self._engine.stop()
        except Exception as e:
            logger.debug("[TTS.pyttsx3] stop 异常: {}", e)

    def cleanup(self) -> None:
        logger.debug("[TTS.pyttsx3] cleanup 开始")
        try:
            self._engine.stop()
        except Exception:
            pass
        self._engine = None  # type: ignore[assignment]
        logger.debug("[TTS.pyttsx3] cleanup 完成")
