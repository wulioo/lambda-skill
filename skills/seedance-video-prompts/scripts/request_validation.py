#!/usr/bin/env python3
"""Seedance 2.5 请求的共享确定性校验。"""

from __future__ import annotations

import base64
import json
import re
from pathlib import Path
from urllib.parse import urlparse


MODEL = "dreamina-seedance-2-5-260628"
ALLOWED_TOP_LEVEL = {
    "model", "content", "generate_audio", "ratio", "duration", "resolution",
    "return_last_frame", "watermark", "output_format", "omni_reference_task_type",
}
TYPE_MAP = {"image": "Image", "video": "Video", "audio": "Audio"}
ROLE_MAP = {
    "image": {"reference_image", "first_frame", "last_frame"},
    "video": {"reference_video"},
    "audio": {"reference_audio"},
}
ITEM_KIND = {"image_url": "image", "video_url": "video", "audio_url": "audio"}
TEXT_ITEM_FIELDS = {"type", "text"}
MEDIA_ITEM_FIELDS = {"type", "role"}
MEDIA_BODY_FIELDS = {"url"}
MARKER_RE = re.compile(r"(?<![\w])@(Image|Video|Audio)\s+([1-9]\d*)(?!\d)")
ASSET_ID_RE = re.compile(r"^asset://[A-Za-z0-9][A-Za-z0-9._-]{2,}$")


def valid_locator(value: str, *, allow_fixture: bool = False) -> bool:
    if not value or value.strip() != value:
        return False
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return True
    if allow_fixture and parsed.scheme == "fixture" and (parsed.netloc or parsed.path):
        return True
    if value.startswith("data:"):
        try:
            header, encoded = value.split(",", 1)
            return ";base64" in header and bool(base64.b64decode(encoded, validate=True))
        except (ValueError, TypeError):
            return False
    return bool(ASSET_ID_RE.fullmatch(value))


def marker_set(prompt: str) -> set[tuple[str, int]]:
    return {(kind, int(number)) for kind, number in MARKER_RE.findall(prompt)}


