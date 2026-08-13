# Seedance 美术资产模板

删除空节和说明。对外交接一律写 `project_id/ID@rN`。

## `visual-bible.md`

```markdown
# 视觉圣经

- project_id：
- artifact_revision：r1
- 上游：SRC-；DIR-@rN
- 制作范围：EP001—EP002
- 制作形态：
- 时代/地域/社会质感：
- 人物区分原则：
- 色彩/光线/材质：
- 竖屏构图原则：
- 必须避免：
- 状态：draft / ready / blocked / stale / accepted / deprecated
```

## `asset-index.md`

```markdown
# 资产索引

- project_id：
- artifact_revision：r1

## CHAR-001｜角色名

- revision：r1
- supersedes：无
- lifecycle_status：draft
- 来源：SRC-；DIR-@rN
- 剧情身份：
- 稳定视觉锚点：
- 区分对象：
- 不得泄露：
- 下游用途：
- 责任人：
- 影响范围：

## LOOK-001｜角色·状态

- revision：r1
- supersedes：无
- lifecycle_status：draft
- 父对象：CHAR-001@r1
- 来源：SRC-；DIR-@rN
- 使用场次：SCENE-EP001-001
- 只改变：

## LOC-001｜场景

- revision：r1
- supersedes：无
- lifecycle_status：draft
- 来源：SRC-；DIR-@rN
- 行动需求：
- 空间锚点：
- 必要视图：VIEW-001@r1

## VIEW-001｜场景视图

- revision：r1
- supersedes：无
- lifecycle_status：draft
- 父对象：LOC-001@r1
- 来源：SHOT- / 创意分镜需求
- 方向与覆盖区域：
- 下游用途：

## PROP-001｜道具

- revision：r1
- supersedes：无
- lifecycle_status：draft
- 来源：SRC-；DIR-
- 剧情功能：
- 识别锚点：
- 精确文字：无 / POST-REQUEST-ID 后期排字需求
- 状态与归属：

## STATE-001｜物理状态

- revision：r1
- supersedes：无
- lifecycle_status：draft
- 父对象：CHAR/LOOK/LOC/PROP@rN
- 来源：SRC-；SHOT-
- 可见变化：
- 生效场次：

## FRAME-EP001-001-S｜镜头首帧

- revision：r1
- supersedes：无
- lifecycle_status：draft
- 来源：SHOT-EP001-001@r1
- 资产绑定：
- 画面边界：
- 下游用途：GEN-EP001-001@r1
```

## `continuity.md`

```markdown
# 视觉连续性

| SCENE-ID | LOOK@rev | LOC/VIEW/STATE@rev | PROP归属/状态 | 传给下一场 |
|---|---|---|---|---|
| SCENE-EP001-001 | LOOK-001@r1 | LOC-001@r1；VIEW-001@r1 | PROP-001@r1：角色A持有 |  |
```

## `image-prompts.md`

```markdown
# 资产生图提示词

## PROMPT-CHAR-001-r1

- 目标：CHAR-001@r1
- 用途：身份主参考
- 提示词：
- 必须保持：
- 不得出现：
- lifecycle_status：ready
```

## `reference-manifest.md`

```markdown
# 生产参考清单

- project_id：
- artifact_revision：r1
- 核心视觉批准：approvals/visual-approval.md
- visual_bible_sha256：
- asset_index_sha256：
- continuity_sha256：
- capability_profile：seedance-video-prompts/capability-profile.md@r1
- capability_profile_sha256：

| REF-ASSET-ID | revision | 绑定对象 | 本地路径 | SHA-256 | 尺寸/格式 | 用途 | 权利状态 | 责任人 | 批准证据 | lifecycle_status |
|---|---|---|---|---|---|---|---|---|---|---|
| REF-ASSET-001 | r1 | CHAR-001@r1 | /绝对/稳定/path.png | 64位哈希 | 1024x1536/png | 锁定角色身份 | 已授权 | 美术负责人 | approvals/visual-approval.md#REF-ASSET-001 | accepted |
```

## `approvals/visual-approval.md`

```markdown
# 核心视觉批准

| 对象 | 绑定资产+规格/hash | 候选文件/hash | 美术验收 | 美术签署/时间 | 最终批准 | 权责批准人/时间 | 备注 |
|---|---|---|---|---|---|---|---|
| REF-ASSET-001@r1 | CHAR-001@r1 / asset-index.md / hash | path / hash | accepted | 姓名 / ISO-8601 | accepted | 姓名 / ISO-8601 | 主角脸 |
| 视觉规格包@r1 | visual-bible + asset-index + continuity / 三个hash | 无 | accepted | 姓名 / ISO-8601 | accepted | 姓名 / ISO-8601 | 锁定视觉规格 |
```
