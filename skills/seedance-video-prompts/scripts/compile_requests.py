#!/usr/bin/env python3
"""从结构化 GEN 规格编译并严格校验 BytePlus Seedance 2.5 请求。"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from request_validation import MODEL, ROLE_MAP, validate_payload, valid_locator


GEN_RE = re.compile(r"^GEN-EP\d{3}-\d{3}(?:-\d+)?@r\d+$")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allow-fixture", action="store_true", help="仅机械测试允许 fixture://")
    args = parser.parse_args()
    try:
        document = json.loads(args.spec.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: 无法读取规格：{exc}")
        return 1
    tasks = document.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        print("ERROR: tasks 必须是非空数组")
        return 1
    if document.get("model", MODEL) != MODEL:
        print("ERROR: model 与已核实 Seedance 2.5 档案不一致")
        return 1

    errors: list[str] = []
    compiled: list[tuple[str, dict[str, object]]] = []
    seen: set[str] = set()
    for index, task in enumerate(tasks, 1):
        if not isinstance(task, dict):
            errors.append(f"task[{index}] 不是对象")
            continue
        gen = task.get("gen_id")
        prompt = task.get("prompt")
        refs = task.get("refs", [])
        if not isinstance(gen, str) or not GEN_RE.fullmatch(gen):
            errors.append(f"task[{index}] gen_id 非法")
            continue
        if gen in seen:
            errors.append(f"GEN 重复 {gen}")
        seen.add(gen)
        if not isinstance(prompt, str) or not prompt.strip() or not isinstance(refs, list):
            errors.append(f"{gen}: prompt 或 refs 非法")
            continue
        content: list[dict[str, object]] = [{"type": "text", "text": prompt.strip()}]
        reference_seconds = {"video": 0.0, "audio": 0.0}
        for ref_index, ref in enumerate(refs, 1):
            if not isinstance(ref, dict):
                errors.append(f"{gen}: refs[{ref_index}] 不是对象")
                continue
            kind, role, locator = ref.get("kind"), ref.get("role"), ref.get("url")
            if kind not in ROLE_MAP or role not in ROLE_MAP[kind]:
                errors.append(f"{gen}: refs[{ref_index}] kind/role 非法")
                continue
            if not isinstance(locator, str) or not valid_locator(locator, allow_fixture=args.allow_fixture):
                errors.append(f"{gen}: refs[{ref_index}] URL/asset ID 非法")
                continue
            item_type = f"{kind}_url"
            body: dict[str, object] = {"url": locator}
            if kind in {"video", "audio"}:
                declared = ref.get("duration_seconds")
                if not isinstance(declared, (int, float)) or declared < 2 or declared > 30:
                    errors.append(f"{gen}: refs[{ref_index}] {kind} 时长必须在2—30秒")
                else:
                    reference_seconds[kind] += float(declared)
            content.append({"type": item_type, item_type: body, "role": role})
        if reference_seconds["video"] > 30 or reference_seconds["audio"] > 30:
            errors.append(f"{gen}: 视频或音频参考总时长超过30秒")
        request: dict[str, object] = {
            "model": MODEL,
            "content": content,
            "generate_audio": task.get("generate_audio"),
            "ratio": task.get("ratio", "9:16"),
            "duration": task.get("duration"),
            "resolution": task.get("resolution", "720p"),
            "return_last_frame": task.get("return_last_frame", True),
            "watermark": task.get("watermark", False),
        }
        if any(item.get("role") in {"reference_image", "reference_video", "reference_audio"} for item in content):
            request["omni_reference_task_type"] = "reference"
        request["output_format"] = "mp4"
        for error in validate_payload(request, allow_fixture=args.allow_fixture):
            errors.append(f"{gen}: {error}")
        compiled.append((gen, request))

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"FAILED: {len(errors)} 项")
        return 1
    args.output.mkdir(parents=True, exist_ok=True)
    rendered: list[tuple[str, Path, bytes]] = []
    for gen, request in compiled:
        path = args.output / (gen.replace("@", "-") + ".json")
        data = (json.dumps(request, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if path.exists() and path.read_bytes() != data:
            print(f"ERROR: {path} 已存在且内容不同；请提升 GEN revision")
            return 1
        rendered.append((gen, path, data))
    for gen, path, data in rendered:
        path.write_bytes(data)
        print(f"{gen}\t{hashlib.sha256(data).hexdigest()}\t{path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
