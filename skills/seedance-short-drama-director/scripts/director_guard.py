#!/usr/bin/env python3
"""校验 Seedance 导演交付的当前来源、决定、确认、交底和双角色批准。"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SRC_RE = re.compile(r"\bSRC-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
DIR_RE = re.compile(r"\bDIR-[A-Z0-9]+(?:-[A-Z0-9]+)*@r\d+\b")
DIR_FULL_RE = re.compile(r"(DIR-[A-Z0-9]+(?:-[A-Z0-9]+)*)@r(\d+)")
CONF_RE = re.compile(r"\bCONF-[A-Z0-9]+(?:-[A-Z0-9]+)*\b")
SCENE_RE = re.compile(r"^###\s+SCENE-EP\d{3}-\d{3}\b")
BLOCK_RE = re.compile(r"^BLOCK-[A-Z0-9]+(?:-[A-Z0-9]+)*$")
HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
ACTIVE = {"生效", "已确认"}
STATUSES = ACTIVE | {"待用户确认", "待复核", "已失效"}
HANDOFF_HEADINGS = {
    "## 给美术资产 Skill 的剧情约束",
    "## 给分镜脚本 Skill 的导演交底",
}
COVERAGE_SEPARATOR_RE = re.compile(r"[、,，;；/|｜]+")


@dataclass(frozen=True)
class Decision:
    logical_id: str
    revision: int
    supersedes: str
    status: str
    source_refs: tuple[str, ...]
    confirmation_refs: tuple[str, ...]
    location: str


def table_cells(line: str) -> list[str]:
    if not line.lstrip().startswith("|"):
        return []
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*.md")
        if "reviews" not in path.parts and "approvals" not in path.parts
    )


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def meaningful_bullet(line: str) -> bool:
    stripped = line.strip()
    return stripped.startswith("- ") and stripped not in {"-", "- 约束内容。"}


def valid_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "T" in value
    except ValueError:
        return False


def canonical_coverage(value: str) -> tuple[str, ...]:
    """把覆盖范围按无序原子集合比较，防止仅靠重排制造第二个当前来源。"""
    units = {
        re.sub(r"\s+", "", unit).casefold()
        for unit in COVERAGE_SEPARATOR_RE.split(value)
        if re.sub(r"\s+", "", unit)
    }
    return tuple(sorted(units))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path, help="项目内 seedance-director 目录")
    args = parser.parse_args()
    root = args.root.resolve()
    files = markdown_files(root) if root.is_dir() else []
    errors: list[str] = []

    if not files:
        print(f"ERROR: 未找到导演 Markdown：{root}")
        return 1

    project_brief = root / "project-brief.md"
    project_text = project_brief.read_text(encoding="utf-8") if project_brief.is_file() else ""
    if not re.search(r"^- project_id：[a-z0-9][a-z0-9-]*$", project_text, re.M):
        errors.append("project-brief.md 缺合法 project_id")

    pilot_mode = bool(re.search(r"^- (?:制作模式|模式)：前两集试播(?:\s|/|｜|$)", project_text, re.M))
    if pilot_mode:
        if not (root / "pilot-brief.md").is_file():
            errors.append("前两集试播模式缺少 pilot-brief.md")
        for episode in ("EP001.md", "EP002.md"):
            if not (root / "episodes" / episode).is_file():
                errors.append(f"前两集试播模式缺少 episodes/{episode}")

    sources: dict[str, str] = {}
    source_logical: dict[str, str] = {}
    source_coverage: dict[tuple[str, ...], str] = {}
    for number, line in enumerate(project_text.splitlines(), 1):
        cells = table_cells(line)
        if not cells or cells[0] == "SRC-ID" or not SRC_RE.fullmatch(cells[0]):
            continue
        location = f"{project_brief}:{number}"
        if cells[0] in sources:
            errors.append(f"{location}: 当前 SRC-ID 重复，首次定义于 {sources[cells[0]]}")
            continue
        sources[cells[0]] = location
        if len(cells) < 5 or not all(cells[index] for index in range(1, 5)):
            errors.append(f"{location}: 当前来源列不完整")
            continue
        logical_id = cells[0].rsplit("-", 1)[0]
        coverage = canonical_coverage(cells[4])
        if logical_id in source_logical:
            errors.append(
                f"{location}: 同一逻辑来源 {logical_id} 只能有一个当前修订，"
                f"已定义于 {source_logical[logical_id]}"
            )
        else:
            source_logical[logical_id] = location
        if not coverage:
            errors.append(f"{location}: 当前来源覆盖范围不能为空")
        elif coverage in source_coverage:
            errors.append(
                f"{location}: 来源覆盖范围‘{cells[4]}’已有当前来源，"
                f"旧修订必须先退出当前来源表；已定义于 {source_coverage[coverage]}"
            )
        else:
            source_coverage[coverage] = location
        if not HASH_RE.fullmatch(cells[3]):
            errors.append(f"{location}: 当前来源必须有64位 SHA-256")
            continue
        source_path = Path(cells[1]).expanduser()
        if not source_path.is_absolute() or not source_path.is_file():
            errors.append(f"{location}: 当前生产来源必须是存在的绝对本地文件")
        elif file_hash(source_path).lower() != cells[3].lower():
            errors.append(f"{location}: SRC SHA-256 与来源文件不匹配")
    if not sources:
        errors.append("project-brief.md 没有定义当前 SRC-ID")

    confirmations: dict[str, str] = {}
    confirmation_file = root / "approvals" / "user-confirmations.md"
    if confirmation_file.is_file():
        for number, line in enumerate(confirmation_file.read_text(encoding="utf-8").splitlines(), 1):
            cells = table_cells(line)
            if not cells or cells[0] == "CONF-ID" or not CONF_RE.fullmatch(cells[0]):
                continue
            location = f"{confirmation_file}:{number}"
            if cells[0] in confirmations:
                errors.append(f"{location}: CONF-ID 重复，首次定义于 {confirmations[cells[0]]}")
            elif len(cells) < 7 or not all(cells[index] for index in range(1, 7)):
                errors.append(f"{location}: 用户关键确认列不完整")
            elif not valid_iso8601(cells[6]):
                errors.append(f"{location}: 用户确认时间必须是 ISO-8601")
            else:
                confirmations[cells[0]] = location

    decisions: dict[str, Decision] = {}
    decisions_by_logical: dict[str, list[tuple[str, Decision]]] = {}
    contents: dict[Path, list[str]] = {}
    for path in files:
        lines = path.read_text(encoding="utf-8").splitlines()
        contents[path] = lines
        for number, line in enumerate(lines, 1):
            cells = table_cells(line)
            if not cells:
                continue
            first = cells[0]
            location = f"{path}:{number}"
            if BLOCK_RE.fullmatch(first):
                if len(cells) < 6 or cells[4] not in {"已解决", "已失效"} or not cells[5]:
                    errors.append(f"{location}: 最终导演底稿仍有未解锁事实阻断 {first}")
                continue
            match = DIR_FULL_RE.fullmatch(first)
            if not match:
                continue
            if first in decisions:
                errors.append(f"{location}: DIR-ID 修订重复，首次定义于 {decisions[first].location}")
                continue
            if len(cells) < 7:
                errors.append(f"{location}: 导演决定列不完整")
                continue
            source_refs = tuple(SRC_RE.findall(cells[4]))
            confirmation_refs = tuple(CONF_RE.findall(cells[4]))
            decision = Decision(
                logical_id=match.group(1),
                revision=int(match.group(2)),
                supersedes=cells[1],
                status=cells[3],
                source_refs=source_refs,
                confirmation_refs=confirmation_refs,
                location=location,
            )
            decisions[first] = decision
            decisions_by_logical.setdefault(decision.logical_id, []).append((first, decision))
            if decision.status not in STATUSES:
                errors.append(f"{location}: 非法决定状态‘{decision.status}’")
            if decision.status == "待用户确认":
                errors.append(f"{location}: 仍有会改变当前成片的关键确认，导演底稿不得发布")
            if not source_refs:
                errors.append(f"{location}: 导演决定缺少当前 SRC-ID 来源")
            if decision.status == "已确认" and not confirmation_refs:
                errors.append(f"{location}: ‘已确认’决定必须引用 CONF-ID")
            if not cells[5]:
                errors.append(f"{location}: 导演决定缺少影响范围")
            if decision.status == "已失效" and not cells[6]:
                errors.append(f"{location}: 已失效决定缺少替代/失效理由")
    if not decisions:
        errors.append("导演交付没有定义任何 DIR-ID")

    for decision_id, decision in decisions.items():
        for source_id in decision.source_refs:
            if source_id not in sources:
                errors.append(f"{decision.location}: {decision_id} 引用了非当前来源 {source_id}")
        for confirmation_id in decision.confirmation_refs:
            if confirmation_id not in confirmations:
                errors.append(f"{decision.location}: {decision_id} 引用了未定义确认 {confirmation_id}")
        superseded = DIR_RE.findall(decision.supersedes)
        if decision.revision > 1 and len(superseded) != 1:
            errors.append(f"{decision.location}: r2 以上修订必须且只能 supersedes 一个旧修订")
        for old_id in superseded:
            old = decisions.get(old_id)
            if old is None:
                errors.append(f"{decision.location}: supersedes 引用了未定义修订 {old_id}")
            elif old.logical_id != decision.logical_id or old.revision >= decision.revision:
                errors.append(f"{decision.location}: supersedes 必须指向同一逻辑决定的更早修订")

    for logical_id, versions in decisions_by_logical.items():
        active = [(identifier, item) for identifier, item in versions if item.status in ACTIVE]
        if len(active) > 1:
            ids = "、".join(identifier for identifier, _ in active)
            errors.append(f"{logical_id}: 同一逻辑决定存在多个当前生效修订：{ids}")

    for path, lines in contents.items():
        active_handoff: str | None = None
        in_scene = False
        scene_heading = ""
        scene_has_source = False
        in_pending_confirmation = False

        def close_scene() -> None:
            if in_scene and not scene_has_source:
                errors.append(f"{path}: {scene_heading} 缺少含当前 SRC-ID 的‘剧本来源’")

        for number, line in enumerate(lines, 1):
            if line.startswith("### "):
                close_scene()
                in_scene = bool(SCENE_RE.match(line))
                scene_heading = line.removeprefix("### ").strip()
                scene_has_source = False
            elif line.startswith("## "):
                close_scene()
                in_scene = False
                in_pending_confirmation = line.strip() == "## 待用户确认"
                active_handoff = line if line in HANDOFF_HEADINGS else None
            elif in_scene and line.strip().startswith("- 剧本来源："):
                refs = SRC_RE.findall(line)
                scene_has_source = bool(refs) and all(ref in sources for ref in refs)

            if in_pending_confirmation and line.strip().startswith("-"):
                value = line.split("：", 1)[1].strip() if "：" in line else line.lstrip("- ").strip()
                if value:
                    errors.append(f"{path}:{number}: 仍有实质‘待用户确认’，导演底稿不得发布")

            if active_handoff and meaningful_bullet(line):
                location = f"{path}:{number}"
                if "依据：" not in line:
                    errors.append(f"{location}: 交底缺少‘依据：SRC-ID/DIR-ID’")
                    continue
                source_refs = SRC_RE.findall(line)
                decision_refs = DIR_RE.findall(line)
                if not source_refs and not decision_refs:
                    errors.append(f"{location}: 交底至少引用一个当前 SRC-ID 或 DIR-ID")
                for ref in source_refs:
                    if ref not in sources:
                        errors.append(f"{location}: 交底引用了非当前来源 {ref}")
                for ref in decision_refs:
                    decision = decisions.get(ref)
                    if decision is None:
                        errors.append(f"{location}: 交底引用了未定义决定 {ref}")
                    elif decision.status not in ACTIVE:
                        errors.append(f"{location}: 交底引用了{decision.status}决定 {ref}")
        close_scene()

    approval = root / "approvals" / "director-approval.md"
    approved: dict[str, tuple[str, str]] = {}
    if approval.is_file():
        for number, line in enumerate(approval.read_text(encoding="utf-8").splitlines(), 1):
            row = table_cells(line)
            if not row or row[0] == "文件" or set(row[0]) == {"-"}:
                continue
            if len(row) != 9:
                if row[0].endswith(".md"):
                    errors.append(f"{approval}:{number}: 批准必须记录导演验收与最终权责批准")
                continue
            if not row[0].endswith(".md"):
                continue
            if row[3] != "accepted" or row[6] != "accepted":
                errors.append(f"{approval}:{number}: 导演验收和最终批准都必须为 accepted")
                continue
            if not row[4] or not row[7]:
                errors.append(f"{approval}:{number}: 两个批准角色都必须有具名签署人")
            if not valid_iso8601(row[5]) or not valid_iso8601(row[8]):
                errors.append(f"{approval}:{number}: 两个批准时间都必须是 ISO-8601")
            if not re.fullmatch(r"r\d+", row[1]):
                errors.append(f"{approval}:{number}: 非法 artifact_revision")
            if not HASH_RE.fullmatch(row[2]):
                errors.append(f"{approval}:{number}: 批准 SHA-256 无效")
            approved[row[0]] = (row[1], row[2])
    else:
        errors.append("缺少 approvals/director-approval.md")

    required = [
        Path("project-brief.md"),
        *(path.relative_to(root) for path in sorted((root / "episodes").glob("EP*.md"))),
    ]
    if (root / "pilot-brief.md").is_file():
        required.append(Path("pilot-brief.md"))
    if confirmation_file.is_file():
        required.append(Path("approvals/user-confirmations.md"))
    for relative in required:
        path = root / relative
        record = approved.get(str(relative))
        if not path.is_file():
            errors.append(f"导演批准目标不存在 {relative}")
        elif not record:
            errors.append(f"{relative}: 缺少双角色 accepted 批准")
        else:
            revision_match = re.search(r"^- artifact_revision：(r\d+)$", path.read_text(encoding="utf-8"), re.M)
            if not revision_match or revision_match.group(1) != record[0]:
                errors.append(f"{relative}: 批准 revision 与文件不匹配")
            if record[1].lower() != file_hash(path).lower():
                errors.append(f"{relative}: 批准哈希与文件不匹配")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"FAILED: {len(errors)} 项")
        return 1

    print(
        f"OK: {len(sources)} 个当前来源，{len(decisions)} 个导演决定，"
        "修订、交底与双角色批准有效"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
