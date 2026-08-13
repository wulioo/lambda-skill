#!/usr/bin/env python3
"""校验美术规格、当前资产、生产参考、权利和双角色批准。"""

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


HASH_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
REF_RE = re.compile(r"^REF-ASSET-[A-Z0-9-]+$")
ASSET_ID_RE = re.compile(r"^(CHAR|LOOK|LOC|VIEW|PROP|STATE|FRAME)-[A-Z0-9-]+$")
ASSET_REV_RE = re.compile(r"^(?:CHAR|LOOK|LOC|VIEW|PROP|STATE|FRAME)-[A-Z0-9-]+@r\d+$")
MEDIA_RE = re.compile(r"^(\d+)x(\d+)/(png|jpe?g|webp)$", re.I)
STATUSES = {"draft", "ready", "blocked", "stale", "accepted", "deprecated"}


def cells(line: str) -> list[str]:
    if not line.lstrip().startswith("|"):
        return []
    return [x.strip() for x in line.strip().strip("|").split("|")]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def valid_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "T" in value
    except ValueError:
        return False


def image_size(path: Path) -> tuple[int, int] | None:
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    manifest = root / "reference-manifest.md"
    errors: list[str] = []

    if not manifest.is_file():
        print(f"ERROR: 缺少 {manifest}")
        return 1
    manifest_text = manifest.read_text(encoding="utf-8")

    project_match = re.search(r"^- project_id：([a-z0-9][a-z0-9-]*)$", manifest_text, re.M)
    if not project_match:
        errors.append("reference-manifest.md 缺合法 project_id")

    profile_ref = re.search(r"^- capability_profile：(.+?)@(r\d+)$", manifest_text, re.M)
    profile_hash = re.search(r"^- capability_profile_sha256：([0-9a-fA-F]{64})$", manifest_text, re.M)
    if not profile_ref or not profile_hash:
        errors.append("reference-manifest.md 缺能力档案路径/revision/SHA-256")
    else:
        profile_path = root.parent / profile_ref.group(1)
        if not profile_path.is_file():
            errors.append(f"能力档案不存在 {profile_path}")
        else:
            profile_text = profile_path.read_text(encoding="utf-8")
            revision = re.search(r"^- profile_revision：(r\d+)$", profile_text, re.M)
            if not revision or revision.group(1) != profile_ref.group(2):
                errors.append("reference manifest 锁定的能力档案 revision 不匹配")
            if sha256(profile_path).lower() != profile_hash.group(1).lower():
                errors.append("reference manifest 锁定的能力档案 SHA-256 不匹配")
            if "- lifecycle_status：accepted" not in profile_text:
                errors.append("生产参考绑定的能力档案未 accepted")

    spec_files = {
        "visual_bible_sha256": root / "visual-bible.md",
        "asset_index_sha256": root / "asset-index.md",
        "continuity_sha256": root / "continuity.md",
    }
    spec_hashes: dict[str, str] = {}
    for field, path in spec_files.items():
        match = re.search(rf"^- {field}：([0-9a-fA-F]{{64}})$", manifest_text, re.M)
        if not path.is_file() or not match:
            errors.append(f"reference-manifest.md 缺 {path.name} 或其 SHA-256")
        elif sha256(path).lower() != match.group(1).lower():
            errors.append(f"reference-manifest.md 锁定的 {path.name} SHA-256 不匹配")
        else:
            spec_hashes[path.name] = match.group(1).lower()

    asset_index = root / "asset-index.md"
    assets_defined: dict[str, str] = {}
    by_logical: dict[str, list[tuple[str, str]]] = {}
    if asset_index.is_file():
        text = asset_index.read_text(encoding="utf-8")
        headings = list(re.finditer(r"^##\s+((?:CHAR|LOOK|LOC|VIEW|PROP|STATE|FRAME)-[A-Z0-9-]+)\b", text, re.M))
        for index, heading in enumerate(headings):
            line_number = text.count("\n", 0, heading.start()) + 1
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            section = text[heading.end():end]
            revision = re.search(r"^- revision：(r\d+)$", section, re.M)
            status = re.search(r"^- lifecycle_status：(\w+)$", section, re.M)
            supersedes = re.search(r"^- supersedes：(.+)$", section, re.M)
            owner = re.search(r"^- 责任人：(.+)$", section, re.M)
            impact = re.search(r"^- 影响范围：(.+)$", section, re.M)
            if not revision or not status:
                errors.append(f"{asset_index}:{line_number}: 资产缺 revision/status")
                continue
            full = f"{heading.group(1)}@{revision.group(1)}"
            if full in assets_defined:
                errors.append(f"{asset_index}:{line_number}: 资产版本重复 {full}")
            assets_defined[full] = status.group(1)
            by_logical.setdefault(heading.group(1), []).append((full, status.group(1)))
            if status.group(1) not in STATUSES:
                errors.append(f"{asset_index}:{line_number}: 非法 lifecycle_status")
            if not supersedes:
                errors.append(f"{asset_index}:{line_number}: 资产缺 supersedes")
            if not owner or not owner.group(1).strip() or not impact or not impact.group(1).strip():
                errors.append(f"{asset_index}:{line_number}: 资产缺责任人或影响范围")
        for logical, versions in by_logical.items():
            current = [full for full, status in versions if status == "accepted"]
            if len(current) > 1:
                errors.append(f"{logical}: 同一逻辑资产存在多个 accepted 修订：{current}")
    else:
        errors.append("缺少 asset-index.md")

    approval = root / "approvals" / "visual-approval.md"
    approved_refs: dict[str, tuple[str, str, str]] = {}
    specs_approved = False
    if not approval.is_file():
        errors.append("缺少 approvals/visual-approval.md")
    else:
        for number, line in enumerate(approval.read_text(encoding="utf-8").splitlines(), 1):
            row = cells(line)
            if len(row) != 8 or row[0] in {"对象", ""} or set(row[0]) == {"-"}:
                continue
            if row[3] != "accepted" or row[5] != "accepted":
                errors.append(f"{approval}:{number}: 美术验收与最终批准必须同时 accepted")
                continue
            owner_parts = [part.strip() for part in row[4].rsplit("/", 1)]
            authority_parts = [part.strip() for part in row[6].rsplit("/", 1)]
            if len(owner_parts) != 2 or not owner_parts[0] or not valid_iso8601(owner_parts[1]):
                errors.append(f"{approval}:{number}: 美术签署/时间无效")
            if len(authority_parts) != 2 or not authority_parts[0] or not valid_iso8601(authority_parts[1]):
                errors.append(f"{approval}:{number}: 权责批准人/时间无效")
            if re.fullmatch(r"视觉规格包@r\d+", row[0]):
                specs_approved = all(value in row[1].lower() for value in spec_hashes.values())
                if not specs_approved:
                    errors.append(f"{approval}:{number}: 视觉规格包未绑定全部当前规格 SHA-256")
            elif re.fullmatch(r"REF-ASSET-[A-Z0-9-]+@r\d+", row[0]):
                file_hashes = re.findall(r"[0-9a-fA-F]{64}", row[2])
                spec_values = re.findall(r"[0-9a-fA-F]{64}", row[1])
                bound_assets = re.findall(
                    r"(?:CHAR|LOOK|LOC|VIEW|PROP|STATE|FRAME)-[A-Z0-9-]+@r\d+",
                    row[1],
                )
                if len(file_hashes) != 1 or not spec_values or len(bound_assets) != 1:
                    errors.append(f"{approval}:{number}: REF 批准缺绑定资产、规格 hash 或文件 hash")
                else:
                    approved_refs[row[0]] = (
                        spec_values[0].lower(), file_hashes[0].lower(), bound_assets[0]
                    )
    if spec_hashes and not specs_approved:
        errors.append("当前视觉规格包未获双角色批准")

    seen: set[str] = set()
    accepted = 0
    accepted_by_logical: dict[str, str] = {}
    for number, line in enumerate(manifest_text.splitlines(), 1):
        row = cells(line)
        if len(row) != 11 or row[0] == "REF-ASSET-ID" or not REF_RE.fullmatch(row[0]):
            continue
        ref_id, revision, asset, local, recorded_hash, media, _use, rights, owner, approval_ref, status = row
        full_ref = f"{ref_id}@{revision}"
        location = f"{manifest}:{number}"
        if full_ref in seen:
            errors.append(f"{location}: 重复参考 {full_ref}")
        seen.add(full_ref)
        if not re.fullmatch(r"r\d+", revision):
            errors.append(f"{location}: 非法 revision")
        if not ASSET_REV_RE.fullmatch(asset):
            errors.append(f"{location}: 绑定对象必须带 @rN")
        elif asset not in assets_defined:
            errors.append(f"{location}: 绑定对象未在 asset-index 定义 {asset}")
        elif status == "accepted" and assets_defined[asset] != "accepted":
            errors.append(f"{location}: accepted 参考绑定的资产未 accepted {asset}")
        if status not in STATUSES:
            errors.append(f"{location}: 非法 lifecycle_status")
        if status != "accepted":
            continue
        accepted += 1
        if ref_id in accepted_by_logical:
            errors.append(
                f"{location}: 同一逻辑参考 {ref_id} 存在多个 accepted 修订："
                f"{accepted_by_logical[ref_id]}、{full_ref}"
            )
        else:
            accepted_by_logical[ref_id] = full_ref
        if not owner:
            errors.append(f"{location}: accepted 参考缺责任人")
        path = Path(local).expanduser()
        if not path.is_absolute() or not path.is_file():
            errors.append(f"{location}: accepted 参考缺绝对本地文件 {local}")
        elif not HASH_RE.fullmatch(recorded_hash):
            errors.append(f"{location}: accepted 参考缺64位 SHA-256")
        elif sha256(path).lower() != recorded_hash.lower():
            errors.append(f"{location}: 文件哈希不匹配 {local}")
        media_match = MEDIA_RE.fullmatch(media)
        actual_size = image_size(path) if path.is_file() else None
        if not media_match:
            errors.append(f"{location}: 尺寸/格式必须为 宽x高/png|jpg|jpeg|webp")
        elif actual_size is None:
            errors.append(f"{location}: 图片无法由 ffprobe 读取尺寸")
        else:
            declared = (int(media_match.group(1)), int(media_match.group(2)))
            if actual_size != declared:
                errors.append(f"{location}: 声明尺寸与文件尺寸不一致")
            suffix = path.suffix.lower().lstrip(".")
            declared_format = media_match.group(3).lower()
            if {suffix, declared_format} != {"jpg", "jpeg"} and suffix != declared_format:
                errors.append(f"{location}: 声明格式与文件后缀不一致")
        if rights not in {"已授权", "自有", "已核实公版"}:
            errors.append(f"{location}: accepted 参考权利状态不明确")
        if approval_ref.split("#", 1)[0] != "approvals/visual-approval.md":
            errors.append(f"{location}: 批准证据路径不正确")
        approved = approved_refs.get(full_ref)
        if not approved or approved[1] != recorded_hash.lower():
            errors.append(f"{location}: REF 批准未匹配 {full_ref}+文件hash")
        elif asset_index.name in spec_hashes and approved[0] != spec_hashes[asset_index.name]:
            errors.append(f"{location}: REF 批准未绑定当前 asset-index hash")
        elif approved[2] != asset:
            errors.append(f"{location}: REF 批准绑定 {approved[2]}，与 manifest 的 {asset} 不一致")

    if accepted == 0:
        errors.append("没有任何 accepted 生产参考；只能进入创意分镜")
    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"FAILED: {len(errors)} 项")
        return 1
    print(f"OK: {accepted} 个 accepted 参考，规格/绑定/文件/权利/双角色批准有效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
