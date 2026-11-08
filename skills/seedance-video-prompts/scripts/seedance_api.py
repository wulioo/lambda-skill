#!/usr/bin/env python3
"""提交或查询 Seedance 请求；提交前全量校验并原子预留授权次数。"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
import uuid
import time
from datetime import datetime, timezone
from pathlib import Path

from request_validation import MODEL, load_and_validate
from archive_result import archive


BASE = "https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks"
ISO8601_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T")


def cells(line: str) -> list[str]:
    if not line.lstrip().startswith("|"):
        return []
    return [item.strip() for item in line.strip().strip("|").split("|")]


def read_authorization(path: Path, request: Path, digest: str, model: str) -> tuple[int, int, str] | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    global_values: dict[str, str] = {}
    for name in ("project_submission_limit",):
        for line in text.splitlines():
            if line.startswith(f"- {name}："):
                global_values[name] = line.split("：", 1)[1].strip()
    try:
        project_limit = int(global_values["project_submission_limit"])
    except (KeyError, ValueError):
        return None
    if project_limit <= 0:
        return None
    for line in text.splitlines():
        row = cells(line)
        if len(row) != 7 or row[-1] != "accepted":
            continue
        request_value, approved_hash, approved_model, limit, approver, approved_at, _status = row
        try:
            maximum = int(limit)
        except ValueError:
            continue
        same_request = request_value in {request.name, str(request.resolve())}
        if (
            same_request and approved_hash.lower() == digest.lower() and approved_model == model
            and approver and ISO8601_RE.match(approved_at) and maximum > 0
        ):
            return maximum, project_limit, approver
    return None


def call(url: str, api_key: str, data: bytes | None = None) -> dict[str, object]:
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if data is not None else "GET",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code}: {body}") from exc


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_log(stream) -> list[dict[str, object]]:
    stream.seek(0)
    records: list[dict[str, object]] = []
    for number, line in enumerate(stream, 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"submission log 第{number}行损坏，拒绝计费操作") from exc
        if not isinstance(value, dict):
            raise RuntimeError(f"submission log 第{number}行不是对象，拒绝计费操作")
        records.append(value)
    return records


def latest_reservations(records: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    """按日志顺序聚合每个 reservation 的最新状态，避免事件重复计费。"""
    latest: dict[str, dict[str, object]] = {}
    for index, record in enumerate(records):
        reservation_id = record.get("reservation_id")
        if not isinstance(reservation_id, str) or not reservation_id:
            # 旧格式没有 reservation_id 时宁可按单独占用处理，不静默释放预算。
            reservation_id = f"legacy-{index}"
        latest[reservation_id] = record
    return latest


def reserve(log_path: Path, request: Path, digest: str, limits: tuple[int, int, str]) -> str:
    maximum, project_limit, approver = limits
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        records = load_log(stream)
        charged_states = {"reserved", "submitted", "succeeded", "unknown"}
        latest = latest_reservations(records).values()
        request_count = sum(
            1 for record in latest
            if record.get("request_sha256") == digest and record.get("state") in charged_states
        )
        project_count = sum(1 for record in latest if record.get("state") in charged_states)
        if request_count >= maximum:
            raise RuntimeError("已达到该请求的最大授权提交次数")
        if project_count >= project_limit:
            raise RuntimeError("已达到项目总授权提交次数上限")
        reservation_id = str(uuid.uuid4())
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps({
            "event": "reservation",
            "reservation_id": reservation_id,
            "request": str(request.resolve()),
            "request_sha256": digest,
            "model": MODEL,
            "authorized_by": approver,
            "reserved_at": now(),
            "state": "reserved",
        }, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())
        return reservation_id


def append_event(log_path: Path, event: dict[str, object]) -> None:
    with log_path.open("a+", encoding="utf-8") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        stream.seek(0, os.SEEK_END)
        stream.write(json.dumps(event, ensure_ascii=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def submission_for(log_path: Path, task_id: str, digest: str) -> dict[str, object] | None:
    if not log_path.is_file():
        return None
    with log_path.open("r", encoding="utf-8") as stream:
        records = load_log(stream)
    matches = [
        record for record in records
        if record.get("event") == "submit_result"
        and record.get("state") == "submitted"
        if record.get("task_id") == task_id
        and str(record.get("request_sha256", "")).lower() == digest.lower()
    ]
    return matches[-1] if matches else None


def result_urls(result: dict[str, object]) -> tuple[str | None, str | None]:
    content = result.get("content")
    if not isinstance(content, dict):
        return None, None
    video = content.get("video_url")
    last = content.get("last_frame_url")
    return (
        video if isinstance(video, str) and video else None,
        last if isinstance(last, str) and last else None,
    )


def poll_and_archive(
    *, task_id: str, request: Path, digest: str, log_path: Path,
    reservation_id: str, api_key: str, output: Path,
    last_frame_output: Path | None, interval: float, timeout: float,
    allow_fixture: bool, authorized_by: str,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while True:
        result = call(f"{BASE}/{task_id}", api_key)
        status = str(result.get("status", "")).lower()
        if status == "succeeded":
            video_url, last_frame_url = result_urls(result)
            if not video_url:
                raise RuntimeError("任务 succeeded 但响应缺 content.video_url")
            append_event(log_path, {
                "event": "task_result", "reservation_id": reservation_id,
                "request": str(request.resolve()), "model": MODEL,
                "authorized_by": authorized_by,
                "request_sha256": digest, "task_id": task_id,
                "state": "succeeded", "recorded_at": now(),
            })
            try:
                archived = archive(
                    video_url, output, request, digest,
                    last_frame_url=last_frame_url,
                    last_frame_output_value=last_frame_output,
                    allow_fixture=allow_fixture,
                )
            except Exception as exc:
                append_event(log_path, {
                    "event": "archive_result", "reservation_id": reservation_id,
                    "request": str(request.resolve()), "model": MODEL,
                    "authorized_by": authorized_by,
                    "request_sha256": digest, "task_id": task_id,
                    "state": "succeeded", "archive_state": "failed",
                    "recorded_at": now(), "error": str(exc),
                })
                raise RuntimeError("任务已成功但本地归档失败；请用 collect 续收，禁止重提") from exc
            append_event(log_path, {
                "event": "archive_result", "reservation_id": reservation_id,
                "request": str(request.resolve()), "model": MODEL,
                "authorized_by": authorized_by,
                "request_sha256": digest, "task_id": task_id,
                "state": "succeeded", "archive_state": "archived",
                "recorded_at": now(), "archive": archived,
            })
            return {"task": result, "archive": archived}
        if status in {"failed", "expired", "cancelled", "canceled"}:
            append_event(log_path, {
                "event": "task_result", "reservation_id": reservation_id,
                "request": str(request.resolve()), "model": MODEL,
                "authorized_by": authorized_by,
                "request_sha256": digest, "task_id": task_id,
                "state": "failed", "platform_status": status,
                "recorded_at": now(), "error": result.get("error"),
            })
            raise RuntimeError(f"任务终止：{status}；{result.get('error')}")
        if status not in {"queued", "running"}:
            raise RuntimeError(f"任务返回未知状态：{status or '空'}，停止自动处理")
        if time.monotonic() >= deadline:
            append_event(log_path, {
                "event": "poll_timeout", "reservation_id": reservation_id,
                "request": str(request.resolve()), "model": MODEL,
                "authorized_by": authorized_by,
                "request_sha256": digest, "task_id": task_id,
                "state": "submitted", "recorded_at": now(),
            })
            raise RuntimeError("轮询超时；任务仍保持 submitted，请用 collect 续收，禁止重提")
        time.sleep(min(interval, max(0.0, deadline - time.monotonic())))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    submit = sub.add_parser("submit")
    submit.add_argument("request", type=Path)
    submit.add_argument("--expected-sha256", required=True)
    submit.add_argument("--authorization", type=Path, required=True)
    submit.add_argument("--submission-log", type=Path, required=True)
    submit.add_argument("--project-root", type=Path, required=True, help="付费前强制运行四阶段项目门禁")
    submit.add_argument("--allow-fixture", action="store_true", help="禁止用于 API 提交；出现即失败")
    run = sub.add_parser("run", help="提交、轮询并立即归档")
    run.add_argument("request", type=Path)
    run.add_argument("output", type=Path)
    run.add_argument("--expected-sha256", required=True)
    run.add_argument("--authorization", type=Path, required=True)
    run.add_argument("--submission-log", type=Path, required=True)
    run.add_argument("--project-root", type=Path, required=True, help="付费前强制运行四阶段项目门禁")
    run.add_argument("--last-frame-output", type=Path)
    run.add_argument("--poll-interval", type=float, default=10.0)
    run.add_argument("--timeout", type=float, default=3600.0)
    run.add_argument("--allow-fixture", action="store_true", help="禁止用于 API 提交；出现即失败")
    collect = sub.add_parser("collect", help="续收已提交任务，不新增付费提交")
    collect.add_argument("task_id")
    collect.add_argument("request", type=Path)
    collect.add_argument("output", type=Path)
    collect.add_argument("--expected-sha256", required=True)
    collect.add_argument("--submission-log", type=Path, required=True)
    collect.add_argument("--last-frame-output", type=Path)
    collect.add_argument("--poll-interval", type=float, default=10.0)
    collect.add_argument("--timeout", type=float, default=3600.0)
    collect.add_argument("--allow-fixture", action="store_true", help="禁止用于 API 续收；出现即失败")
    get = sub.add_parser("get")
    get.add_argument("task_id")
    parser.add_argument("--api-key-env", default="ARK_API_KEY")
    args = parser.parse_args()
    if getattr(args, "allow_fixture", False):
        print("ERROR: seedance_api 禁止 --allow-fixture；测试素材只能进入编译和门禁，不得触发真实 API")
        return 1
    api_key = os.environ.get(args.api_key_env)
    if not api_key:
        print(f"ERROR: 环境变量 {args.api_key_env} 未配置")
        return 1
    try:
        if args.command in {"submit", "run"}:
            if args.command == "run" and (args.poll_interval <= 0 or args.timeout <= 0):
                raise RuntimeError("poll-interval 和 timeout 必须大于0")
            raw = args.request.read_bytes()
            actual_hash = hashlib.sha256(raw).hexdigest()
            if actual_hash.lower() != args.expected_sha256.lower():
                raise RuntimeError("请求文件 SHA-256 与冻结值不一致，禁止提交")
            payload, validation = load_and_validate(args.request, allow_fixture=args.allow_fixture)
            if validation or payload is None:
                raise RuntimeError("请求门禁失败：" + "；".join(validation))
            if payload.get("model") != MODEL:
                raise RuntimeError("请求模型与已核实档案不一致")
            roles = {
                item.get("role") for item in payload.get("content", []) if isinstance(item, dict)
            }
            if roles & {"reference_image", "reference_video", "reference_audio"}:
                if payload.get("omni_reference_task_type") != "reference":
                    raise RuntimeError("正式 omni 生成必须显式锁定 omni_reference_task_type=reference")
            if payload.get("output_format") != "mp4":
                raise RuntimeError("正式短剧请求必须显式锁定 output_format=mp4")
            request_root = (args.project_root.resolve() / "seedance-video-prompts" / "requests").resolve()
            if args.request.resolve().parent != request_root:
                raise RuntimeError("付费请求必须位于当前项目 seedance-video-prompts/requests/")
            import subprocess

            guard = Path(__file__).with_name("pipeline_guard.py")
            checked = subprocess.run(
                [sys.executable, str(guard), str(args.project_root.resolve()), "--pre-submit"],
                capture_output=True, text=True, check=False,
            )
            if checked.returncode != 0:
                raise RuntimeError("项目付费前门禁失败：" + (checked.stdout + checked.stderr).strip())
            limits = read_authorization(args.authorization, args.request, actual_hash, MODEL)
            if limits is None:
                raise RuntimeError("付费授权缺失，或预算/候选/轮次字段无效")
            reservation_id = reserve(args.submission_log, args.request, actual_hash, limits)
            try:
                result = call(BASE, api_key, raw)
            except Exception as exc:
                append_event(args.submission_log, {
                    "event": "submit_result", "reservation_id": reservation_id,
                    "request": str(args.request.resolve()), "model": MODEL,
                    "authorized_by": limits[2],
                    "request_sha256": actual_hash, "state": "unknown",
                    "recorded_at": now(), "error": str(exc),
                })
                raise RuntimeError("提交结果未知；必须人工查询/核销 reservation，禁止自动重提") from exc
            task_id = result.get("id") or result.get("task_id")
            if not task_id:
                append_event(args.submission_log, {
                    "event": "submit_result", "reservation_id": reservation_id,
                    "request": str(args.request.resolve()), "model": MODEL,
                    "authorized_by": limits[2],
                    "request_sha256": actual_hash, "state": "unknown", "recorded_at": now(),
                    "response": result,
                })
                raise RuntimeError("响应缺 task ID；该预留保持 unknown，禁止自动重提")
            append_event(args.submission_log, {
                "event": "submit_result", "reservation_id": reservation_id,
                "request": str(args.request.resolve()), "request_sha256": actual_hash,
                "model": MODEL, "authorized_by": limits[2],
                "submitted_at": now(), "task_id": task_id, "state": "submitted",
            })
            result["_request_sha256"] = actual_hash
            result["_reservation_id"] = reservation_id
            if args.command == "run":
                result = poll_and_archive(
                    task_id=str(task_id), request=args.request,
                    digest=actual_hash, log_path=args.submission_log,
                    reservation_id=reservation_id, api_key=api_key,
                    output=args.output, last_frame_output=args.last_frame_output,
                    interval=args.poll_interval, timeout=args.timeout,
                    allow_fixture=False, authorized_by=limits[2],
                )
        elif args.command == "collect":
            if args.poll_interval <= 0 or args.timeout <= 0:
                raise RuntimeError("poll-interval 和 timeout 必须大于0")
            raw = args.request.read_bytes()
            actual_hash = hashlib.sha256(raw).hexdigest()
            if actual_hash.lower() != args.expected_sha256.lower():
                raise RuntimeError("请求文件 SHA-256 与冻结值不一致")
            payload, validation = load_and_validate(args.request, allow_fixture=args.allow_fixture)
            if validation or payload is None:
                raise RuntimeError("请求门禁失败：" + "；".join(validation))
            record = submission_for(args.submission_log, args.task_id, actual_hash)
            if record is None:
                raise RuntimeError("submission log 中没有匹配 task ID/request hash，拒绝续收")
            reservation_id = str(record.get("reservation_id", ""))
            authorized_by = str(record.get("authorized_by", ""))
            if not reservation_id:
                raise RuntimeError("匹配提交记录缺 reservation_id，需人工核查")
            if not authorized_by:
                raise RuntimeError("匹配提交记录缺 authorized_by，需人工核查")
            result = poll_and_archive(
                task_id=args.task_id, request=args.request,
                digest=actual_hash, log_path=args.submission_log,
                reservation_id=reservation_id, api_key=api_key,
                output=args.output, last_frame_output=args.last_frame_output,
                interval=args.poll_interval, timeout=args.timeout,
                allow_fixture=False, authorized_by=authorized_by,
            )
        else:
            result = call(f"{BASE}/{args.task_id}", api_key)
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"ERROR: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
