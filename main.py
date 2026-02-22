"""TTS 服务插件。

在 NotificationAPI 的 pushed 信号触发时，按通知级别朗读通知内容。
支持三种后端：EdgeTTS / WinSDK / pyttsx3，统一由 QMediaPlayer 播放音频。

特性：
- 动态 TTS 引擎切换
- 自选 Voice
- Activity 自定义朗读文本模板
- 音量调节
"""

from __future__ import annotations

import os
import threading
from typing import Optional

from loguru import logger
from PySide6.QtCore import Signal, Slot

from ClassWidgets.SDK import CW2Plugin, PluginAPI

from announcer import build_announce_text
from config import TTSPluginConfig, DEFAULT_TEMPLATES
from engines import create_engine, list_available_engines, list_voices_for_engine
from speaker import Speaker


class Plugin(CW2Plugin):
    # 通知 QML 刷新的信号
    engineChanged = Signal()
    voiceListChanged = Signal()
    configChanged = Signal()

    def __init__(self, api: PluginAPI) -> None:
        logger.debug("[TTS] Plugin.__init__ 开始")
        super().__init__(api)
        self._config = TTSPluginConfig()
        self._speaker: Optional[Speaker] = None
        self._voice_cache: list = []
        self._voices_loading = False
        logger.debug("[TTS] Plugin.__init__ 完成, 默认引擎配置: {}", self._config.engine)

    # ---- 生命周期 ----------------------------------------------------------

    def on_load(self) -> None:
        logger.info("[TTS] on_load 开始, pid={}", self.meta.get("id"))
        super().on_load()

        # 加载已有配置
        logger.debug("[TTS] 正在加载已持久化的插件配置...")
        self._load_plugin_config()
        logger.debug("[TTS] 配置加载完成, engine={}, voice={}, volume={}",
                     self._config.engine, self._config.voice, self._config.volume)

        # 注册配置模型
        try:
            logger.debug("[TTS] 正在注册配置模型...")
            self.api.config.register_plugin_model(self.pid, self._config)
            logger.debug("[TTS] 配置模型注册成功")
        except Exception as e:
            logger.warning("[TTS] 注册配置模型失败: {}", e)

        # 注册设置页
        self._register_settings_page()

        # 初始化引擎 + 播放器
        self._init_speaker()

        # 连接通知信号
        logger.debug("[TTS] 正在连接 notification.pushed 信号...")
        self.api.notification.pushed.connect(self._on_notification_pushed)
        logger.debug("[TTS] 信号连接完成")

        backend = self._speaker.engine_name if self._speaker else "none"
        logger.info("[TTS] TTS 服务已加载 (backend={})", backend)

    def on_unload(self) -> None:
        logger.info("[TTS] on_unload 开始")
        try:
            self.api.notification.pushed.disconnect(self._on_notification_pushed)
            logger.debug("[TTS] 已断开 notification.pushed 信号")
        except Exception as e:
            logger.debug("[TTS] 断开信号时异常 (可忽略): {}", e)

        if self._speaker is not None:
            logger.debug("[TTS] 正在关闭 Speaker...")
            self._speaker.shutdown()
            self._speaker = None
            logger.debug("[TTS] Speaker 已关闭")

        logger.info("[TTS] TTS 服务已卸载")

    # ---- QML Slots (供前端调用) --------------------------------------------

    @Slot(result=list)
    def getAvailableEngines(self) -> list:
        """返回所有可用引擎列表: [{"name": str, "available": str}, ...]"""
        engines = list_available_engines()
        # 在列表前面加一个 "auto" 选项
        return [{"name": "auto", "available": "true"}] + engines

    @Slot(result=str)
    def getCurrentEngine(self) -> str:
        """返回当前配置的引擎名称。"""
        return self._config.engine

    @Slot(str)
    def setEngine(self, engine_name: str) -> None:
        """切换引擎（会热切换 Speaker）。"""
        logger.info("[TTS] setEngine 调用: {}", engine_name)
        if engine_name == self._config.engine:
            return

        self._config.engine = engine_name
        self._save_config()

        # 热切换引擎
        self._init_speaker()
        self.engineChanged.emit()

        # 切换引擎后清空 voice 缓存
        self._voice_cache = []
        self.voiceListChanged.emit()

    @Slot(result=list)
    def getVoiceList(self) -> list:
        """返回当前引擎可用的语音列表: [{"id": str, "name": str, "locale": str}, ...]"""
        return self._voice_cache

    @Slot()
    def refreshVoiceList(self) -> None:
        """异步刷新当前引擎的语音列表。"""
        if self._voices_loading:
            return
        self._voices_loading = True

        def _worker():
            try:
                engine_name = self._config.engine
                if engine_name == "auto" and self._speaker:
                    engine_name = self._speaker.engine_name
                if not engine_name or engine_name == "auto":
                    self._voice_cache = []
                else:
                    voices = list_voices_for_engine(engine_name)
                    self._voice_cache = [
                        {"id": v[0], "name": v[1], "locale": v[2] if len(v) > 2 else ""}
                        for v in voices
                    ]
                logger.debug("[TTS] 语音列表刷新完成, {} 条", len(self._voice_cache))
            except Exception as e:
                logger.warning("[TTS] 语音列表刷新失败: {}", e)
                self._voice_cache = []
            finally:
                self._voices_loading = False
                self.voiceListChanged.emit()

        threading.Thread(target=_worker, daemon=True).start()

    @Slot(result=str)
    def getCurrentVoice(self) -> str:
        """返回当前配置的语音 ID。"""
        return self._config.voice

    @Slot(str)
    def setVoice(self, voice_id: str) -> None:
        """设置语音并通知引擎。"""
        logger.info("[TTS] setVoice 调用: {}", voice_id)
        self._config.voice = voice_id
        self._save_config()

        if self._speaker and self._speaker.engine:
            self._speaker.engine.set_voice(voice_id)
        self.configChanged.emit()

    @Slot(result=float)
    def getVolume(self) -> float:
        """返回当前音量。"""
        return self._config.volume

    @Slot(float)
    def setVolume(self, volume: float) -> None:
        """设置播放音量 (0.0 ~ 1.0)。"""
        volume = max(0.0, min(1.0, volume))
        logger.debug("[TTS] setVolume: {}", volume)
        self._config.volume = volume
        self._save_config()

        if self._speaker:
            self._speaker.volume = volume
        self.configChanged.emit()

    @Slot(result=list)
    def getTemplateKeys(self) -> list:
        """返回所有可配置的 activity 模板 key。"""
        return list(DEFAULT_TEMPLATES.keys())

    @Slot(str, result=str)
    def getTemplate(self, key: str) -> str:
        """获取指定 activity 的朗读模板。"""
        return self._config.templates.get(key, DEFAULT_TEMPLATES.get(key, ""))

    @Slot(str, str)
    def setTemplate(self, key: str, template: str) -> None:
        """设置指定 activity 的朗读模板。"""
        logger.debug("[TTS] setTemplate: {}={!r}", key, template)
        self._config.templates[key] = template
        self._save_config()
        self.configChanged.emit()

    @Slot(str, result=str)
    def getDefaultTemplate(self, key: str) -> str:
        """获取指定 activity 的默认模板。"""
        return DEFAULT_TEMPLATES.get(key, "")

    @Slot(str)
    def resetTemplate(self, key: str) -> None:
        """重置指定 activity 的模板为默认值。"""
        default = DEFAULT_TEMPLATES.get(key, "")
        self._config.templates[key] = default
        self._save_config()
        self.configChanged.emit()

    @Slot(str)
    def testSpeak(self, text: str) -> None:
        """测试朗读指定文本。"""
        if self._speaker and text:
            self._speaker.speak(text)

    @Slot(result=str)
    def getActiveEngineName(self) -> str:
        """获取实际使用的引擎名称（auto 模式下会显示实际选择的引擎）。"""
        if self._speaker:
            return self._speaker.engine_name
        return "none"

    # ---- 内部方法 ----------------------------------------------------------

    def _init_speaker(self) -> None:
        """初始化或重新初始化 Speaker。"""
        # 先关闭旧 speaker
        if self._speaker is not None:
            self._speaker.shutdown()
            self._speaker = None

        logger.debug("[TTS] 正在创建 TTS 引擎, preference={}, voice={}",
                     self._config.engine, self._config.voice)
        engine = create_engine(self._config.engine, self._config.voice)
        if engine is not None:
            logger.debug("[TTS] 引擎创建成功: {}, 正在初始化 Speaker...", engine.name)
            self._speaker = Speaker(engine, volume=self._config.volume)
            logger.debug("[TTS] Speaker 初始化完成")
        else:
            logger.warning("[TTS] 未能创建任何 TTS 引擎, 语音播报将不可用")

    def _load_plugin_config(self) -> None:
        """从宿主读取已持久化的插件配置。"""
        try:
            model = self.api.config.get_plugin_model(self.pid)
            logger.debug("[TTS] 从宿主获取到配置模型: {}", model)
            if model and hasattr(model, "engine"):
                self._config.engine = str(getattr(model, "engine", "auto") or "auto")
                self._config.voice = str(getattr(model, "voice", "") or "")
                self._config.volume = float(getattr(model, "volume", 1.0) or 1.0)
                saved_templates = getattr(model, "templates", None)
                if isinstance(saved_templates, dict):
                    for key, val in saved_templates.items():
                        self._config.templates[key] = str(val)
                logger.debug("[TTS] 配置已恢复")
            else:
                logger.debug("[TTS] 未找到已保存的配置模型, 使用默认值")
        except Exception as e:
            logger.warning("[TTS] 加载已持久化配置失败: {}", e)

    def _save_config(self) -> None:
        """触发配置持久化。"""
        try:
            if hasattr(self._config, '_on_change') and callable(self._config._on_change):
                self._config._on_change()
        except Exception as e:
            logger.warning("[TTS] 保存配置失败: {}", e)

    def _register_settings_page(self) -> None:
        """注册 QML 设置页面。"""
        try:
            settings_qml = os.path.join(os.path.dirname(__file__), "qml", "settings.qml")
            logger.debug("[TTS] 正在注册设置页: {}", settings_qml)
            self.api.ui.register_settings_page(
                qml_path=settings_qml,
                title="TTS 服务",
                icon="ic_fluent_speaker_2_20_regular",
            )
            logger.debug("[TTS] 设置页注册成功")
        except Exception as e:
            logger.warning("[TTS] 注册设置页失败: {}", e)

    def _on_notification_pushed(self, payload: dict) -> None:
        """通知推送回调。"""
        logger.debug("[TTS] 收到通知推送: provider_id={}, title={!r}, message={!r}",
                      payload.get("provider_id"), payload.get("title"), payload.get("message"))
        if self._speaker is None:
            logger.warning("[TTS] Speaker 为 None, 跳过朗读")
            return

        # 从 RuntimeAPI 获取结构化课程信息，供模板使用
        runtime_context = self._build_runtime_context()

        text = build_announce_text(
            payload,
            templates=self._config.templates,
            runtime_context=runtime_context,
        )
        logger.debug("[TTS] 构建朗读文案: {!r}", text)
        if text:
            self._speaker.speak(text)
        else:
            logger.debug("[TTS] 文案为空, 跳过朗读")

    def _build_runtime_context(self) -> dict:
        """从 RuntimeAPI 提取当前/下一节课程的结构化信息。

        返回字典包含:
          subject, teacher, location       — 当前科目
          next_subject, next_teacher, next_location — 下一节科目
        """
        ctx: dict = {
            "subject": "",
            "teacher": "",
            "location": "",
            "next_subject": "",
            "next_teacher": "",
            "next_location": "",
        }

        try:
            runtime = self.api.runtime

            # 当前科目
            cur_subject = runtime.current_subject
            if cur_subject:
                ctx["subject"] = cur_subject.get("name", "") or ""
                ctx["teacher"] = cur_subject.get("teacher", "") or ""
                ctx["location"] = cur_subject.get("location", "") or ""

            # 当前条目的 title（活动等没有 subject 时回退）
            cur_entry = runtime.current_entry
            if cur_entry and not ctx["subject"]:
                ctx["subject"] = cur_entry.get("title", "") or ""

            # 下一节
            next_entries = runtime.next_entries
            if next_entries:
                next_entry = next_entries[0]
                next_sid = next_entry.get("subjectId")
                # 尝试从 schedule 中查找 subject 详情
                if next_sid:
                    try:
                        schedule_data = self.api.schedule.get()
                        if schedule_data and hasattr(schedule_data, "subjects"):
                            for s in schedule_data.subjects:
                                sd = s.model_dump() if hasattr(s, "model_dump") else s
                                if sd.get("id") == next_sid:
                                    ctx["next_subject"] = sd.get("name", "") or ""
                                    ctx["next_teacher"] = sd.get("teacher", "") or ""
                                    ctx["next_location"] = sd.get("location", "") or ""
                                    break
                    except Exception as e:
                        logger.debug("[TTS] 获取下一节 subject 详情失败: {}", e)

                # 回退到 title
                if not ctx["next_subject"]:
                    ctx["next_subject"] = next_entry.get("title", "") or ""

        except Exception as e:
            logger.warning("[TTS] 获取 runtime 课程信息失败: {}", e)

        logger.debug("[TTS] runtime_context: {}", ctx)
        return ctx
