"""EdgeTTS 后端 — 基于 edge_tts 的在线语音合成。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import List, Tuple

from loguru import logger

from engines.base import TTSEngine


class EdgeTTSEngine(TTSEngine):
    """使用 edge_tts 将文本合成为 mp3 文件。"""

    name = "edge"
    DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"

    def __init__(self, voice: str = "zh-CN-XiaoxiaoNeural") -> None:
        self._voice = voice or self.DEFAULT_VOICE
        logger.debug("[TTS.EdgeTTS] 初始化, voice={}", voice)
        import edge_tts

        self._edge_tts = edge_tts
        logger.debug("[TTS.EdgeTTS] edge_tts 模块导入成功")

    @staticmethod
    def is_available() -> bool:
        try:
            import edge_tts  # noqa: F401

            logger.debug("[TTS.EdgeTTS] is_available=True")
            return True
        except ImportError as e:
            logger.debug("[TTS.EdgeTTS] is_available=False, ImportError: {}", e)
            return False

    @staticmethod
    def list_voices() -> List[Tuple[str, str]]:
        """列出 EdgeTTS 所有可用语音。"""
        try:
            import edge_tts
            voices = asyncio.run(edge_tts.list_voices())
            result = []
            for v in voices:
                vid = v["ShortName"]
                locale = v.get("Locale", "")
                display = f"{v['ShortName']} ({locale})"
                result.append((vid, display, locale))
            return result
        except Exception as e:
            logger.warning("[TTS.EdgeTTS] list_voices 失败: {}", e)
            return [("zh-CN-XiaoxiaoNeural", "zh-CN-XiaoxiaoNeural (zh-CN)")]

    def set_voice(self, voice_id: str) -> None:
        self._voice = voice_id or self.DEFAULT_VOICE
        logger.debug("[TTS.EdgeTTS] 语音切换为: {}", self._voice)

    def get_current_voice(self) -> str:
        return self._voice

    def synthesize(self, text: str, out_path: Path) -> None:
        logger.debug("[TTS.EdgeTTS] 开始合成, 文本长度={}, 输出={}", len(text), out_path)
        asyncio.run(self._synthesize_async(text, out_path))

    async def _synthesize_async(self, text: str, out_path: Path) -> None:
        voice = self._voice or self.DEFAULT_VOICE
        communicate = self._edge_tts.Communicate(text=text, voice=voice)
        await communicate.save(str(out_path))
        logger.debug("[TTS.EdgeTTS] 合成完成: {} ({} bytes)", out_path,
                      out_path.stat().st_size if out_path.exists() else 0)
