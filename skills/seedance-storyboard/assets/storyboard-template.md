# Seedance 分镜模板

## `episodes/EPxxx-creative.md`

```markdown
# EPxxx 创意分镜

- project_id：
- mode：creative-draft
- artifact_revision：r1
- capability_profile：平台/版本或通用规格
- 上游：SRC-；DIR-
- lifecycle_status：ready

## 原文落实表

| 来源 | 必须落实内容 | SHOT | 状态/理由 |
|---|---|---|---|
| SRC-：SCENE-EPxxx-001 |  | SHOT-EPxxx-001@r1 | ready |

## SHOT-EPxxx-001@r1

- 任务：
- 主体/观众视角：
- 景别/机位/构图及理由：
- 调度/表演节拍：
- 摄影机：
- 对白/声音：
- 概念资产：ASSET@rN
- 首帧：
- 尾帧：
- 目标剪辑时长：3秒
- 来源：SRC-；DIR-@rN
```

## `asset-requests.md`

```markdown
# 创意分镜资产需求

| REQUEST-ID | 影响SHOT | 父资产 | 需求类型 | 现有资产不足 | 必须锁定的结果 | lifecycle_status |
|---|---|---|---|---|---|---|
| REQUEST-EP001-001 | SHOT-EP001-001@r1 | LOC-001@r1 | VIEW/FRAME |  |  | ready |
```

精确文字或屏幕合成先在创意分镜建立 `POST-REQUEST-ID`，写来源事实、影响 SHOT、底板需求和必须验收的结果；不得提前伪造 `POST-ID`。

## `animatics/EPxxx.md`

```markdown
# EPxxx 轻量 animatic

- project_id：
- artifact_revision：r1
- creative_storyboard：episodes/EPxxx-creative.md
- creative_storyboard_sha256：
- sound_plan：seedance-video-prompts/sound-plan.md
- sound_plan_sha256：
- 代表帧/时间线文件：/path / SHA-256
- 目标时长：
- 对白实测时长：
- 镜序/节奏/对白容纳：pass
- lifecycle_status：accepted
```

## `episodes/EPxxx-production.md`

```markdown
# EPxxx 生产分镜

- project_id：
- mode：production-frozen
- artifact_revision：r1
- capability_profile：seedance-video-prompts/capability-profile.md@r1
- capability_profile_sha256：
- sound_plan：seedance-video-prompts/sound-plan.md@r1
- sound_plan_sha256：
- post_plan：seedance-video-prompts/post-plan.md@r1
- post_plan_sha256：
- animatic：animatics/EPxxx.md@r1
- animatic_sha256：
- minimum_generation_seconds：4
- target_episode_seconds：60
- allowed_tolerance_seconds：10
- upstream_status：accepted
- lifecycle_status：accepted

## 生产镜头

### SHOT-EPxxx-001@r1

- 任务：
- 目标剪辑时长：3秒
- 构图/调度/表演/摄影机：
- 对白/声音：
- 首帧：
- 尾帧：
- 来源：SRC-；DIR-@rN
- 资产：CHAR-001@r1；LOOK-001@r1；LOC-001@r1
- 生产参考：REF-ASSET-001@r1；REF-ASSET-002@r1
- POST：无 / POST-EPxxx-001@r1
- 前后衔接：

## 生成单元

| GEN@revision | SHOT@revision | 本段目标剪辑秒 | 请求素材秒 | 预期可用区间/trim | 首尾帧参考 | 生产参考 | lifecycle_status |
|---|---|---:|---:|---|---|---|---|
| GEN-EPxxx-001@r1 | SHOT-EPxxx-001@r1 | 3 | 4 | 0.5—3.5秒 | FRAME-EPxxx-001-S@r1 | REF-ASSET-001@r1 | accepted |

## 连续性

- 轴线/视线/位置：
- 造型/状态/持物：
- 上一 accepted 尾帧串联：

## 阻断

| BLOCK-ID | 问题 | 影响ID | 唯一责任人 | lifecycle_status | 解锁证据 |
|---|---|---|---|---|---|
```

## `approvals/animatic-approval.md`

```markdown
# Animatic 批准

| 集 | animatic文件 | SHA-256 | 导演创作验收 | 导演签署/时间 | 最终批准 | 权责批准人/时间 |
|---|---|---|---|---|---|---|
| EP001 | animatics/EP001.md | 64位哈希 | accepted | 姓名 / ISO-8601 | accepted | 姓名 / ISO-8601 |
```

## `approvals/storyboard-approval.md`

```markdown
# 生产分镜批准

| 集 | 生产文件 | SHA-256 | 分镜技术验收 | 分镜签署/时间 | 导演创作验收 | 导演签署/时间 | 最终批准 | 权责批准人/时间 |
|---|---|---|---|---|---|---|---|---|
| EP001 | episodes/EP001-production.md | 64位哈希 | accepted | 姓名 / ISO-8601 | accepted | 姓名 / ISO-8601 | accepted | 姓名 / ISO-8601 |
```