def validate_payload(payload: object, *, allow_fixture: bool = False) -> list[str]:
    errors: list[str] = []
    if not isinstance(payload, dict):
        return ["请求顶层必须是对象"]
    unknown = sorted(set(payload) - ALLOWED_TOP_LEVEL)
    if unknown:
        errors.append(f"请求包含未冻结顶层字段：{unknown}")
    if payload.get("model") != MODEL:
        errors.append(f"model 必须为 {MODEL}")
    content = payload.get("content")
    if not isinstance(content, list):
        return errors + ["content 必须是数组"]
    for index, item in enumerate(content):
        if not isinstance(item, dict):
            errors.append(f"content[{index}] 必须是对象")
            continue
        item_type = item.get("type")
        if item_type == "text":
            unknown_item = sorted(set(item) - TEXT_ITEM_FIELDS)
            if unknown_item:
                errors.append(f"content[{index}] text 含未冻结字段：{unknown_item}")
            continue
        kind = ITEM_KIND.get(item_type)
        if kind is None:
            errors.append(f"content[{index}] type 非法")
            continue
        allowed_item = MEDIA_ITEM_FIELDS | {str(item_type)}
        unknown_item = sorted(set(item) - allowed_item)
        if unknown_item:
            errors.append(f"content[{index}] 媒体项含未冻结字段：{unknown_item}")
        body = item.get(item_type)
        if isinstance(body, dict):
            unknown_body = sorted(set(body) - MEDIA_BODY_FIELDS)
            if unknown_body:
                errors.append(f"content[{index}] {item_type} 含未冻结字段：{unknown_body}")
    text_items = [item for item in content if isinstance(item, dict) and item.get("type") == "text"]
    if len(text_items) != 1 or not isinstance(text_items[0].get("text"), str) or not text_items[0]["text"].strip():
        errors.append("content 必须有且只有一个非空 text")
        prompt = ""
    else:
        prompt = text_items[0]["text"].strip()
    counts = {kind: 0 for kind in TYPE_MAP}
    reference_seconds = {"video": 0.0, "audio": 0.0}
    roles: list[str] = []
    expected_markers: set[tuple[str, int]] = set()
    for index, item in enumerate(content):
        if not isinstance(item, dict) or item.get("type") == "text":
            continue
        item_type = item.get("type")
        kind = ITEM_KIND.get(item_type)
        if kind is None:
            continue
        role = item.get("role")
        if role not in ROLE_MAP[kind]:
            errors.append(f"content[{index}] role 与 {kind} 不匹配")
        body = item.get(item_type)
        locator = body.get("url") if isinstance(body, dict) else None
        if not isinstance(locator, str) or not valid_locator(locator, allow_fixture=allow_fixture):
            errors.append(f"content[{index}] URL/asset ID 不是 HTTPS、Base64 或合法 asset ID")
        counts[kind] += 1
        expected_markers.add((TYPE_MAP[kind], counts[kind]))
        roles.append(str(role))
        if kind in reference_seconds:
            declared = body.get("duration_seconds") if isinstance(body, dict) else None
            if declared is not None:
                if not isinstance(declared, (int, float)) or declared < 2 or declared > 30:
                    errors.append(f"content[{index}] duration_seconds 必须在2—30秒")
                else:
                    reference_seconds[kind] += float(declared)
    actual_markers = marker_set(prompt)
    if actual_markers != expected_markers:
        missing = sorted(expected_markers - actual_markers)
        extra = sorted(actual_markers - expected_markers)
        errors.append(f"提示词参考编号不精确，缺{missing}，多{extra}")
    if counts["image"] > 30 or counts["video"] > 10 or counts["audio"] > 10 or sum(counts.values()) > 50:
        errors.append("参考数量超过 Seedance 2.5 上限")
    if reference_seconds["video"] > 30 or reference_seconds["audio"] > 30:
        errors.append("视频或音频参考总时长超过30秒")
    if roles.count("first_frame") > 1 or roles.count("last_frame") > 1:
        errors.append("first_frame/last_frame 各最多一个")
    if "last_frame" in roles and "first_frame" not in roles:
        errors.append("last_frame 必须同时提供 first_frame")
    if any(role in {"first_frame", "last_frame"} for role in roles) and any(
        role in {"reference_image", "reference_video", "reference_audio"} for role in roles
    ):
        errors.append("严格首/尾帧与 omni reference 素材互斥，不能混用")
    duration = payload.get("duration")
    if not isinstance(duration, (int, float)) or duration < 4 or duration > 30:
        errors.append("duration 必须在4—30秒")
    ratio = payload.get("ratio")
    if any(role in {"first_frame", "last_frame"} for role in roles):
        if ratio != "adaptive":
            errors.append("首尾帧请求 ratio 必须 adaptive")
    elif ratio != "9:16":
        errors.append("当前短剧非首尾帧请求 ratio 必须9:16")
    if payload.get("resolution") not in {"480p", "720p"}:
        errors.append("resolution 只允许480p或720p")
    if not isinstance(payload.get("generate_audio"), bool):
        errors.append("generate_audio 必须显式为布尔值")
    if not isinstance(payload.get("return_last_frame"), bool):
        errors.append("return_last_frame 必须显式为布尔值")
    if not isinstance(payload.get("watermark"), bool):
        errors.append("watermark 必须显式为布尔值")
    if payload.get("output_format") != "mp4":
        errors.append("当前短剧生成请求必须显式设置 output_format=mp4")
    task_type = payload.get("omni_reference_task_type")
    has_omni = any(role in {"reference_image", "reference_video", "reference_audio"} for role in roles)
    if has_omni and task_type != "reference":
        errors.append("omni 短剧生成必须显式设 omni_reference_task_type=reference")
    if not has_omni and task_type is not None:
        errors.append("严格首尾帧请求不得携带 omni_reference_task_type")
    return errors


def load_and_validate(path: Path, *, allow_fixture: bool = False) -> tuple[dict[str, object] | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return None, [f"无法读取请求：{exc}"]
    return payload if isinstance(payload, dict) else None, validate_payload(payload, allow_fixture=allow_fixture)
