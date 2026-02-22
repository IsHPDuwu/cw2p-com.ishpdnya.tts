"""朗读调度器 — 合成 + QMediaPlayer 播放。"""

from __future__ import annotations

import tempfile
import threading
import uuid
from pathlib import Path
from typing import Optional

from loguru import logger
from PySide6.QtCore import QUrl, QEventLoop, QTimer
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput

from engines.base import TTSEngine


class Speaker:
    """管理 TTS 合成与 QMediaPlayer 音频播放。

    所有引擎的合成产物都通过 Qt Multimedia 统一播放，
    无需额外依赖（如 pygame），与主程序技术栈一致。
    """

    def __init__(self, engine: TTSEngine, volume: float = 1.0) -> None:
        self._engine = engine
        self._volume = max(0.0, min(1.0, volume))
        self._lock = threading.Lock()
        self._stopped = False

        # QMediaPlayer 实例（在主线程创建，播放也在主线程）
        self._player: Optional[QMediaPlayer] = None
        self._audio_output: Optional[QAudioOutput] = None
        self._init_player()

        logger.debug("[TTS.Speaker] 初始化完成, engine={}, volume={}", engine.name, self._volume)

    def _init_player(self) -> None:
        """初始化 QMediaPlayer + QAudioOutput。"""
        self._player = QMediaPlayer()
        self._audio_output = QAudioOutput()
        self._audio_output.setVolume(self._volume)
        self._player.setAudioOutput(self._audio_output)
        # 播放完毕后清理临时文件
        self._player.playbackStateChanged.connect(self._on_playback_state_changed)
        self._pending_cleanup: Optional[Path] = None

    def _on_playback_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        """播放结束后清理临时文件。"""
        if state == QMediaPlayer.PlaybackState.StoppedState:
            if self._pending_cleanup is not None:
                tmp = self._pending_cleanup
                self._pending_cleanup = None
                try:
                    # 延迟一点删除，确保文件句柄已释放
                    QTimer.singleShot(1500, lambda: self._safe_unlink(tmp))
                except Exception:
                    pass

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
            logger.debug("[TTS.Speaker] 临时文件已清理: {}", path)
        except Exception as e:
            logger.warning("[TTS.Speaker] 清理临时文件失败: {}", e)

    @property
    def engine_name(self) -> str:
        return self._engine.name

    @property
    def engine(self) -> TTSEngine:
        return self._engine

    @property
    def volume(self) -> float:
        return self._volume

    @volume.setter
    def volume(self, value: float) -> None:
        self._volume = max(0.0, min(1.0, value))
        if self._audio_output is not None:
            self._audio_output.setVolume(self._volume)
        logger.debug("[TTS.Speaker] 音量已设置: {}", self._volume)

    # ---- public API --------------------------------------------------------

    def speak(self, text: str) -> None:
        """在后台线程中合成，然后回主线程播放。"""
        if self._stopped:
            logger.debug("[TTS.Speaker] speak() 被调用但已停止, 跳过")
            return
        logger.debug("[TTS.Speaker] 启动后台线程朗读: {!r}", text[:80])
        threading.Thread(target=self._speak_worker, args=(text,), daemon=True).start()

    def swap_engine(self, new_engine: TTSEngine) -> None:
        """热切换 TTS 引擎。"""
        logger.debug("[TTS.Speaker] 切换引擎: {} -> {}", self._engine.name, new_engine.name)
        old = self._engine
        self._engine = new_engine
        try:
            old.stop()
            old.cleanup()
        except Exception as e:
            logger.debug("[TTS.Speaker] 旧引擎清理异常: {}", e)

    def shutdown(self) -> None:
        """停止播放并释放所有资源。"""
        logger.debug("[TTS.Speaker] shutdown 开始")
        self._stopped = True
        self._engine.stop()

        if self._player is not None:
            try:
                self._player.stop()
                logger.debug("[TTS.Speaker] QMediaPlayer 已停止")
            except Exception as e:
                logger.warning("[TTS.Speaker] 停止 QMediaPlayer 时异常: {}", e)

        self._engine.cleanup()
        logger.debug("[TTS.Speaker] shutdown 完成")

    # ---- internal ----------------------------------------------------------

    def _speak_worker(self, text: str) -> None:
        """合成音频文件（后台线程），然后调用主线程播放。"""
        tmp_path: Optional[Path] = None
        try:
            suffix = ".mp3" if self._engine.name == "edge" else ".wav"
            tmp_path = Path(tempfile.gettempdir()) / f"cw2_tts_{self._engine.name}_{uuid.uuid4().hex}{suffix}"
            logger.debug("[TTS.Speaker] 临时文件路径: {}", tmp_path)

            # 1. 合成（在后台线程）
            logger.debug("[TTS.Speaker] 开始合成, 文本长度={}", len(text))
            self._engine.synthesize(text, tmp_path)
            logger.debug("[TTS.Speaker] 合成完成, 文件大小={} bytes",
                         tmp_path.stat().st_size if tmp_path.exists() else 0)

            if self._stopped:
                logger.debug("[TTS.Speaker] 合成后发现已停止, 跳过播放")
                return

            # 2. 在主线程播放（QMediaPlayer 必须在创建它的线程操作）
            logger.debug("[TTS.Speaker] 请求主线程播放音频...")
            self._play(tmp_path)
            logger.debug("[TTS.Speaker] 播放已启动")

        except Exception as e:
            logger.error("[TTS.Speaker] TTS 朗读失败: {}", e)
            logger.exception(e)
            # 合成失败时直接清理
            if tmp_path is not None:
                self._safe_unlink(tmp_path)

    def _play(self, audio_path: Path) -> None:
        """通过 QMediaPlayer 播放音频文件。

        临时文件的清理由 playbackStateChanged 信号回调处理。
        """
        if self._player is None:
            logger.warning("[TTS.Speaker] QMediaPlayer 未初始化, 跳过播放")
            return

        # 先停止上一次播放
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.stop()

        self._pending_cleanup = audio_path
        self._audio_output.setVolume(self._volume)

        logger.debug("[TTS.Speaker] 加载音频: {}", audio_path)
        self._player.setSource(QUrl.fromLocalFile(str(audio_path)))
        self._player.play()
