#!/usr/bin/env python3
"""校验冻结分镜、真实参考、请求、产物、POST 与粗剪之间的证据链。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from request_validation import marker_set, validate_payload, valid_locator


GEN_RE = re.compile(r"GEN-EP\d{3}-\d{3}(?:-\d+)?@r\d+")
SHOT_RE = re.compile(r"SHOT-EP\d{3}-\d{3}@r\d+")
REF_RE = re.compile(r"REF-ASSET-[A-Z0-9-]+@r\d+")
HASH_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
RANGE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[—-]\s*(\d+(?:\.\d+)?)")
MEDIA_RE = re.compile(r"^(\d+)x(\d+)/(png|jpe?g|webp)$", re.I)


def cells(line: str) -> list[str]:
    if not line.lstrip().startswith("|"):
        return []
    return [item.strip() for item in line.strip().strip("|").split("|")]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def resolve_file(root: Path, value: str) -> Path:
    path = Path(value).expanduser()
    return path if path.is_absolute() else root / path


def inspect_media(path: Path) -> tuple[float, int, int, bool] | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        videos = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"]
        audios = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"]
        if not videos:
            return None
        return (
            float(data.get("format", {}).get("duration", 0)),
            int(videos[0].get("width", 0)),
            int(videos[0].get("height", 0)),
            bool(audios),
        )
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def inspect_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    try:
        duration = float(json.loads(result.stdout).get("format", {}).get("duration", 0))
        return duration if duration > 0 else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def inspect_audio_duration(path: Path) -> float | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
        if audio is None:
            return None
        value = audio.get("duration") or data.get("format", {}).get("duration")
        duration = float(value or 0)
        return duration if duration > 0 else None
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def inspect_image_size(path: Path) -> tuple[int, int] | None:
    if not shutil.which("ffprobe"):
        return None
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries", "stream=width,height", "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        stream = json.loads(result.stdout).get("streams", [])[0]
        width, height = int(stream["width"]), int(stream["height"])
        return (width, height) if width > 0 and height > 0 else None
    except (IndexError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def seconds_range(value: str) -> tuple[float, float] | None:
    match = RANGE_RE.search(value)
    if not match:
        return None
    return float(match.group(1)), float(match.group(2))


def valid_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "T" in value
    except ValueError:
        return False


def approval_contains(path: Path, key: str, digest: str, *, character: str | None = None) -> bool:
    if not path.is_file():
        return False
    for line in path.read_text(encoding="utf-8").splitlines():
        row = cells(line)
        if not row or row[0] != key or digest.lower() not in {item.lower() for item in row} or row[-1] != "accepted":
            continue
        if character is not None:
            if len(row) != 7 or row[1] != character or not row[4] or not valid_iso8601(row[5]):
                continue
        elif len(row) == 6 and (not row[3] or not valid_iso8601(row[4])):
            continue
        return True
    return False


def valid_submission_chain(
    records: list[dict[str, object]], task_id: str, digest: str,
    media_path: str, media_hash: str, request_path: str,
    model: str, authorized_by: str,
) -> bool:
    expected_request = str(Path(request_path).expanduser().resolve())
    expected_media = str(Path(media_path).expanduser().resolve())
    matching = [
        (index, record) for index, record in enumerate(records)
        if str(record.get("request_sha256", "")).lower() == digest.lower()
    ]
    task_submissions = [
        item for item in matching
        if item[1].get("event") == "submit_result" and item[1].get("state") == "submitted"
        and item[1].get("task_id") == task_id
    ]
    task_archives = [
        item for item in matching
        if item[1].get("event") == "archive_result" and item[1].get("archive_state") == "archived"
        and item[1].get("task_id") == task_id
    ]
    if len(task_submissions) != 1 or len(task_archives) != 1:
        return False
    reservation_ids = {
        str(record.get("reservation_id")) for _index, record in matching
        if record.get("event") == "reservation" and record.get("reservation_id")
    }
    for reservation_id in reservation_ids:
        chain = [(index, record) for index, record in matching if str(record.get("reservation_id")) == reservation_id]
        reservations = [item for item in chain if item[1].get("event") == "reservation" and item[1].get("state") == "reserved"]
        submissions = [
            item for item in chain
            if item[1].get("event") == "submit_result" and item[1].get("state") == "submitted"
            and item[1].get("task_id") == task_id
        ]
        archives = []
        for item in chain:
            record = item[1]
            archive = record.get("archive")
            if not isinstance(archive, dict):
                continue
            if (
                record.get("event") == "archive_result" and record.get("state") == "succeeded"
                and record.get("archive_state") == "archived" and record.get("task_id") == task_id
                and str(Path(str(archive.get("path", ""))).expanduser().resolve()) == expected_media
                and str(archive.get("sha256", "")).lower() == media_hash.lower()
                and str(archive.get("request_sha256", "")).lower() == digest.lower()
            ):
                archives.append(item)
        if len(reservations) != 1 or len(submissions) != 1 or len(archives) != 1:
            continue
        reservation, submission, archived = reservations[0], submissions[0], archives[0]
        if not (reservation[0] < submission[0] < archived[0]):
            continue
        events = [reservation[1], submission[1], archived[1]]
        if not all(
            str(Path(str(event.get("request", ""))).expanduser().resolve()) == expected_request
            and event.get("model") == model
            and event.get("authorized_by") == authorized_by
            for event in events
        ):
            continue
        if not all(valid_iso8601(str(event.get(field, ""))) for event, field in (
            (reservation[1], "reserved_at"),
            (submission[1], "submitted_at"),
            (archived[1], "recorded_at"),
        )):
            continue
        return True
    return False


def authorization_approver(text: str, request_path: Path, digest: str, model: str) -> str | None:
    for line in text.splitlines():
        row = cells(line)
        if len(row) != 7 or row[-1] != "accepted":
            continue
        request_value, approved_hash, approved_model, limit, approver, approved_at, _status = row
        same_request = request_value in {request_path.name, str(request_path.resolve())}
        if (
            same_request and approved_hash.lower() == digest.lower() and approved_model == model
            and limit.isdigit() and int(limit) > 0 and approver and valid_iso8601(approved_at)
        ):
            return approver
    return None


def production_contract(storyboard: Path) -> tuple[dict, dict, set[str], dict, list[str]]:
    gens: dict[str, dict] = {}
    shots: dict[str, dict] = {}
    posts: set[str] = set()
    episodes: dict[str, dict] = {}
    errors: list[str] = []
    for path in sorted((storyboard / "episodes").glob("EP*-production.md")):
        text = path.read_text(encoding="utf-8")
        episode = path.stem.split("-", 1)[0]
        target = re.search(r"^- target_episode_seconds：(\d+(?:\.\d+)?)$", text, re.M)
        tolerance = re.search(r"^- allowed_tolerance_seconds：(\d+(?:\.\d+)?)$", text, re.M)
        profile_hash = re.search(r"^- capability_profile_sha256：([0-9a-fA-F]{64})$", text, re.M)
        episodes[episode] = {
            "path": path,
            "hash": file_hash(path),
            "target": float(target.group(1)) if target else 0.0,
            "tolerance": float(tolerance.group(1)) if tolerance else -1.0,
            "profile_hash": profile_hash.group(1).lower() if profile_hash else "",
        }
        headings = list(re.finditer(r"^###\s+(SHOT-EP\d{3}-\d{3}@r\d+)$", text, re.M))
        for index, match in enumerate(headings):
            shot = match.group(1)
            end = headings[index + 1].start() if index + 1 < len(headings) else text.find("\n## 生成单元", match.end())
            section = text[match.start(): end if end >= 0 else len(text)]
            duration = re.search(r"^- 目标剪辑时长：(\d+(?:\.\d+)?)秒$", section, re.M)
            if shot in shots:
                errors.append(f"{path}: SHOT 重复 {shot}")
            shots[shot] = {
                "episode": episode,
                "duration": float(duration.group(1)) if duration else 0.0,
                "refs": set(REF_RE.findall(section)),
            }
        posts.update(re.findall(r"\bPOST-EP\d{3}-\d{3}@r\d+\b", text))
        for number, line in enumerate(text.splitlines(), 1):
            row = cells(line)
            if len(row) != 8 or not GEN_RE.fullmatch(row[0]):
                continue
            gen, shot, edit, material, trim, _frames, refs_text, status = row
            if gen in gens:
                errors.append(f"{path}:{number}: GEN 重复 {gen}")
                continue
            try:
                edit_s, material_s = float(edit), float(material)
            except ValueError:
                errors.append(f"{path}:{number}: GEN 时长非法 {gen}")
                continue
            gens[gen] = {
                "shot": shot,
                "edit": edit_s,
                "material": material_s,
                "trim": trim,
                "refs": set(REF_RE.findall(refs_text)),
                "status": status,
                "episode": episode,
            }
    return gens, shots, posts, episodes, errors


def accepted_assets(root: Path) -> tuple[dict[str, dict], list[str]]:
    records: dict[str, dict] = {}
    errors: list[str] = []
    manifest = root / "reference-manifest.md"
    if not manifest.is_file():
        return records, ["美术缺少 reference-manifest.md"]
    for number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        row = cells(line)
        if len(row) != 11 or not row[0].startswith("REF-ASSET-") or row[0] == "REF-ASSET-ID":
            continue
        ref_id, revision, _asset, local, digest, media, _use, _rights, _owner, _approval, status = row
        key = f"{ref_id}@{revision}"
        if status != "accepted":
            continue
        path = resolve_file(root, local)
        if key in records:
            errors.append(f"{manifest}:{number}: accepted 参考重复 {key}")
        if not path.is_file() or not HASH_RE.fullmatch(digest) or file_hash(path).lower() != digest.lower():
            errors.append(f"{manifest}:{number}: accepted 参考文件/hash 无效 {key}")
        media_match = MEDIA_RE.fullmatch(media)
        actual_size = inspect_image_size(path) if path.is_file() else None
        if not media_match or actual_size is None:
            errors.append(f"{manifest}:{number}: accepted 参考尺寸/格式或图片文件无效 {key}")
            size = (0, 0)
        else:
            size = (int(media_match.group(1)), int(media_match.group(2)))
            if size != actual_size:
                errors.append(f"{manifest}:{number}: accepted 参考声明尺寸与文件不一致 {key}")
        records[key] = {
            "file": str(path), "hash": digest.lower(), "size": size,
        }
    return records, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path)
    parser.add_argument("storyboard", type=Path)
    parser.add_argument("assets", type=Path)
    parser.add_argument("--allow-fixture", action="store_true", help="仅测试时允许 fixture_mode")
    parser.add_argument("--pre-submit", action="store_true", help="仅校验付费前的档案、权利、参考与请求")
    args = parser.parse_args()
    root = args.video.resolve()
    storyboard = args.storyboard.resolve()
    assets_root = args.assets.resolve()
    expected_gens, expected_shots, expected_posts, episode_contracts, errors = production_contract(storyboard)
    asset_records, asset_errors = accepted_assets(assets_root)
    errors.extend(asset_errors)

    profile = root / "capability-profile.md"
    profile_text = profile.read_text(encoding="utf-8") if profile.is_file() else ""
    if not profile.is_file() or "- lifecycle_status：accepted" not in profile_text:
        errors.append("capability-profile.md 缺失或未 accepted")
    profile_hash = file_hash(profile) if profile.is_file() else ""
    for episode, contract in episode_contracts.items():
        if contract["profile_hash"] != profile_hash:
            errors.append(f"{contract['path']}: {episode} 未绑定当前能力档案 SHA-256")
    fixture_mode = "- fixture_mode：true" in profile_text
    if fixture_mode and not args.allow_fixture:
        errors.append("检测到 fixture_mode；真实生产门禁禁止测试媒体")
    strategy = re.search(r"^- project_voice_strategy：(.+)$", profile_text, re.M)
    voice_strategy = strategy.group(1).strip() if strategy else ""
    if voice_strategy not in {"原生音画", "统一后配"}:
        errors.append("capability profile 缺合法声音策略")
    profile_model_match = re.search(r"^- model：(.+)$", profile_text, re.M)
    profile_model = profile_model_match.group(1).strip() if profile_model_match else ""
    if profile_model != "dreamina-seedance-2-5-260628":
        errors.append("capability profile 模型不是已核实的 Seedance 2.5")
    portrait_match = re.search(r"^- portrait_input_route：(.+)$", profile_text, re.M)
    portrait_route = portrait_match.group(1).strip() if portrait_match else ""
    allowed_portrait_routes = {
        "no-real-human-face", "trusted-model-output", "preset-avatar", "authorized-real-person",
    }
    if portrait_route not in allowed_portrait_routes:
        errors.append("capability profile 缺合法 portrait_input_route")
    if portrait_route != "no-real-human-face":
        evidence = re.search(r"^- portrait_route_evidence：(.+)$", profile_text, re.M)
        if not evidence or not evidence.group(1).strip():
            errors.append("含真人风格人像时缺平台信任/预设/授权通道证据")

    sound_plan = root / "sound-plan.md"
    required_voices: dict[str, set[str]] = {}
    planned_voice_refs: dict[str, set[str]] = {}
    expected_voice_characters: dict[str, set[str]] = {}
    sound_channels: dict[str, str] = {}
    adr_by_episode: dict[str, set[str]] = {}
    if not sound_plan.is_file() or "- lifecycle_status：accepted" not in sound_plan.read_text(encoding="utf-8"):
        errors.append("缺少 accepted sound-plan.md")
    else:
        sound_text = sound_plan.read_text(encoding="utf-8")
        if "- 导演表演适配：accepted；" not in sound_text or "- 视频技术与权利验收：accepted；" not in sound_text:
            errors.append("sound-plan 缺导演表演适配或视频技术/权利双签")
        for line in sound_text.splitlines():
            row = cells(line)
            if len(row) != 8 or not (SHOT_RE.fullmatch(row[0]) or GEN_RE.fullmatch(row[0])):
                continue
            voice_refs = set(re.findall(r"VOICE-[A-Z0-9-]+@r\d+", row[6]))
            characters = {
                part.strip().removesuffix("画外")
                for part in re.split(r"[;；/]", row[1])
                if part.strip() and part.strip() not in {"无对白", "无"}
            }
            channel = row[5]
            if channel not in {"原生模型", "后期ADR", "无对白"}:
                errors.append(f"sound-plan: {row[0]} 非法执行通道 {channel}")
            if channel in {"原生模型", "后期ADR"} and not voice_refs:
                errors.append(f"sound-plan: {row[0]} {channel}有对白却未绑定 VOICE")
            if channel == "无对白" and voice_refs:
                errors.append(f"sound-plan: {row[0]} 无对白却绑定了 VOICE")
            if channel == "后期ADR":
                episode_match = re.search(r"EP\d{3}", row[0])
                if episode_match:
                    adr_by_episode.setdefault(episode_match.group(0), set()).add(row[0])
            sound_channels[row[0]] = channel
            required_voices[row[0]] = voice_refs if channel == "原生模型" else set()
            planned_voice_refs[row[0]] = voice_refs
            expected_voice_characters[row[0]] = characters if channel in {"原生模型", "后期ADR"} else set()
        missing_sound_rows = set(expected_gens) - set(sound_channels)
        extra_sound_rows = set(sound_channels) - set(expected_gens) - set(expected_shots)
        if missing_sound_rows:
            errors.append(f"sound-plan 缺生产 GEN 行：{sorted(missing_sound_rows)}")
        if extra_sound_rows:
            errors.append(f"sound-plan 含非生产 GEN/SHOT：{sorted(extra_sound_rows)}")

    post_plan = root / "post-plan.md"
    planned_posts: dict[str, str] = {}
    if not post_plan.is_file() or "- lifecycle_status：accepted" not in post_plan.read_text(encoding="utf-8"):
        errors.append("缺少 accepted post-plan.md")
    else:
        for line in post_plan.read_text(encoding="utf-8").splitlines():
            row = cells(line)
            if len(row) == 8 and re.fullmatch(r"POST-EP\d{3}-\d{3}@r\d+", row[1]) and SHOT_RE.fullmatch(row[3]):
                planned_posts[row[1]] = row[3]
    for post in expected_posts:
        if post not in planned_posts:
            errors.append(f"生产分镜 POST 未在 post-plan 定义：{post}")

    voice_manifest = root / "voice-manifest.md"
    voices = 0
    voice_records: dict[str, dict] = {}
    if not voice_manifest.is_file():
        errors.append("缺少 voice-manifest.md")
    else:
        for number, line in enumerate(voice_manifest.read_text(encoding="utf-8").splitlines(), 1):
            row = cells(line)
            if len(row) != 9 or not row[0].startswith("VOICE-") or row[0] == "VOICE-ID":
                continue
            voices += 1
            voice_id, revision, character, _anchors, local, digest, rights, approval, status = row
            key = f"{voice_id}@{revision}"
            media = resolve_file(root, local)
            location = f"{voice_manifest}:{number}"
            if status != "accepted" or not re.fullmatch(r"r\d+", revision):
                errors.append(f"{location}: {voice_id} 未 accepted 或 revision 非法")
            if not media.is_file() or not HASH_RE.fullmatch(digest) or file_hash(media).lower() != digest.lower():
                errors.append(f"{location}: {voice_id} 文件/hash 无效")
            if rights not in {"已授权", "自有", "已核实公版"} or not approval:
                errors.append(f"{location}: {voice_id} 权利状态不明确或缺批准")
            approval_file = root / approval.split("#", 1)[0]
            if (
                "rough-cut-approval" in approval_file.name
                or not approval_contains(approval_file, key, digest, character=character)
            ):
                errors.append(f"{location}: {voice_id} 批准证据不存在或错误倒签")
            if key in voice_records:
                errors.append(f"{location}: 声音版本重复 {key}")
            voice_records[key] = {
                "file": str(media), "hash": digest.lower(),
                "duration": inspect_duration(media) if media.is_file() else None,
                "character": character,
            }
        if voices == 0:
            errors.append("voice-manifest 没有角色声音")

    motion_records: dict[str, dict] = {}
    motion_manifest = root / "motion-reference-manifest.md"
    if motion_manifest.is_file():
        for number, line in enumerate(motion_manifest.read_text(encoding="utf-8").splitlines(), 1):
            row = cells(line)
            if len(row) != 9 or not row[0].startswith("MOTION-") or row[0] == "MOTION-ID":
                continue
            motion_id, revision, _use, local, digest, declared_duration, rights, approval, status = row
            key = f"{motion_id}@{revision}"
            media = resolve_file(root, local)
            location = f"{motion_manifest}:{number}"
            try:
                declared_s = float(declared_duration)
            except ValueError:
                declared_s = 0.0
            actual_s = inspect_duration(media) if media.is_file() else None
            if status != "accepted" or not re.fullmatch(r"r\d+", revision):
                errors.append(f"{location}: {key} 未 accepted 或 revision 非法")
            if not media.is_file() or not HASH_RE.fullmatch(digest) or file_hash(media).lower() != digest.lower():
                errors.append(f"{location}: {key} 文件/hash 无效")
            if actual_s is None or declared_s <= 0 or abs(actual_s - declared_s) > 0.1:
                errors.append(f"{location}: {key} 时长与媒体不一致")
            if rights not in {"已授权", "自有", "已核实公版"} or not approval:
                errors.append(f"{location}: {key} 权利状态不明确或缺批准")
            approval_file = root / approval.split("#", 1)[0]
            if not approval_contains(approval_file, key, digest):
                errors.append(f"{location}: {key} 批准证据不存在或不匹配")
            if key in motion_records:
                errors.append(f"{location}: 动作参考版本重复 {key}")
            motion_records[key] = {
                "file": str(media), "hash": digest.lower(), "duration": actual_s,
            }

    audio_records: dict[str, dict] = {}
    audio_manifest = root / "audio-assets-manifest.md"
    if audio_manifest.is_file():
        for number, line in enumerate(audio_manifest.read_text(encoding="utf-8").splitlines(), 1):
            row = cells(line)
            if len(row) != 10 or row[0] == "AUDIO-ID@revision" or not re.fullmatch(r"AUDIO-[A-Z0-9-]+@r\d+", row[0]):
                continue
            audio_id, kind, episode, local, digest, declared_duration, rights, use, approval, status = row
            media = resolve_file(root, local)
            location = f"{audio_manifest}:{number}"
            try:
                declared_s = float(declared_duration)
            except ValueError:
                declared_s = 0.0
            actual_s = inspect_audio_duration(media) if media.is_file() else None
            if status != "accepted":
                errors.append(f"{location}: {audio_id} 未 accepted")
            if episode not in {"EP001", "EP002"}:
                errors.append(f"{location}: {audio_id} 缺合法集号")
            if kind not in {"ADR", "音乐", "SFX", "母版混音"}:
                errors.append(f"{location}: {audio_id} 类型非法")
            if not media.is_file() or not HASH_RE.fullmatch(digest) or file_hash(media).lower() != digest.lower():
                errors.append(f"{location}: {audio_id} 文件/hash 无效")
            if actual_s is None or declared_s <= 0 or abs(actual_s - declared_s) > 0.1:
                errors.append(f"{location}: {audio_id} 声明时长与媒体不一致")
            if rights not in {"已授权", "自有", "已核实公版"} or not use or not approval:
                errors.append(f"{location}: {audio_id} 权利/用途/批准证据不完整")
            approval_file = root / approval.split("#", 1)[0]
            if not approval_contains(approval_file, audio_id, digest):
                errors.append(f"{location}: {audio_id} 批准证据不存在或不匹配")
            audio_records[audio_id] = {
                "kind": kind, "episode": episode, "file": str(media),
                "hash": digest.lower(), "duration": actual_s, "use": use,
            }
    if not args.pre_submit:
        for episode, gens in adr_by_episode.items():
            for gen in gens:
                if not any(
                    record["kind"] == "ADR" and record["episode"] == episode and gen in record["use"]
                    for record in audio_records.values()
                ):
                    errors.append(f"sound-plan: {gen} 声明后期ADR，但 audio-assets-manifest 无对应 accepted ADR")
    for sound_id, voice_ids in planned_voice_refs.items():
        actual_characters = {
            voice_records[voice_id]["character"] for voice_id in voice_ids if voice_id in voice_records
        }
        expected_characters = expected_voice_characters.get(sound_id, set())
        if actual_characters != expected_characters:
            errors.append(
                f"sound-plan: {sound_id} 说话角色与 VOICE 身份不一致，"
                f"需{sorted(expected_characters)}，实际{sorted(actual_characters)}"
            )

    seen: set[str] = set()
    referenced_requests: set[Path] = set()
    accepted_for: dict[str, str] = {}
    accepted_outputs: dict[str, dict] = {}
    authorization_text = (root / "approvals" / "production-authorization.md").read_text(encoding="utf-8") if (root / "approvals" / "production-authorization.md").is_file() else ""
    submission_records: list[dict[str, object]] = []
    submission_log = root / "approvals" / "submission-log.jsonl"
    if submission_log.is_file():
        for line in submission_log.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                errors.append(f"{submission_log}: 非法 JSONL 记录")
                continue
            if isinstance(record, dict):
                submission_records.append(record)
    if not fixture_mode and not args.pre_submit and (not authorization_text or not submission_records):
        errors.append("真实生产缺 production-authorization.md 或 submission-log.jsonl")
    for path in sorted((root / "episodes").glob("EP*.md")):
        text = path.read_text(encoding="utf-8")
        headings = list(re.finditer(
            r"^##\s+(GEN-EP\d{3}-\d{3}(?:-\d+)?@r\d+)｜(SHOT-EP\d{3}-\d{3}@r\d+)$",
            text,
            re.M,
        ))
        for index, match in enumerate(headings):
            gen, declared_shot = match.groups()
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            section = text[match.start():end]
            contract = expected_gens.get(gen)
            if gen in seen:
                errors.append(f"{path}: GEN 重复 {gen}")
            seen.add(gen)
            if not contract:
                errors.append(f"{path}: GEN 无生产分镜来源 {gen}")
            elif declared_shot != contract["shot"]:
                errors.append(f"{path}: {gen} 声明 {declared_shot}，生产分镜映射为 {contract['shot']}")

            target = re.search(r"^- 目标剪辑时长：(\d+(?:\.\d+)?)秒$", section, re.M)
            material = re.search(r"^- 请求素材时长：(\d+(?:\.\d+)?)秒$", section, re.M)
            trim = re.search(r"^- 预期可用区间/trim：(.+)$", section, re.M)
            if contract:
                if not target or abs(float(target.group(1)) - contract["edit"]) > 1e-6:
                    errors.append(f"{path}: {gen} 目标剪辑时长与生产分镜不一致")
                if not material or abs(float(material.group(1)) - contract["material"]) > 1e-6:
                    errors.append(f"{path}: {gen} 请求素材时长与生产分镜不一致")
                if not trim or trim.group(1).strip() != contract["trim"]:
                    errors.append(f"{path}: {gen} trim 与生产分镜不一致")

            reference_rows: list[dict] = []
            for number, line in enumerate(section.splitlines(), 1):
                row = cells(line)
                if len(row) != 7 or not row[0].startswith("REF-GEN-") or row[0] == "REF-ID":
                    continue
                _ref_gen, upload, local_hash, url, binding, _use, _avoid = row
                if " / " not in local_hash:
                    errors.append(f"{path}: {gen} 参考行缺本地文件/hash")
                    continue
                local, digest = local_hash.rsplit(" / ", 1)
                kind = upload.split(" ", 1)[0]
                authority = {"Image": asset_records, "Video": motion_records, "Audio": voice_records}.get(kind)
                record = authority.get(binding) if authority is not None else None
                if not record:
                    errors.append(f"{path}: {gen} 的 {upload} 绑定对象未在对应 accepted 清单中：{binding}")
                else:
                    if str(resolve_file(root, local)) != record["file"] or digest.lower() != record["hash"]:
                        errors.append(f"{path}: {gen} 的 {binding} 本地文件/hash 与权威清单不一致")
                    if not valid_locator(url, allow_fixture=fixture_mode and args.allow_fixture):
                        errors.append(f"{path}: {gen} 的 {binding} 提交 URL/asset ID 非法")
                reference_rows.append({
                    "upload": upload, "url": url, "binding": binding,
                    "duration": record.get("duration") if record else None,
                })
            bound_assets = {
                row["binding"] for row in reference_rows if row["upload"].startswith("Image ")
            }
            if contract and bound_assets != contract["refs"]:
                missing = sorted(contract["refs"] - bound_assets)
                extra = sorted(bound_assets - contract["refs"])
                errors.append(f"{path}: {gen} 图片参考集合与生产分镜不一致，缺{missing}，多{extra}")
            if voice_strategy == "原生音画":
                bound_voices = {row["binding"] for row in reference_rows if row["upload"].startswith("Audio ")}
                required = required_voices.get(gen, required_voices.get(declared_shot, set()))
                if bound_voices != required:
                    errors.append(f"{path}: {gen} 对白角色 VOICE 映射不一致，需{sorted(required)}，实际{sorted(bound_voices)}")

            request_match = re.search(r"^- 请求文件：(.+\.json)$", section, re.M)
            request_hash_match = re.search(r"^- 请求文件 SHA-256：([0-9a-fA-F]{64})$", section, re.M)
            request_digest = ""
            request_path: Path | None = None
            if not request_match or not request_hash_match:
                errors.append(f"{path}: {gen} 缺请求文件/hash")
            else:
                request_path = resolve_file(root, request_match.group(1).strip())
                request_digest = request_hash_match.group(1).lower()
                expected_request_name = gen.replace("@", "-") + ".json"
                if request_path.name != expected_request_name:
                    errors.append(
                        f"{path}: {gen} 请求文件名必须为 {expected_request_name}"
                    )
                if request_path in referenced_requests:
                    errors.append(f"{path}: 请求文件被多个 GEN 复用 {request_path}")
                referenced_requests.add(request_path)
                if not request_path.is_file() or file_hash(request_path).lower() != request_digest:
                    errors.append(f"{path}: {gen} 请求文件不存在或 hash 不匹配")
                else:
                    try:
                        payload = json.loads(request_path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError) as exc:
                        errors.append(f"{path}: {gen} 请求 JSON 无效：{exc}")
                        payload = {}
                    for validation_error in validate_payload(payload, allow_fixture=fixture_mode and args.allow_fixture):
                        errors.append(f"{path}: {gen} 请求门禁：{validation_error}")
                    if not fixture_mode:
                        request_roles = {
                            item.get("role") for item in payload.get("content", []) if isinstance(item, dict)
                        }
                        if request_roles & {"reference_image", "reference_video", "reference_audio"}:
                            if payload.get("omni_reference_task_type") != "reference":
                                errors.append(f"{path}: {gen} 正式 omni 请求未锁定 reference 任务类型")
                        if payload.get("output_format") != "mp4":
                            errors.append(f"{path}: {gen} 正式请求未锁定 output_format=mp4")
                    content = payload.get("content")
                    if payload.get("model") != profile_model or not isinstance(content, list):
                        errors.append(f"{path}: {gen} 请求缺 model/content[]")
                        content = []
                    text_items = [item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"]
                    if len(text_items) != 1 or not text_items[0].strip():
                        errors.append(f"{path}: {gen} 请求必须有且只有一个非空 text")
                    actual_media: list[dict[str, str]] = []
                    counts = {"image": 0, "video": 0, "audio": 0}
                    allowed_roles = {"reference_image", "reference_video", "reference_audio", "first_frame", "last_frame"}
                    for item in content:
                        if not isinstance(item, dict) or item.get("type") == "text":
                            continue
                        kind = str(item.get("type", "")).removesuffix("_url")
                        if kind not in counts or item.get("role") not in allowed_roles:
                            errors.append(f"{path}: {gen} 非法参考类型/role")
                            continue
                        counts[kind] += 1
                        container = item.get(f"{kind}_url")
                        url = container.get("url") if isinstance(container, dict) else ""
                        actual_media.append({
                            "upload": f"{kind.capitalize()} {counts[kind]}",
                            "url": url,
                            "role": str(item.get("role", "")),
                        })
                    declared_media = [
                        {"upload": row["upload"], "url": row["url"]}
                        for row in reference_rows
                    ]
                    if [
                        {"upload": row["upload"], "url": row["url"]}
                        for row in actual_media
                    ] != declared_media:
                        errors.append(f"{path}: {gen} 请求参考顺序/URL 与参考上传表不一致")
                    for media_item in actual_media:
                        url = media_item["url"]
                        if not fixture_mode and not (
                            isinstance(url, str)
                            and (url.startswith("https://") or url.startswith("asset://") or url.startswith("data:"))
                        ):
                            errors.append(f"{path}: {gen} 参考素材不是平台可访问形式")
                    if counts["image"] > 30 or counts["video"] > 10 or counts["audio"] > 10:
                        errors.append(f"{path}: {gen} 参考数量超过平台上限")
                    if sum(counts.values()) > 50:
                        errors.append(f"{path}: {gen} 参考素材总数超过平台50个上限")
                    video_seconds = sum(
                        row["duration"] or 0 for row in reference_rows if row["upload"].startswith("Video ")
                    )
                    audio_seconds = sum(
                        row["duration"] or 0 for row in reference_rows if row["upload"].startswith("Audio ")
                    )
                    if video_seconds > 30.1 or audio_seconds > 30.1:
                        errors.append(f"{path}: {gen} 视频或音频参考总时长超过30秒")
                    prompt = text_items[0] if text_items else ""
                    expected_markers = {
                        (row["upload"].split(" ", 1)[0], int(row["upload"].split(" ", 1)[1]))
                        for row in actual_media
                    }
                    if marker_set(prompt) != expected_markers:
                        errors.append(f"{path}: {gen} 提示词引用与真实上传编号不精确一致")
                    duration = payload.get("duration")
                    if not isinstance(duration, (int, float)) or duration < 4 or duration > 30:
                        errors.append(f"{path}: {gen} 请求 duration 不在4—30秒")
                    elif contract and abs(float(duration) - contract["material"]) > 1e-6:
                        errors.append(f"{path}: {gen} 请求 duration 与生产分镜不一致")
                    roles = [item.get("role") for item in content if isinstance(item, dict)]
                    if roles.count("first_frame") > 1 or roles.count("last_frame") > 1:
                        errors.append(f"{path}: {gen} first_frame/last_frame 各最多一个")
                    if "last_frame" in roles and "first_frame" not in roles:
                        errors.append(f"{path}: {gen} last_frame 必须同时提供 first_frame")
                    if any(role in {"first_frame", "last_frame"} for role in roles) and any(
                        role in {"reference_image", "reference_video", "reference_audio"} for role in roles
                    ):
                        errors.append(f"{path}: {gen} 严格首尾帧与 omni 参考互斥")
                    frame_sizes: dict[str, tuple[int, int]] = {}
                    declared_by_upload = {row["upload"]: row for row in reference_rows}
                    for media_item in actual_media:
                        role = media_item["role"]
                        if role not in {"first_frame", "last_frame"}:
                            continue
                        declared = declared_by_upload.get(media_item["upload"])
                        record = asset_records.get(declared["binding"]) if declared else None
                        if not record or record.get("size") == (0, 0):
                            errors.append(f"{path}: {gen} {role} 缺可验证图片尺寸")
                        else:
                            frame_sizes[role] = record["size"]
                    if set(frame_sizes) == {"first_frame", "last_frame"}:
                        first_w, first_h = frame_sizes["first_frame"]
                        last_w, last_h = frame_sizes["last_frame"]
                        if first_w * last_h != last_w * first_h:
                            errors.append(f"{path}: {gen} 首尾帧宽高比不一致")
                    if any(role in {"first_frame", "last_frame"} for role in roles) and payload.get("ratio") != "adaptive":
                        errors.append(f"{path}: {gen} 首尾帧请求 ratio 必须 adaptive")
                    elif not any(role in {"first_frame", "last_frame"} for role in roles) and payload.get("ratio") != "9:16":
                        errors.append(f"{path}: {gen} 非首尾帧竖屏请求 ratio 必须9:16")
                    if payload.get("resolution") not in {"480p", "720p"}:
                        errors.append(f"{path}: {gen} resolution 不在能力档案允许范围")
                    generate_audio = payload.get("generate_audio")
                    channel = sound_channels.get(gen, sound_channels.get(declared_shot, ""))
                    if not isinstance(generate_audio, bool):
                        errors.append(f"{path}: {gen} generate_audio 必须显式为布尔值")
                    elif voice_strategy == "原生音画" and channel == "后期ADR" and generate_audio:
                        errors.append(f"{path}: {gen} 后期ADR底板必须关闭 generate_audio，避免不可控人声")
                    elif voice_strategy == "原生音画" and channel != "后期ADR" and not generate_audio:
                        errors.append(f"{path}: {gen} 原生音画且非ADR底板，却关闭 generate_audio")
                    elif voice_strategy == "统一后配" and generate_audio:
                        errors.append(f"{path}: {gen} 统一后配策略必须关闭 generate_audio")

            if args.pre_submit:
                continue
            if "- lifecycle_status：accepted" not in section:
                errors.append(f"{path}: {gen} 未 accepted")
            checks = [
                row for row in (cells(line) for line in section.splitlines())
                if len(row) == 5 and row[0] in {"剧情/信息", "身份/资产", "动作/表演", "摄影/首尾", "声音/技术"}
            ]
            expected_result = "fixture-pass" if fixture_mode and args.allow_fixture else "pass"
            if len(checks) != 5 or any(
                row[2] != expected_result or not row[1].strip() or not row[3].strip()
                for row in checks
            ):
                errors.append(f"{path}: {gen} 验收未全部 {expected_result}")

            outputs = [
                row for row in (cells(line) for line in section.splitlines())
                if len(row) == 13 and row[0].startswith("OUTPUT-") and row[-1] == "accepted"
            ]
            if len(outputs) != 1:
                errors.append(f"{path}: {gen} 必须恰有一个 accepted OUTPUT")
            for row in outputs:
                output, revision, task, input_hash, _prompt, model, _submitted, _temporary, local, digest, probe_text, usable, _status = row
                location = f"{path}: {gen}/{output}@{revision}"
                key = f"{output}@{revision}"
                media = resolve_file(root, local)
                if task.startswith("fixture-") and not args.allow_fixture:
                    errors.append(f"{location}: 真实生产门禁禁止 fixture task")
                if not task or not model or not re.fullmatch(r"r\d+", revision):
                    errors.append(f"{location}: accepted OUTPUT 缺 task/revision/model")
                if not fixture_mode and model != profile_model:
                    errors.append(f"{location}: OUTPUT 模型与能力档案不一致")
                if not fixture_mode:
                    approver = authorization_approver(
                        authorization_text, request_path, input_hash, model,
                    ) if request_path is not None else None
                    if approver is None:
                        errors.append(f"{location}: 请求 hash/model 无匹配具名付费授权")
                    if not valid_submission_chain(
                        submission_records, task, input_hash, str(media), digest,
                        str(request_path or ""), model, approver or "",
                    ):
                        errors.append(f"{location}: task ID/hash 缺唯一、有序且绑定授权的 reservation→submitted→archived 事件链")
                if input_hash.lower() != request_digest or not HASH_RE.fullmatch(input_hash):
                    errors.append(f"{location}: input manifest hash 与请求文件不一致")
                if not media.is_file() or not HASH_RE.fullmatch(digest) or file_hash(media).lower() != digest.lower():
                    errors.append(f"{location}: 媒体文件/hash 无效")
                media_probe = inspect_media(media) if media.is_file() else None
                if media_probe is None or media_probe[0] <= 0 or media_probe[1] <= 0 or media_probe[2] <= 0:
                    errors.append(f"{location}: ffprobe 媒体规格无效")
                channel = sound_channels.get(gen, sound_channels.get(declared_shot, ""))
                expected_audio = voice_strategy == "原生音画" and channel != "后期ADR"
                if media_probe is not None and media_probe[3] != expected_audio:
                    errors.append(f"{location}: 归档媒体音轨与声音执行通道不一致")
                elif contract and (
                    abs(media_probe[0] - contract["material"]) > 0.5
                    or abs((media_probe[1] / media_probe[2]) - (9 / 16)) > 0.003
                ):
                    errors.append(f"{location}: 归档媒体时长/比例/音轨与请求不一致")
                if not probe_text or seconds_range(usable) is None:
                    errors.append(f"{location}: 缺媒体探针/可用区间")
                if key in accepted_outputs:
                    errors.append(f"{location}: accepted OUTPUT 版本重复")
                accepted_outputs[key] = {
                    "file": str(media), "hash": digest.lower(), "usable": usable,
                    "gen": gen, "shot": declared_shot,
                }
                accepted_for[gen] = key

    for gen in sorted(set(expected_gens) - seen):
        errors.append(f"缺少视频任务 {gen}")
    for gen in sorted(seen - set(expected_gens)):
        errors.append(f"视频任务无生产分镜来源 {gen}")
    if not args.pre_submit:
        for gen in sorted(set(expected_gens) - set(accepted_for)):
            errors.append(f"生产 GEN 没有唯一 accepted 媒体 {gen}")

    request_files = set((root / "requests").glob("*.json"))
    for request_path in sorted(request_files - referenced_requests):
        errors.append(f"requests 目录存在未被当前 GEN 引用的孤儿请求 {request_path.name}")
    for request_path in sorted(referenced_requests - request_files):
        errors.append(f"GEN 引用的请求不在 requests 目录 {request_path}")

    if args.pre_submit:
        if errors:
            for error in errors:
                print(f"ERROR: {error}")
            print(f"PRE-SUBMIT FAILED: {len(errors)} 项")
            return 1
        print(f"PRE-SUBMIT OK: {len(seen)} 个 GEN 的平台档案/权利/参考/请求有效")
        return 0

    post_records: dict[str, dict] = {}
    post_path = root / "post-tasks.md"
    if post_path.is_file():
        for number, line in enumerate(post_path.read_text(encoding="utf-8").splitlines(), 1):
            row = cells(line)
            if len(row) != 11 or not row[0].startswith("POST-") or row[0] == "POST-ID":
                continue
            post_id, source, binding, _base, _time, _effect, output_file, digest, _owner, evidence, status = row
            post_key = post_id if "@r" in post_id else f"{post_id}@r1"
            location = f"{post_path}:{number}"
            bindings = [part.strip() for part in binding.split(" / ")]
            shot = next((part for part in bindings if SHOT_RE.fullmatch(part)), "")
            output = next((part for part in bindings if part.startswith("OUTPUT-") and "@r" in part), "")
            media = resolve_file(root, output_file)
            if status != "accepted":
                errors.append(f"{location}: 必需 POST 未 accepted {post_id}")
                continue
            if not source or not shot or not output or not evidence:
                errors.append(f"{location}: accepted POST 缺来源/SHOT/OUTPUT/验收证据")
            if output not in accepted_outputs or accepted_outputs.get(output, {}).get("shot") != shot:
                errors.append(f"{location}: POST 绑定非 accepted OUTPUT 或错误 SHOT")
            if not media.is_file() or not HASH_RE.fullmatch(digest) or file_hash(media).lower() != digest.lower():
                errors.append(f"{location}: POST 输出文件/hash 无效")
            if post_key not in planned_posts or planned_posts.get(post_key) != shot:
                errors.append(f"{location}: POST 未由当前 post-plan 分配或绑定 SHOT 错误")
            post_records[post_key] = {"shot": shot, "output": output, "file": str(media), "hash": digest.lower()}
    elif expected_posts:
        errors.append("生产分镜声明 POST，但缺少 post-tasks.md")
    for post_id in sorted(expected_posts - set(post_records)):
        errors.append(f"生产分镜 POST 未 accepted：{post_id}")

    approvals = root / "approvals" / "rough-cut-approval.md"
    approved_cuts: dict[str, tuple[str, str, str, str]] = {}
    if approvals.is_file():
        for line in approvals.read_text(encoding="utf-8").splitlines():
            row = cells(line)
            if len(row) == 11 and row[4] == "accepted" and row[7] == "accepted":
                if not row[5] or not valid_iso8601(row[6]) or not row[8] or not valid_iso8601(row[9]):
                    errors.append(f"{approvals}: {row[0]} 粗剪批准缺具名签署或 ISO-8601 时间")
                approved_cuts[row[0]] = (
                    row[1], row[2].lower(), row[3].lower(), row[10].lower()
                )

    used_outputs: set[str] = set()
    used_shots: set[str] = set()
    cuts = sorted((root / "cuts").glob("EP???.md"))
    if {path.stem for path in cuts} != set(episode_contracts):
        errors.append("粗剪集数与生产分镜不一致")
    for cut in cuts:
        episode = cut.stem
        contract_ep = episode_contracts.get(episode, {})
        text = cut.read_text(encoding="utf-8")
        cut_id_match = re.search(r"^- CUT-ID：(CUT-EP\d{3}@r\d+)$", text, re.M)
        plan_match = re.search(r"^- cut_plan：(.+\.json)$", text, re.M)
        plan_hash_match = re.search(r"^- cut_plan_SHA-256：([0-9a-fA-F]{64})$", text, re.M)
        receipt_match = re.search(r"^- assembly_receipt：(.+\.json)$", text, re.M)
        receipt_hash_match = re.search(r"^- assembly_receipt_SHA-256：([0-9a-fA-F]{64})$", text, re.M)
        media_match = re.search(r"^- 粗剪本地文件：(.+)$", text, re.M)
        digest_match = re.search(r"^- SHA-256：([0-9a-fA-F]{64})$", text, re.M)
        total_match = re.search(r"^- 总时长：(\d+(?:\.\d+)?)秒$", text, re.M)
        if not cut_id_match or "- lifecycle_status：accepted" not in text or "- 时间线QC：pass" not in text:
            errors.append(f"{cut}: 未 accepted 或时间线QC未通过")
            continue
        cut_id = cut_id_match.group(1)
        if not plan_match or not plan_hash_match:
            errors.append(f"{cut}: 缺 cut-plan 文件/hash")
            continue
        plan_path = resolve_file(root, plan_match.group(1).strip())
        if not plan_path.is_file() or file_hash(plan_path).lower() != plan_hash_match.group(1).lower():
            errors.append(f"{cut}: cut-plan 文件/hash 无效")
            continue
        try:
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{cut}: cut-plan JSON 无效：{exc}")
            continue
        receipt: dict[str, object] = {}
        receipt_path = resolve_file(root, receipt_match.group(1).strip()) if receipt_match else Path("")
        if (
            not receipt_match or not receipt_hash_match or not receipt_path.is_file()
            or file_hash(receipt_path).lower() != receipt_hash_match.group(1).lower()
        ):
            errors.append(f"{cut}: 组接来源凭证文件/hash 无效")
        else:
            try:
                loaded_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                receipt = loaded_receipt if isinstance(loaded_receipt, dict) else {}
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"{cut}: 组接来源凭证 JSON 无效：{exc}")
            if receipt.get("schema") != "seedance-cut-assembly-receipt/v1":
                errors.append(f"{cut}: 组接来源凭证 schema 无效")
            receipt_plan = receipt.get("plan")
            if not isinstance(receipt_plan, dict) or (
                str(resolve_file(root, str(receipt_plan.get("path", "")))) != str(plan_path)
                or str(receipt_plan.get("sha256", "")).lower() != plan_hash_match.group(1).lower()
            ):
                errors.append(f"{cut}: 组接来源凭证未绑定当前 cut-plan 文件/hash")
        if plan.get("cut_id") != cut_id:
            errors.append(f"{cut}: cut-plan 的 CUT-ID 不匹配")
        if receipt and receipt.get("cut_id") != cut_id:
            errors.append(f"{cut}: 组接来源凭证 CUT-ID 不匹配")
        audio_mode = plan.get("audio_mode")
        if audio_mode not in {"native", "master_mix", "fixture_silence"}:
            errors.append(f"{cut}: cut-plan 缺合法 audio_mode")
        elif audio_mode == "fixture_silence" and not (fixture_mode and args.allow_fixture):
            errors.append(f"{cut}: fixture_silence 只允许测试夹具")
        elif voice_strategy == "统一后配" and audio_mode == "native":
            errors.append(f"{cut}: 统一后配不能使用未冻结的片段原声")
        elif adr_by_episode.get(episode) and audio_mode != "master_mix":
            errors.append(f"{cut}: 本集存在后期ADR，必须使用 accepted master_mix")
        if audio_mode == "master_mix":
            mix_id = str(plan.get("mix_id", ""))
            mix_file = resolve_file(root, str(plan.get("mix_file", "")))
            mix_hash = str(plan.get("mix_sha256", ""))
            mix_duration = inspect_audio_duration(mix_file) if mix_file.is_file() else None
            mix_record = audio_records.get(mix_id)
            if (
                not mix_file.is_file() or not HASH_RE.fullmatch(mix_hash)
                or file_hash(mix_file).lower() != mix_hash.lower()
                or mix_duration is None
            ):
                errors.append(f"{cut}: master_mix 文件/hash/音轨无效")
            elif not mix_record or (
                mix_record["kind"] != "母版混音" or mix_record["episode"] != episode
                or mix_record["file"] != str(mix_file) or mix_record["hash"] != mix_hash.lower()
            ):
                errors.append(f"{cut}: master_mix 未绑定 audio-assets-manifest 的当前 accepted 母版")
            elif abs(mix_duration - sum(float(clip.get("out", 0)) - float(clip.get("in", 0)) for clip in plan.get("clips", []))) > 0.15:
                errors.append(f"{cut}: master_mix 未覆盖完整冻结时间线")
            required_adr = {
                audio_id for audio_id, record in audio_records.items()
                if record["kind"] == "ADR" and record["episode"] == episode
            }
            declared_components = set(re.findall(r"AUDIO-[A-Z0-9-]+@r\d+", mix_record["use"])) if mix_record else set()
            if not required_adr.issubset(declared_components):
                errors.append(f"{cut}: master_mix 用途未声明包含全部 ADR：{sorted(required_adr - declared_components)}")
        receipt_audio = receipt.get("audio") if isinstance(receipt.get("audio"), dict) else {}
        expected_mix_file = str(resolve_file(root, str(plan.get("mix_file", "")))) if audio_mode == "master_mix" else ""
        if receipt and (
            receipt_audio.get("mode") != audio_mode
            or (
                audio_mode == "master_mix" and (
                    str(resolve_file(root, str(receipt_audio.get("mix_file", "")))) != expected_mix_file
                    or str(receipt_audio.get("mix_sha256", "")).lower() != str(plan.get("mix_sha256", "")).lower()
                )
            )
        ):
            errors.append(f"{cut}: 组接来源凭证 audio 与 cut-plan/master_mix 不一致")
        storyboard_file = resolve_file(storyboard, str(plan.get("storyboard_file", "")))
        if storyboard_file != contract_ep.get("path") or plan.get("storyboard_sha256", "").lower() != contract_ep.get("hash"):
            errors.append(f"{cut}: cut-plan 未绑定当前生产分镜文件/hash")

        timeline: dict[str, dict] = {}
        for number, line in enumerate(text.splitlines(), 1):
            row = cells(line)
            if len(row) != 8 or not row[0].isdigit():
                continue
            _order, shot, output_field, in_point, out_point, post_id, _sound, status = row
            parts = [part.strip() for part in output_field.split(" / ")]
            output = parts[0] if parts else ""
            if output in timeline:
                errors.append(f"{cut}:{number}: OUTPUT 在时间线重复 {output}")
            timeline[output] = {
                "shot": shot, "hash": parts[1].lower() if len(parts) > 1 else "",
                "in": in_point, "out": out_point, "post": post_id, "status": status,
            }

        clips = plan.get("clips")
        if not isinstance(clips, list) or not clips:
            errors.append(f"{cut}: cut-plan clips 为空")
            continue
        plan_outputs: set[str] = set()
        consumed_posts: set[str] = set()
        receipt_clips = receipt.get("clips") if isinstance(receipt.get("clips"), list) else []
        if receipt and len(receipt_clips) != len(clips):
            errors.append(f"{cut}: 组接来源凭证 clip 数与 cut-plan 不一致")
        cut_gen_order: list[str] = []
        shot_durations: dict[str, float] = {}
        cut_duration = 0.0
        for index, clip in enumerate(clips):
            location = f"{plan_path}:clips[{index}]"
            if not isinstance(clip, dict):
                errors.append(f"{location}: 不是对象")
                continue
            shot, output = clip.get("shot"), clip.get("output")
            record = accepted_outputs.get(output)
            if output in plan_outputs:
                errors.append(f"{location}: OUTPUT 重复 {output}")
            plan_outputs.add(output)
            if not record or record["shot"] != shot:
                errors.append(f"{location}: OUTPUT 不是该 SHOT 的 accepted 产物")
                continue
            cut_gen_order.append(record["gen"])
            used_outputs.add(output)
            used_shots.add(shot)
            source = resolve_file(root, str(clip.get("file", "")))
            if str(source) != record["file"] or clip.get("file_sha256", "").lower() != record["hash"]:
                errors.append(f"{location}: 原 OUTPUT 文件/hash 与生成记录不一致")
            post_id = clip.get("post_id")
            if post_id and "@r" not in str(post_id):
                errors.append(f"{location}: cut-plan POST 必须带 revision")
            chosen = source
            if post_id:
                consumed_posts.add(str(post_id))
                post_record = post_records.get(post_id)
                post_file = resolve_file(root, str(clip.get("post_file", "")))
                if not post_record or post_record["shot"] != shot or post_record["output"] != output:
                    errors.append(f"{location}: POST 未 accepted 或绑定错误")
                elif str(post_file) != post_record["file"] or clip.get("post_sha256", "").lower() != post_record["hash"]:
                    errors.append(f"{location}: POST 输出文件/hash 不一致")
                chosen = post_file
            elif any(key in clip for key in ("post_file", "post_sha256")):
                errors.append(f"{location}: 有 POST 文件但缺 post_id")
            try:
                start, end = float(clip["in"]), float(clip["out"])
            except (KeyError, TypeError, ValueError):
                errors.append(f"{location}: 入出点非法")
                continue
            usable = seconds_range(record["usable"])
            if start < 0 or end <= start or (usable and (start < usable[0] - 1e-6 or end > usable[1] + 1e-6)):
                errors.append(f"{location}: 入出点超出 accepted 可用区间")
            probe = inspect_media(chosen) if chosen.is_file() else None
            if probe is None or end > probe[0] + 0.05:
                errors.append(f"{location}: 所选媒体不足以覆盖出点")
            if receipt and index < len(receipt_clips):
                receipt_clip = receipt_clips[index]
                expected_selected_hash = file_hash(chosen).lower() if chosen.is_file() else ""
                if not isinstance(receipt_clip, dict) or (
                    receipt_clip.get("order") != index + 1
                    or receipt_clip.get("shot") != shot
                    or receipt_clip.get("output") != output
                    or str(resolve_file(root, str(receipt_clip.get("selected_file", "")))) != str(chosen)
                    or str(receipt_clip.get("selected_sha256", "")).lower() != expected_selected_hash
                    or receipt_clip.get("post_id") != (post_id or None)
                    or abs(float(receipt_clip.get("in", -1)) - start) > 1e-6
                    or abs(float(receipt_clip.get("out", -1)) - end) > 1e-6
                ):
                    errors.append(f"{location}: 组接来源凭证与当前 clip/POST/入出点不一致")
            duration = end - start
            cut_duration += duration
            shot_durations[shot] = shot_durations.get(shot, 0.0) + duration
            timeline_row = timeline.get(output)
            expected_post = post_id or "无"
            if not timeline_row:
                errors.append(f"{location}: cut-plan OUTPUT 未出现在粗剪清单")
            elif (
                timeline_row["shot"] != shot
                or timeline_row["hash"] != record["hash"]
                or abs(float(timeline_row["in"]) - start) > 1e-6
                or abs(float(timeline_row["out"]) - end) > 1e-6
                or timeline_row["post"] != expected_post
                or timeline_row["status"] != "accepted"
            ):
                errors.append(f"{location}: cut-plan 与粗剪清单时间线不一致")
        for output in set(timeline) - plan_outputs:
            errors.append(f"{cut}: 粗剪清单 OUTPUT 未进入 cut-plan：{output}")
        required_episode_posts = {
            post for post in expected_posts
            if (match := re.search(r"EP\d{3}", post)) and match.group(0) == episode
        }
        if consumed_posts != required_episode_posts:
            errors.append(
                f"{cut}: 必需 POST 消费集合不一致，缺{sorted(required_episode_posts - consumed_posts)}，"
                f"多{sorted(consumed_posts - required_episode_posts)}"
            )
        expected_gen_order = [
            gen for gen, gen_record in expected_gens.items()
            if gen_record["episode"] == episode
        ]
        if cut_gen_order != expected_gen_order:
            errors.append(
                f"{cut}: 粗剪 GEN 顺序与生产分镜不一致；"
                f"期望 {expected_gen_order}，实际 {cut_gen_order}"
            )
        for shot, shot_record in expected_shots.items():
            if shot_record["episode"] != episode:
                continue
            actual = shot_durations.get(shot, 0.0)
            if abs(actual - shot_record["duration"]) > 1e-6:
                errors.append(f"{cut}: {shot} 时间线 {actual:g}s 不等于冻结目标 {shot_record['duration']:g}s")
        if total_match and abs(float(total_match.group(1)) - cut_duration) > 0.05:
            errors.append(f"{cut}: 登记总时长与入出点之和不一致")
        if contract_ep and abs(cut_duration - contract_ep["target"]) > contract_ep["tolerance"]:
            errors.append(f"{cut}: 粗剪 {cut_duration:g}s 超出分镜目标容差")

        media = resolve_file(root, media_match.group(1).strip()) if media_match else Path("")
        digest = digest_match.group(1).lower() if digest_match else ""
        if not media.is_file() or not HASH_RE.fullmatch(digest) or file_hash(media).lower() != digest:
            errors.append(f"{cut}: 粗剪文件/hash 无效")
        else:
            probe = inspect_media(media)
            if probe is None or abs(probe[0] - cut_duration) > 0.15 or probe[1] >= probe[2] or (voice_strategy and not probe[3]):
                errors.append(f"{cut}: 粗剪时长/竖屏/音轨不符合冻结时间线")
        receipt_output = receipt.get("output") if isinstance(receipt.get("output"), dict) else {}
        if receipt and (
            str(resolve_file(root, str(receipt_output.get("path", "")))) != str(media)
            or str(receipt_output.get("sha256", "")).lower() != digest
        ):
            errors.append(f"{cut}: 组接来源凭证未绑定当前粗剪文件/hash")
        approval = approved_cuts.get(cut_id)
        if (
            not approval or approval[0] != str(media) or approval[1] != digest
            or approval[2] != plan_hash_match.group(1).lower()
            or approval[3] != receipt_hash_match.group(1).lower()
        ):
            errors.append(f"{cut}: 缺少匹配的导演批准")

    for output in sorted(set(accepted_outputs) - used_outputs):
        errors.append(f"accepted OUTPUT 未进入任何粗剪：{output}")
    for shot in sorted(set(expected_shots) - used_shots):
        errors.append(f"生产 SHOT 未进入粗剪：{shot}")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"FAILED: {len(errors)} 项")
        return 1
    print(
        f"OK: {len(seen)} 个 GEN 与生产分镜/多模态参考一致，"
        f"{len(post_records)} 个 POST 和 {len(cuts)} 集粗剪证据链有效"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
