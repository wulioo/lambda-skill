#!/usr/bin/env python3
"""校验生产分镜的上游计划、资产绑定、SHOT/GEN、animatic 与双角色批准。"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from datetime import datetime
from pathlib import Path


SHOT_RE = re.compile(r"SHOT-EP\d{3}-\d{3}@r\d+")
GEN_RE = re.compile(r"GEN-EP\d{3}-\d{3}(?:-\d+)?@r\d+")
REF_RE = re.compile(r"REF-ASSET-[A-Z0-9-]+@r\d+")
ASSET_RE = re.compile(r"(?:CHAR|LOOK|LOC|VIEW|PROP|STATE|FRAME)-[A-Z0-9-]+@r\d+")
POST_RE = re.compile(r"POST-EP\d{3}-\d{3}@r\d+")
HASH_RE = re.compile(r"^[0-9a-f]{64}$", re.I)
RANGE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*[—-]\s*(\d+(?:\.\d+)?)秒?$")


def cells(line: str) -> list[str]:
    if not line.lstrip().startswith("|"):
        return []
    return [x.strip() for x in line.strip().strip("|").split("|")]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def valid_iso8601(value: str) -> bool:
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return "T" in value
    except ValueError:
        return False


def section_end(text: str, start: int) -> int:
    candidates = [
        position for position in (text.find("\n### ", start + 4), text.find("\n## ", start + 4))
        if position >= 0
    ]
    return min(candidates) if candidates else len(text)


def resolve(project_root: Path, storyboard_root: Path, value: str) -> Path:
    clean = value.split("@r", 1)[0].strip()
    path = Path(clean).expanduser()
    if path.is_absolute():
        return path.resolve()
    local = storyboard_root / path
    return local.resolve() if local.exists() else (project_root / path).resolve()


def accepted_assets_and_refs(assets: Path) -> tuple[set[str], dict[str, str], str]:
    accepted_assets: set[str] = set()
    asset_index = assets / "asset-index.md"
    if asset_index.is_file():
        text = asset_index.read_text(encoding="utf-8")
        headings = list(re.finditer(r"^##\s+((?:CHAR|LOOK|LOC|VIEW|PROP|STATE|FRAME)-[A-Z0-9-]+)\b", text, re.M))
        for index, heading in enumerate(headings):
            end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
            section = text[heading.end():end]
            revision = re.search(r"^- revision：(r\d+)$", section, re.M)
            status = re.search(r"^- lifecycle_status：(\w+)$", section, re.M)
            if revision and status and status.group(1) == "accepted":
                accepted_assets.add(f"{heading.group(1)}@{revision.group(1)}")
    refs: dict[str, str] = {}
    project_id = ""
    manifest = assets / "reference-manifest.md"
    if manifest.is_file():
        text = manifest.read_text(encoding="utf-8")
        match = re.search(r"^- project_id：([a-z0-9][a-z0-9-]*)$", text, re.M)
        project_id = match.group(1) if match else ""
        for line in text.splitlines():
            row = cells(line)
            if len(row) == 11 and row[-1] == "accepted" and row[0].startswith("REF-ASSET-"):
                refs[f"{row[0]}@{row[1]}"] = row[2]
    return accepted_assets, refs, project_id


def require_dependency(
    text: str,
    field: str,
    revision_field: bool,
    project_root: Path,
    storyboard_root: Path,
    errors: list[str],
    source: Path,
) -> Path | None:
    pattern = rf"^- {re.escape(field)}：(.+?@r\d+)$" if revision_field else rf"^- {re.escape(field)}：(.+)$"
    path_match = re.search(pattern, text, re.M)
    hash_match = re.search(rf"^- {re.escape(field)}_sha256：([0-9a-fA-F]{{64}})$", text, re.M)
    if not path_match or not hash_match:
        errors.append(f"{source}: 缺 {field} 路径/revision/SHA-256")
        return None
    path = resolve(project_root, storyboard_root, path_match.group(1))
    if not path.is_file() or digest(path).lower() != hash_match.group(1).lower():
        errors.append(f"{source}: {field} 文件或 SHA-256 无效")
        return None
    content = path.read_text(encoding="utf-8")
    if "- lifecycle_status：accepted" not in content:
        errors.append(f"{source}: {field} 未 accepted")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("storyboard", type=Path)
    parser.add_argument("assets", type=Path)
    args = parser.parse_args()
    root = args.storyboard.resolve()
    assets = args.assets.resolve()
    project_root = root.parent
    errors: list[str] = []
    production = sorted((root / "episodes").glob("EP*-production.md"))
    if not production:
        errors.append("没有 production-frozen 分镜")

    valid_assets, ref_to_asset, asset_project_id = accepted_assets_and_refs(assets)
    if not ref_to_asset:
        errors.append("美术 reference manifest 没有 accepted 参考")

    approvals = root / "approvals" / "storyboard-approval.md"
    approval_rows: dict[str, str] = {}
    if approvals.is_file():
        for number, line in enumerate(approvals.read_text(encoding="utf-8").splitlines(), 1):
            row = cells(line)
            if len(row) != 9 or not row[0].startswith("EP"):
                continue
            if row[3] != "accepted" or row[5] != "accepted" or row[7] != "accepted":
                errors.append(f"{approvals}:{number}: 分镜、导演与最终批准必须全部 accepted")
                continue
            for field, label in ((row[4], "分镜签署"), (row[6], "导演签署"), (row[8], "权责批准")):
                parts = [part.strip() for part in field.rsplit("/", 1)]
                if len(parts) != 2 or not parts[0] or not valid_iso8601(parts[1]):
                    errors.append(f"{approvals}:{number}: {label}/时间无效")
            approval_rows[row[1]] = row[2]
    else:
        errors.append("缺少 approvals/storyboard-approval.md")

    animatic_approvals = root / "approvals" / "animatic-approval.md"
    approved_animatics: dict[str, str] = {}
    if animatic_approvals.is_file():
        for number, line in enumerate(animatic_approvals.read_text(encoding="utf-8").splitlines(), 1):
            row = cells(line)
            if len(row) != 7 or not row[0].startswith("EP"):
                continue
            if row[3] != "accepted" or row[5] != "accepted":
                errors.append(f"{animatic_approvals}:{number}: animatic 导演验收与最终批准必须同时 accepted")
                continue
            for field, label in ((row[4], "导演签署"), (row[6], "权责批准")):
                parts = [part.strip() for part in field.rsplit("/", 1)]
                if len(parts) != 2 or not parts[0] or not valid_iso8601(parts[1]):
                    errors.append(f"{animatic_approvals}:{number}: {label}/时间无效")
            approved_animatics[row[1]] = row[2]
    else:
        errors.append("缺少 approvals/animatic-approval.md")

    total_shots = 0
    total_gens = 0
    for path in production:
        text = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(root))
        project_match = re.search(r"^- project_id：([a-z0-9][a-z0-9-]*)$", text, re.M)
        if not project_match or project_match.group(1) != asset_project_id:
            errors.append(f"{path}: project_id 缺失或与美术不一致")
        if "- mode：production-frozen" not in text or "- lifecycle_status：accepted" not in text:
            errors.append(f"{path}: 未标记 production-frozen/accepted")
        for line_number, line in enumerate(text.splitlines(), 1):
            row = cells(line)
            if len(row) == 6 and row[0].startswith("BLOCK-") and row[4] not in {"resolved", "deprecated"}:
                errors.append(f"{path}:{line_number}: 仍有未解决阻断 {row[0]}")

        capability = require_dependency(text, "capability_profile", True, project_root, root, errors, path)
        sound = require_dependency(text, "sound_plan", True, project_root, root, errors, path)
        post_plan = require_dependency(text, "post_plan", True, project_root, root, errors, path)
        animatic = require_dependency(text, "animatic", True, project_root, root, errors, path)
        if capability:
            minimum_match = re.search(r"^- minimum_generation_seconds：(\d+(?:\.\d+)?)$", text, re.M)
            minimum = float(minimum_match.group(1)) if minimum_match else 0.0
        else:
            minimum = 0.0
        if minimum <= 0:
            errors.append(f"{path}: 缺有效 minimum_generation_seconds")
        animatic_text = animatic.read_text(encoding="utf-8") if animatic else ""
        if animatic:
            animatic_rel = str(animatic.relative_to(root))
            approved_hash = approved_animatics.get(animatic_rel)
            if not approved_hash or not HASH_RE.fullmatch(approved_hash):
                errors.append(f"{path}: animatic 缺导演与最终权责双重批准")
            elif approved_hash.lower() != digest(animatic).lower():
                errors.append(f"{path}: animatic 批准 SHA-256 与当前文件不匹配")
            creative_match = re.search(r"^- creative_storyboard：(.+\.md)$", animatic_text, re.M)
            creative_hash = re.search(r"^- creative_storyboard_sha256：([0-9a-fA-F]{64})$", animatic_text, re.M)
            if not creative_match or not creative_hash:
                errors.append(f"{path}: animatic 缺创意分镜路径/SHA-256")
            else:
                creative = resolve(project_root, root, creative_match.group(1))
                expected_creative = root / "episodes" / path.name.replace("-production", "-creative")
                if creative != expected_creative or not creative.is_file() or creative_hash.group(1).lower() != digest(creative).lower():
                    errors.append(f"{path}: animatic 未绑定当前本集创意分镜文件/SHA-256")
        if sound:
            sound_path = re.search(r"^- sound_plan：(.+\.md)$", animatic_text, re.M)
            sound_hash = re.search(r"^- sound_plan_sha256：([0-9a-fA-F]{64})$", animatic_text, re.M)
            resolved_sound = resolve(project_root, root, sound_path.group(1)) if sound_path else None
            if resolved_sound != sound or not sound_hash or sound_hash.group(1).lower() != digest(sound).lower():
                errors.append(f"{path}: animatic 未绑定当前 sound-plan 文件/SHA-256")
        if sound and "- 镜序/节奏/对白容纳：pass" not in animatic_text:
            errors.append(f"{path}: animatic 未通过镜序/节奏/对白容纳检查")

        post_ids = set(POST_RE.findall(post_plan.read_text(encoding="utf-8"))) if post_plan else set()
        recorded_hash = approval_rows.get(rel)
        if not recorded_hash or not HASH_RE.fullmatch(recorded_hash):
            errors.append(f"{path}: 缺双角色 accepted 批准哈希")
        elif recorded_hash.lower() != digest(path):
            errors.append(f"{path}: 批准哈希与生产文件不匹配")

        shots = re.findall(r"^###\s+(SHOT-EP\d{3}-\d{3}@r\d+)$", text, re.M)
        if len(shots) != len(set(shots)) or not shots:
            errors.append(f"{path}: SHOT 缺失或重复")
        shot_sections = set(shots)
        total_shots += len(shot_sections)
        shot_targets: dict[str, float] = {}
        shot_refs: dict[str, set[str]] = {}
        required_posts: dict[str, set[str]] = {}
        for shot in shot_sections:
            start = text.find(f"### {shot}")
            section = text[start:section_end(text, start)]
            if "- 来源：" not in section or not re.search(r"SRC-", section):
                errors.append(f"{path}: {shot} 缺 SRC 来源")
            declared_assets = set(ASSET_RE.findall(section))
            refs = set(REF_RE.findall(section))
            if not declared_assets:
                errors.append(f"{path}: {shot} 缺资产依赖")
            for asset in declared_assets - valid_assets:
                errors.append(f"{path}: {shot} 引用非 accepted 资产 {asset}")
            if not refs:
                errors.append(f"{path}: {shot} 缺生产参考")
            for ref in refs:
                binding = ref_to_asset.get(ref)
                if not binding:
                    errors.append(f"{path}: {shot} 引用非 accepted 参考 {ref}")
                elif binding not in declared_assets:
                    errors.append(f"{path}: {shot} 的 {ref} 实际绑定 {binding}，未出现在本镜资产声明")
            shot_refs[shot] = refs
            post_line = re.search(r"^- POST：(.+)$", section, re.M)
            posts = set(POST_RE.findall(post_line.group(1))) if post_line else set()
            if post_line and post_line.group(1).strip() != "无" and not posts:
                errors.append(f"{path}: {shot} POST 字段必须为‘无’或正式 POST-ID@rN")
            for post in posts - post_ids:
                errors.append(f"{path}: {shot} 引用 post-plan 未定义 POST {post}")
            required_posts[shot] = posts
            target_shot = re.search(r"^- 目标剪辑时长：(\d+(?:\.\d+)?)秒$", section, re.M)
            if not target_shot:
                errors.append(f"{path}: {shot} 缺目标剪辑时长")
            else:
                shot_targets[shot] = float(target_shot.group(1))

        target_match = re.search(r"^- target_episode_seconds：(\d+(?:\.\d+)?)$", text, re.M)
        tolerance_match = re.search(r"^- allowed_tolerance_seconds：(\d+(?:\.\d+)?)$", text, re.M)
        target = float(target_match.group(1)) if target_match else 0.0
        tolerance = float(tolerance_match.group(1)) if tolerance_match else -1.0
        if target <= 0 or tolerance < 0:
            errors.append(f"{path}: 缺单集目标时长/容差")

        mapped: list[str] = []
        gen_ids: set[str] = set()
        edit_total = 0.0
        shot_edit_totals = {shot: 0.0 for shot in shot_sections}
        for number, line in enumerate(text.splitlines(), 1):
            row = cells(line)
            if len(row) != 8 or not GEN_RE.fullmatch(row[0]):
                continue
            gen, shot, edit, material, trim, _frames, refs_text, status = row
            if gen in gen_ids:
                errors.append(f"{path}:{number}: GEN 重复 {gen}")
            gen_ids.add(gen)
            total_gens += 1
            if shot not in shot_sections:
                errors.append(f"{path}:{number}: GEN 引用未定义 SHOT {shot}")
            mapped.append(shot)
            gen_refs = set(REF_RE.findall(refs_text))
            if not gen_refs:
                errors.append(f"{path}:{number}: GEN 缺明确生产参考")
            elif shot in shot_refs and not gen_refs.issubset(shot_refs[shot]):
                errors.append(f"{path}:{number}: GEN 使用 SHOT 未声明参考")
            try:
                edit_s, material_s = float(edit), float(material)
                edit_total += edit_s
                if shot in shot_edit_totals:
                    shot_edit_totals[shot] += edit_s
                if edit_s <= 0 or material_s < max(edit_s, minimum) or material_s > 30:
                    errors.append(f"{path}:{number}: 请求/剪辑素材时长非法")
                trim_match = RANGE_RE.fullmatch(trim.strip())
                if not trim_match:
                    errors.append(f"{path}:{number}: trim 必须是明确秒数区间")
                else:
                    start_s, end_s = float(trim_match.group(1)), float(trim_match.group(2))
                    if start_s < 0 or end_s > material_s or end_s <= start_s or abs((end_s - start_s) - edit_s) > 1e-6:
                        errors.append(f"{path}:{number}: trim 与素材/目标时长不一致")
            except ValueError:
                errors.append(f"{path}:{number}: 时长必须为数字秒")
            if status != "accepted":
                errors.append(f"{path}:{number}: 生产 GEN 状态不是 accepted")
        for shot in shot_sections:
            if shot not in mapped:
                errors.append(f"{path}: {shot} 没有 GEN")
            elif shot in shot_targets and abs(shot_edit_totals[shot] - shot_targets[shot]) > 1e-6:
                errors.append(f"{path}: {shot} 的 GEN 剪辑时长合计不等于 SHOT 目标")
        if target > 0 and tolerance >= 0 and abs(edit_total - target) > tolerance:
            errors.append(f"{path}: SHOT总时长超出单集目标容差")

    if errors:
        for error in errors:
            print(f"ERROR: {error}")
        print(f"FAILED: {len(errors)} 项")
        return 1
    print(f"OK: {len(production)} 集、{total_shots} SHOT、{total_gens} GEN，资产绑定/计划/animatic/批准有效")
    return 0


if __name__ == "__main__":
    sys.exit(main())
