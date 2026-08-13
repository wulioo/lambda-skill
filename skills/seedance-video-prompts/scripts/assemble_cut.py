#!/usr/bin/env python3
"""按冻结入出点与 POST 文件组接竖屏粗剪，并输出 SHA-256/ffprobe。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


HASH_RE = re.compile(r"^[0-9a-f]{64}$", re.I)


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def has_audio(path: Path) -> bool:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return False
    try:
        return bool(json.loads(result.stdout).get("streams"))
    except json.JSONDecodeError:
        return False


def media_probe(path: Path) -> tuple[float, int, int, float | None] | None:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
        video = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "video"), None)
        audio = next((stream for stream in data.get("streams", []) if stream.get("codec_type") == "audio"), None)
        duration = float(data.get("format", {}).get("duration", 0))
        audio_duration = float(audio.get("duration")) if audio and audio.get("duration") is not None else None
        return duration, int(video.get("width", 0)) if video else 0, int(video.get("height", 0)) if video else 0, audio_duration
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("plan", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--receipt", type=Path, required=True, help="不可覆盖的组接来源凭证 JSON")
    args = parser.parse_args()
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        print("ERROR: 需要 ffmpeg 和 ffprobe")
        return 1
    try:
        plan_raw = args.plan.read_bytes()
        plan = json.loads(plan_raw.decode("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: 无法读取时间线：{exc}")
        return 1
    clips = plan.get("clips")
    if not isinstance(clips, list) or not clips:
        print("ERROR: clips 必须为非空数组")
        return 1
    if not isinstance(plan.get("cut_id"), str) or not plan["cut_id"]:
        print("ERROR: 缺少 cut_id")
        return 1
    audio_mode = plan.get("audio_mode")
    if audio_mode not in {"native", "master_mix", "fixture_silence"}:
        print("ERROR: audio_mode 只允许 native/master_mix/fixture_silence")
        return 1

    seen_outputs: set[str] = set()
    receipt_clips: list[dict[str, object]] = []

    command = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-n"]
    filters: list[str] = []
    video_inputs: list[str] = []
    audio_inputs: list[str] = []
    total_duration = 0.0
    for index, clip in enumerate(clips):
        if not isinstance(clip, dict):
            print(f"ERROR: clips[{index}] 不是对象")
            return 1
        output_id = clip.get("output")
        if not isinstance(output_id, str) or not output_id or output_id in seen_outputs:
            print(f"ERROR: clips[{index}] OUTPUT 缺失或重复")
            return 1
        seen_outputs.add(output_id)
        source_file = Path(str(clip.get("file", ""))).expanduser().resolve()
        source_hash = clip.get("file_sha256")
        if not source_file.is_file() or not isinstance(source_hash, str) or not HASH_RE.fullmatch(source_hash):
            print(f"ERROR: clips[{index}] 原 OUTPUT 文件/hash 无效")
            return 1
        if file_hash(source_file).lower() != source_hash.lower():
            print(f"ERROR: clips[{index}] 原 OUTPUT hash 不匹配")
            return 1
        post_id = clip.get("post_id")
        if post_id:
            post_file = Path(str(clip.get("post_file", ""))).expanduser().resolve()
            post_hash = clip.get("post_sha256")
            if not post_file.is_file() or not isinstance(post_hash, str) or not HASH_RE.fullmatch(post_hash):
                print(f"ERROR: clips[{index}] POST 输出文件/hash 无效")
                return 1
            if file_hash(post_file).lower() != post_hash.lower():
                print(f"ERROR: clips[{index}] POST 输出 hash 不匹配")
                return 1
            source_value = post_file
        elif any(key in clip for key in ("post_file", "post_sha256")):
            print(f"ERROR: clips[{index}] 有 POST 文件但缺 post_id")
            return 1
        else:
            source_value = source_file
        source = Path(str(source_value)).expanduser().resolve()
        if not source.is_file():
            print(f"ERROR: clips[{index}] 文件不存在：{source}")
            return 1
        try:
            start = float(clip["in"])
            end = float(clip["out"])
        except (KeyError, TypeError, ValueError):
            print(f"ERROR: clips[{index}] 入出点无效")
            return 1
        if start < 0 or end <= start:
            print(f"ERROR: clips[{index}] 入出点范围无效")
            return 1
        source_probe = media_probe(source)
        if source_probe is None or end > source_probe[0] + 0.05:
            print(f"ERROR: clips[{index}] 源视频不足以覆盖出点")
            return 1
        width, height = source_probe[1], source_probe[2]
        if width <= 0 or height <= 0 or abs((width / height) - (9 / 16)) > 0.003:
            print(f"ERROR: clips[{index}] 输入不是9:16，拒绝拉伸修复")
            return 1
        if audio_mode == "native" and source_probe[3] is not None and source_probe[3] + 0.05 < end:
            print(f"ERROR: clips[{index}] 原生音轨不足以覆盖出点")
            return 1
        total_duration += end - start
        if audio_mode == "native" and not has_audio(source):
            print(f"ERROR: clips[{index}] native 模式但所选媒体没有音轨")
            return 1
        receipt_clips.append({
            "order": index + 1,
            "shot": clip.get("shot"),
            "output": output_id,
            "accepted_output_file": str(source_file),
            "accepted_output_sha256": source_hash.lower(),
            "post_id": post_id or None,
            "selected_file": str(source),
            "selected_sha256": file_hash(source),
            "in": start,
            "out": end,
        })
        command.extend(["-i", str(source)])
        filters.append(f"[{index}:v]trim=start={start}:end={end},setpts=PTS-STARTPTS,scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[v{index}]")
        video_inputs.append(f"[v{index}]")
        if audio_mode == "native":
            filters.append(f"[{index}:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS,aresample=48000[a{index}]")
            audio_inputs.append(f"[a{index}]")
    filters.append("".join(video_inputs) + f"concat=n={len(clips)}:v=1:a=0[vout]")
    if audio_mode == "native":
        filters.append("".join(audio_inputs) + f"concat=n={len(clips)}:v=0:a=1[aout]")
    elif audio_mode == "master_mix":
        mix_file = Path(str(plan.get("mix_file", ""))).expanduser().resolve()
        mix_hash = plan.get("mix_sha256")
        if not mix_file.is_file() or not isinstance(mix_hash, str) or not HASH_RE.fullmatch(mix_hash):
            print("ERROR: master_mix 模式缺混音文件/hash")
            return 1
        if file_hash(mix_file).lower() != mix_hash.lower() or not has_audio(mix_file):
            print("ERROR: 混音文件/hash/音轨无效")
            return 1
        mix_probe = media_probe(mix_file)
        if mix_probe is None or (mix_probe[3] or mix_probe[0]) + 0.05 < total_duration:
            print("ERROR: master_mix 音频时长不足以覆盖整集")
            return 1
        command.extend(["-i", str(mix_file)])
        filters.append(f"[{len(clips)}:a]atrim=start=0:end={total_duration},asetpts=PTS-STARTPTS,aresample=48000[aout]")
    else:
        filters.append(f"anullsrc=r=48000:cl=stereo,atrim=duration={total_duration}[aout]")
    output = args.output.expanduser().resolve()
    receipt = args.receipt.expanduser().resolve()
    if output.exists():
        print("ERROR: 粗剪目标已存在；请使用新的 CUT revision，禁止覆盖")
        return 1
    if receipt.exists():
        print("ERROR: 组接凭证目标已存在；请使用新的 CUT revision，禁止覆盖")
        return 1
    receipt_temporary = receipt.with_suffix(receipt.suffix + ".part")
    if receipt_temporary.exists():
        print("ERROR: 组接凭证临时文件已存在，请先人工核查")
        return 1
    output.parent.mkdir(parents=True, exist_ok=True)
    command.extend([
        "-filter_complex", ";".join(filters),
        "-map", "[vout]", "-map", "[aout]",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "24",
        "-c:a", "aac", "-ar", "48000", "-movflags", "+faststart", str(output),
    ])
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"ERROR: ffmpeg 失败：{result.stderr.strip()}")
        return 1
    probe_result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(output)],
        capture_output=True,
        text=True,
        check=False,
    )
    if probe_result.returncode != 0:
        print(f"ERROR: ffprobe 失败：{probe_result.stderr.strip()}")
        return 1
    final_probe = media_probe(output)
    if final_probe is None or abs(final_probe[0] - total_duration) > 0.15 or final_probe[3] is None or final_probe[3] + 0.15 < total_duration:
        output.unlink(missing_ok=True)
        print("ERROR: 粗剪视频/音频时长没有完整覆盖冻结时间线")
        return 1
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt_payload = {
        "schema": "seedance-cut-assembly-receipt/v1",
        "cut_id": plan["cut_id"],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "plan": {
            "path": str(args.plan.expanduser().resolve()),
            "sha256": hashlib.sha256(plan_raw).hexdigest(),
        },
        "clips": receipt_clips,
        "audio": {
            "mode": audio_mode,
            "mix_file": str(Path(str(plan.get("mix_file"))).expanduser().resolve()) if audio_mode == "master_mix" else None,
            "mix_sha256": plan.get("mix_sha256") if audio_mode == "master_mix" else None,
        },
        "output": {"path": str(output), "sha256": digest},
    }
    try:
        with receipt_temporary.open("x", encoding="utf-8") as stream:
            json.dump(receipt_payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        receipt_temporary.replace(receipt)
    except Exception as exc:
        receipt_temporary.unlink(missing_ok=True)
        output.unlink(missing_ok=True)
        print(f"ERROR: 组接凭证写入失败，已回滚粗剪：{exc}")
        return 1
    print(json.dumps({
        "path": str(output), "sha256": digest,
        "receipt": str(receipt), "receipt_sha256": file_hash(receipt),
        "probe": json.loads(probe_result.stdout),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
