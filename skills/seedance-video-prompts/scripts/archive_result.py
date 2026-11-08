#!/usr/bin/env python3
"""按冻结请求下载视频与返回尾帧，并核对媒体规格后原子归档。"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from request_validation import load_and_validate


def probe(path: Path) -> dict[str, object] | None:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


def download(url: str, target: Path) -> None:
    if urlparse(url).scheme != "https":
        raise RuntimeError("只接受 HTTPS 临时下载地址")
    if target.exists():
        raise RuntimeError(f"归档目标已存在：{target}")
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(url, timeout=60) as response, temporary.open("xb") as stream:
            shutil.copyfileobj(response, stream)
        temporary.replace(target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def archive(
    url: str,
    output_value: Path,
    request_path: Path,
    expected_request_sha256: str,
    *,
    last_frame_url: str | None = None,
    last_frame_output_value: Path | None = None,
    allow_fixture: bool = False,
) -> dict[str, object]:
    """归档一个已成功任务；失败时只删除本次调用创建的文件。"""
    created_output = False
    created_last_frame = False
    output = output_value.expanduser().resolve()
    last = last_frame_output_value.expanduser().resolve() if last_frame_output_value else None
    try:
        raw = request_path.read_bytes()
        if hashlib.sha256(raw).hexdigest().lower() != expected_request_sha256.lower():
            raise RuntimeError("请求文件 hash 与冻结值不一致")
        request, errors = load_and_validate(request_path, allow_fixture=allow_fixture)
        if errors or request is None:
            raise RuntimeError("请求门禁失败：" + "；".join(errors))
        download(url, output)
        created_output = True
        metadata = probe(output)
        if metadata is None:
            raise RuntimeError("视频 ffprobe 失败")
        videos = [s for s in metadata.get("streams", []) if s.get("codec_type") == "video"]
        audios = [s for s in metadata.get("streams", []) if s.get("codec_type") == "audio"]
        if not videos:
            raise RuntimeError("归档结果没有视频流")
        duration = float(metadata.get("format", {}).get("duration", 0))
        expected_duration = float(request["duration"])
        if abs(duration - expected_duration) > 0.5:
            raise RuntimeError(f"归档时长 {duration:g}s 与请求 {expected_duration:g}s 不一致")
        expected_dims = {
            ("720p", "9:16"): (720, 1280), ("480p", "9:16"): (480, 854),
        }.get((request.get("resolution"), request.get("ratio")))
        actual_dims = (int(videos[0].get("width", 0)), int(videos[0].get("height", 0)))
        if expected_dims and actual_dims != expected_dims:
            raise RuntimeError(f"归档尺寸 {actual_dims} 与请求 {expected_dims} 不一致")
        if request.get("ratio") == "adaptive" and actual_dims[0] >= actual_dims[1]:
            raise RuntimeError("短剧 adaptive 输出不是竖屏")
        expected_format = request.get("output_format", "mp4")
        actual_format = str(metadata.get("format", {}).get("format_name", ""))
        if expected_format == "mp4" and "mp4" not in actual_format:
            raise RuntimeError(f"归档容器 {actual_format} 与请求 mp4 不一致")
        frame_rate = str(videos[0].get("avg_frame_rate") or videos[0].get("r_frame_rate") or "0/1")
        try:
            numerator, denominator = (float(value) for value in frame_rate.split("/", 1))
            fps = numerator / denominator
        except (ValueError, ZeroDivisionError):
            fps = 0
        if not 24 <= fps <= 60:
            raise RuntimeError(f"归档帧率 {fps:g} 不在平台声明范围 24—60")
        if bool(request.get("generate_audio")) != bool(audios):
            raise RuntimeError("归档音轨与 generate_audio 不一致")
        result: dict[str, object] = {
            "path": str(output), "sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
            "request_sha256": expected_request_sha256.lower(), "probe": metadata,
        }
        if request.get("return_last_frame"):
            if not last_frame_url or last is None:
                raise RuntimeError("请求要求 return_last_frame，但未提供尾帧 URL/输出路径")
            download(last_frame_url, last)
            created_last_frame = True
            last_probe = probe(last)
            if last_probe is None:
                raise RuntimeError("返回尾帧无法读取")
            streams = [s for s in last_probe.get("streams", []) if s.get("codec_type") == "video"]
            if not streams or (int(streams[0].get("width", 0)), int(streams[0].get("height", 0))) != actual_dims:
                raise RuntimeError("返回尾帧尺寸与视频不一致")
            result["last_frame"] = {"path": str(last), "sha256": hashlib.sha256(last.read_bytes()).hexdigest()}
        return result
    except Exception:
        if created_output:
            output.unlink(missing_ok=True)
        if created_last_frame and last is not None:
            last.unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("output", type=Path)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--expected-request-sha256", required=True)
    parser.add_argument("--last-frame-url")
    parser.add_argument("--last-frame-output", type=Path)
    parser.add_argument("--allow-fixture", action="store_true")
    args = parser.parse_args()
    if not shutil.which("ffprobe"):
        print("ERROR: 缺少 ffprobe")
        return 1
    try:
        result = archive(
            args.url, args.output, args.request, args.expected_request_sha256,
            last_frame_url=args.last_frame_url,
            last_frame_output_value=args.last_frame_output,
            allow_fixture=args.allow_fixture,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(f"ERROR: 归档失败：{exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
