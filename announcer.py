"""通知文案构建器 — 基于 provider_id、RuntimeAPI 课程信息和模板。

模板变量:
  {title}    — 通知标题（如 "上课了"）
  {message}  — 通知正文（主程序已拼好的文本）
  {subject}  — 当前科目名称（来自 RuntimeAPI）
  {teacher}  — 教师姓名（来自 RuntimeAPI，可能为空）
  {location} — 上课地点（来自 RuntimeAPI，可能为空）
"""

from __future__ import annotations

from typing import Dict, Optional

from loguru import logger

from config import DEFAULT_TEMPLATES

# provider_id 后缀到 activity key 的映射
_PROVIDER_SUFFIX_MAP = {
    ".class": "class",
    ".activity": "activity",
    ".break": "break",
    ".free": "free",
    ".preparation": "preparation",
}


def _resolve_activity_key(provider_id: str) -> Optional[str]:
    """从 provider_id 解析出 activity 类型 key。

    例如: "com.classwidgets.schedule.runtime.class" → "class"
    """
    if not provider_id:
        return None
    for suffix, key in _PROVIDER_SUFFIX_MAP.items():
        if provider_id.endswith(suffix):
            return key
    return None


def build_announce_text(
    payload: dict,
    templates: Optional[Dict[str, str]] = None,
    runtime_context: Optional[dict] = None,
) -> Optional[str]:
    """根据通知 payload 和模板构建朗读文案。

    :param payload: NotificationAPI.pushed 信号传递的字典
    :param templates: 自定义模板字典 {activity_key: template_str}
    :param runtime_context: 来自 RuntimeAPI 的课程上下文，可包含:
        - subject: 科目名称
        - teacher: 教师
        - location: 上课地点
        - next_subject: 下一节科目名称
        - next_teacher: 下一节教师
        - next_location: 下一节地点
    :return: 朗读文本，无需朗读时返回 None
    """
    logger.debug("[TTS.Announcer] 收到 payload: keys={}", list(payload.keys()))

    provider_id = (payload.get("provider_id") or "").strip()
    title = (payload.get("title") or "").strip()
    message = (payload.get("message") or "").strip()

    logger.debug("[TTS.Announcer] provider_id={!r}, title={!r}, message={!r}",
                 provider_id, title, message)

    # 从 runtime_context 提取结构化课程信息
    ctx = runtime_context or {}
    subject = ctx.get("subject", "")
    teacher = ctx.get("teacher", "")
    location = ctx.get("location", "")
    next_subject = ctx.get("next_subject", "")
    next_teacher = ctx.get("next_teacher", "")
    next_location = ctx.get("next_location", "")

    logger.debug("[TTS.Announcer] runtime_context: subject={!r}, teacher={!r}, "
                 "location={!r}, next_subject={!r}",
                 subject, teacher, location, next_subject)

    # 解析 activity 类型
    activity_key = _resolve_activity_key(provider_id)
    logger.debug("[TTS.Announcer] activity_key={!r}", activity_key)

    if activity_key:
        # 使用模板
        tmpl_dict = templates if templates else DEFAULT_TEMPLATES
        template = tmpl_dict.get(activity_key, "")
        if not template:
            template = DEFAULT_TEMPLATES.get(activity_key, "{title}。{message}")

        try:
            result = template.format(
                title=title,
                message=message,
                subject=subject,
                teacher=teacher,
                location=location,
                next_subject=next_subject,
                next_teacher=next_teacher,
                next_location=next_location,
            )
            # 清理多余的标点
            result = result.strip("。，, .")
            result = result.strip()
        except (KeyError, IndexError) as e:
            logger.warning("[TTS.Announcer] 模板格式化失败: {}, 回退", e)
            result = f"{title}。{message}" if message else title

        logger.debug("[TTS.Announcer] 模板构建结果: {!r}", result)
        return result if result else None

    # 非日程类通知 — 直接拼接 title + message
    if title and message:
        result = f"{title}。{message}"
    else:
        result = title or message or None
    logger.debug("[TTS.Announcer] 通用构建结果: {!r}", result)
    return result
