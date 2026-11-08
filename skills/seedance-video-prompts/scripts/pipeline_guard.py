#!/usr/bin/env python3
"""运行四阶段门禁，并校验所有下游 SRC/DIR 引用仍由当前导演底稿定义。"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


SRC_RE = re.compile(r"\bSRC-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
DIR_RE = re.compile(r"\bDIR-[A-Z0-9]+(?:-[A-Z0-9]+)*@r\d+\b")
PROJECT_RE = re.compile(r"^- project_id：([a-z0-9][a-z0-9-]*)$", re.M)
BLOCK_RE = re.compile(r"\bBLOCK-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")


def run(script: Path, args: list[str]) -> list[str]:
    result = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True)
    if result.returncode == 0:
        print(result.stdout.strip())
        return []
    return [line for line in (result.stdout + result.stderr).splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("--allow-fixture", action="store_true", help="仅用于机械闭环测试")
    parser.add_argument("--pre-submit", action="store_true", help="付费前只校验到冻结请求")
    args = parser.parse_args()
    project = args.project.resolve()
    skills = Path(__file__).resolve().parents[2]
    director = project / "seedance-director"
    assets = project / "seedance-art-assets"
    storyboard = project / "seedance-storyboard"
    video = project / "seedance-video-prompts"
    checks: list[tuple[Path, list[str]]] = [
        (skills / "seedance-short-drama-director/scripts/director_guard.py", [str(director)]),
        (skills / "seedance-art-assets/scripts/art_assets_guard.py", [str(assets)]),
        (skills / "seedance-storyboard/scripts/storyboard_guard.py", [str(storyboard), str(assets)]),
        (
            skills / "seedance-video-prompts/scripts/video_guard.py",
            [
                str(video), str(storyboard), str(assets),
                *(["--allow-fixture"] if args.allow_fixture else []),
                *(["--pre-submit"] if args.pre_submit else []),
            ],
        ),
    ]
    errors: list[str] = []
    for script, check_args in checks:
        errors.extend(run(script, check_args))

    project_sources = {
        "导演": director / "project-brief.md",
        "美术规格": assets / "asset-index.md",
        "美术": assets / "reference-manifest.md",
        "视频": video / "capability-profile.md",
        "声音": video / "sound-plan.md",
        "POST": video / "post-plan.md",
    }
    for path in sorted((storyboard / "episodes").glob("EP*-production.md")):
        project_sources[f"分镜/{path.name}"] = path
    for path in sorted(video.rglob("*.md")):
        if "archive" not in path.parts:
            project_sources[f"视频产物/{path.relative_to(video)}"] = path
    project_ids: dict[str, str] = {}
    for label, path in project_sources.items():
        text_value = path.read_text(encoding="utf-8") if path.is_file() else ""
        match = PROJECT_RE.search(text_value)
        if not match:
            errors.append(f"{path}: 缺合法 project_id")
        else:
            project_ids[label] = match.group(1)
    if len(set(project_ids.values())) > 1:
        errors.append(f"四阶段 project_id 不一致：{project_ids}")

    director_text = "\n".join(path.read_text(encoding="utf-8") for path in director.rglob("*.md") if "approvals" not in path.parts and "reviews" not in path.parts)
    defined_src = set(SRC_RE.findall(director_text))
    active_dir: set[str] = set()
    for line in director_text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if cells and DIR_RE.fullmatch(cells[0]) and len(cells) >= 4 and cells[3] in {"生效", "已确认"}:
            active_dir.add(cells[0])

    for stage in (assets, storyboard, video):
        for path in stage.rglob("*.md"):
            text = path.read_text(encoding="utf-8")
            for ref in set(SRC_RE.findall(text)) - defined_src:
                errors.append(f"{path}: 引用当前导演底稿未定义来源 {ref}")
            for ref in set(DIR_RE.findall(text)) - active_dir:
                errors.append(f"{path}: 引用非当前生效导演决定 {ref}")
            for number, line in enumerate(text.splitlines(), 1):
                row = [cell.strip() for cell in line.strip().strip("|").split("|")] if line.lstrip().startswith("|") else []
                if row and BLOCK_RE.fullmatch(row[0]):
                    status = next((value for value in row if value in {"blocked", "待解决", "已解决", "已失效", "resolved", "deprecated"}), "")
                    if status not in {"已解决", "已失效", "resolved", "deprecated"}:
                        errors.append(f"{path}:{number}: 最终交付仍有未解 BLOCK {row[0]}")
                elif re.search(r"lifecycle_status[：:]\s*blocked", line):
                    errors.append(f"{path}:{number}: 最终交付仍有 blocked 对象")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"PIPELINE FAILED: {len(errors)} 项")
        return 1
    suffix = "付费前门禁" if args.pre_submit else "四阶段门禁"
    print(f"PIPELINE OK: {suffix}通过，SRC/DIR 引用当前有效且无未解阻断")
    return 0


if __name__ == "__main__":
    sys.exit(main())
