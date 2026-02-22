"""TTS 引擎注册与工厂。"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple, Type

from loguru import logger

from engines.base import TTSEngine
from engines.edge import EdgeTTSEngine
from engines.pyttsx3_engine import Pyttsx3Engine
from engines.winsdk_engine import WinRTEngine

# 按优先级排列的引擎列表
ENGINE_REGISTRY: List[Type[TTSEngine]] = [
    EdgeTTSEngine,
    WinRTEngine,
    Pyttsx3Engine,
]


def create_engine(preference: str = "auto", voice: str = "") -> Optional[TTSEngine]:
    """根据偏好创建 TTS 引擎实例。

    :param preference: "auto" 按优先级自动选择，或指定引擎名称
    :param voice: 语音标识符，空字符串使用默认
    :return: TTSEngine 实例，全部不可用时返回 None
    """
    logger.debug("[TTS.Engine] create_engine 调用, preference={}, voice={}", preference, voice)
    logger.debug("[TTS.Engine] 已注册引擎: {}", [cls.name for cls in ENGINE_REGISTRY])

    if preference != "auto":
        for cls in ENGINE_REGISTRY:
            if cls.name == preference:
                logger.debug("[TTS.Engine] 检查指定引擎 {} 可用性...", cls.name)
                if cls.is_available():
                    logger.info("[TTS.Engine] TTS 引擎已选择: {}", cls.name)
                    try:
                        instance = cls(voice=voice) if voice else cls()
                        logger.debug("[TTS.Engine] 引擎 {} 实例化成功", cls.name)
                        return instance
                    except Exception as e:
                        logger.error("[TTS.Engine] 引擎 {} 实例化失败: {}", cls.name, e)
                        return None
                logger.warning("[TTS.Engine] TTS 引擎 {} 不可用", cls.name)
                return None
        logger.warning("[TTS.Engine] 未知的 TTS 引擎: {}", preference)
        return None

    # auto：按优先级依次尝试
    for cls in ENGINE_REGISTRY:
        logger.debug("[TTS.Engine] 自动模式: 尝试引擎 {} ...", cls.name)
        if cls.is_available():
            logger.info("[TTS.Engine] TTS 引擎自动选择: {}", cls.name)
            try:
                instance = cls(voice=voice) if voice else cls()
                logger.debug("[TTS.Engine] 引擎 {} 实例化成功", cls.name)
                return instance
            except Exception as e:
                logger.error("[TTS.Engine] 引擎 {} 实例化失败: {}", cls.name, e)
                continue
        else:
            logger.debug("[TTS.Engine] 引擎 {} 不可用, 跳过", cls.name)

    logger.warning("[TTS.Engine] 没有可用的 TTS 引擎")
    return None


def list_available_engines() -> List[Dict[str, str]]:
    """列出所有可用的引擎。

    :return: [{"name": engine_name, "available": "true"/"false"}, ...]
    """
    result = []
    for cls in ENGINE_REGISTRY:
        available = False
        try:
            available = cls.is_available()
        except Exception:
            pass
        result.append({"name": cls.name, "available": str(available).lower()})
    return result


def list_voices_for_engine(engine_name: str) -> List[Tuple[str, str]]:
    """列出指定引擎的所有可用语音。

    :return: [(voice_id, display_name), ...]
    """
    for cls in ENGINE_REGISTRY:
        if cls.name == engine_name:
            try:
                return cls.list_voices()
            except Exception as e:
                logger.warning("[TTS.Engine] 列出 {} 语音失败: {}", engine_name, e)
                return []
    return []


__all__ = [
    "TTSEngine",
    "EdgeTTSEngine",
    "WinRTEngine",
    "Pyttsx3Engine",
    "ENGINE_REGISTRY",
    "create_engine",
    "list_available_engines",
    "list_voices_for_engine",
]
