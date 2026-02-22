"""WinRT 后端 — 基于 winrt.windows.media.speechsynthesis 的本地语音合成。

仅限 Windows 平台。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import List, Tuple

from loguru import logger

from engines.base import TTSEngine


class WinRTEngine(TTSEngine):
    """使用 WinRT SpeechSynthesizer 将文本合成为 wav 文件。"""

    name = "winrt"

    def __init__(self, voice: str = "") -> None:
        logger.debug("[TTS.WinRT] 初始化, 导入 SpeechSynthesizer...")
        from winrt.windows.media.speechsynthesis import SpeechSynthesizer

        self._synthesizer = SpeechSynthesizer()
        self._voice_id = voice
        if voice:
            self._apply_voice(voice)
        logger.debug("[TTS.WinRT] SpeechSynthesizer 创建成功")

    def _apply_voice(self, voice_id: str) -> None:
        """根据 voice_id 设置合成器语音。"""
        try:
            from winrt.windows.media.speechsynthesis import SpeechSynthesizer
            all_voices = SpeechSynthesizer.all_voices
            for v in all_voices:
                if v.id == voice_id or v.display_name == voice_id:
                    self._synthesizer.voice = v
                    self._voice_id = voice_id
                    logger.debug("[TTS.WinRT] 语音已设置: {}", v.display_name)
                    return
            logger.warning("[TTS.WinRT] 未找到语音: {}, 使用默认", voice_id)
        except Exception as e:
            logger.warning("[TTS.WinRT] 设置语音失败: {}", e)

    @staticmethod
    def is_available() -> bool:
        if sys.platform != "win32":
            logger.debug("[TTS.WinRT] is_available=False, 非 Windows 平台")
            return False
        try:
            from winrt.windows.media.speechsynthesis import SpeechSynthesizer  # noqa: F401

            logger.debug("[TTS.WinRT] is_available=True")
            return True
        except ImportError as e:
            logger.debug("[TTS.WinRT] is_available=False, ImportError: {}", e)
            return False

    @staticmethod
    def list_voices() -> List[Tuple[str, str]]:
        """列出 WinRT 所有可用语音。"""
        try:
            from winrt.windows.media.speechsynthesis import SpeechSynthesizer
            all_voices = SpeechSynthesizer.all_voices
            result = []
            for v in all_voices:
                result.append((v.id, f"{v.display_name} ({v.language})", v.language))
            return result
        except Exception as e:
            logger.warning("[TTS.WinRT] list_voices 失败: {}", e)
            return []

    def set_voice(self, voice_id: str) -> None:
        self._apply_voice(voice_id)

    def get_current_voice(self) -> str:
        return self._voice_id

    def synthesize(self, text: str, out_path: Path) -> None:
        logger.debug("[TTS.WinRT] 开始合成, 文本长度={}, 输出={}", len(text), out_path)
        asyncio.run(self._synthesize_async(text, out_path))

    async def _synthesize_async(self, text: str, out_path: Path) -> None:
        from winrt.windows.storage.streams import DataReader

        logger.debug("[TTS.WinRT] 调用 synthesize_text_to_stream_async...")
        stream = await self._synthesizer.synthesize_text_to_stream_async(text)
        logger.debug("[TTS.WinRT] 音频流大小: {} bytes", stream.size)

        reader = DataReader(stream.get_input_stream_at(0))
        await reader.load_async(stream.size)
        buf = reader.read_buffer(stream.size)

        out_path.write_bytes(bytes(buf))

        reader.close()
        stream.close()

        logger.debug("[TTS.WinRT] 合成完成: {} ({} bytes)", out_path,
                      out_path.stat().st_size if out_path.exists() else 0)

    def cleanup(self) -> None:
        logger.debug("[TTS.WinRT] cleanup, 释放 SpeechSynthesizer")
        self._synthesizer = None  # type: ignore[assignment]
