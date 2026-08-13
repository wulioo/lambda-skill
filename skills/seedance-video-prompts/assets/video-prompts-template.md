# Seedance 视频执行模板

## `capability-profile.md`

```markdown
# Seedance 能力档案

- project_id：
- profile_revision：r1
- platform：BytePlus ModelArk / platform-agnostic
- model：
- interface：API / 控制台
- verified_at：
- official_sources：
- ratio：9:16；首尾帧 adaptive
- generation_duration_seconds：4—30
- resolution：480p / 720p
- input_roles：reference_image / reference_video / reference_audio / first_frame / last_frame
- portrait_input_route：no-real-human-face / trusted-model-output / preset-avatar / authorized-real-person
- portrait_route_evidence：非 no-real-human-face 时必填平台来源/预设ID/授权通道证据
- generate_audio：true/false
- return_last_frame：true/false
- project_voice_strategy：原生音画 / 统一后配
- candidates_per_round：
- max_rounds：
- cost_limit：货币金额，不得当作提交次数
- archive_root：
- lifecycle_status：accepted
```

## `voice-manifest.md`

```markdown
# 声音清单

- project_id：

| VOICE-ID | revision | 角色 | 语言/口音/声音锚点 | 本地文件 | SHA-256 | 权利 | 批准证据 | lifecycle_status |
|---|---|---|---|---|---|---|---|---|
| VOICE-001 | r1 | 角色A |  | /path.wav | 64位哈希 | 已授权 |  | accepted |
```

`approvals/voice-approval.md` 在首次生成前冻结角色、文件与 SHA-256；不得引用粗剪批准。

```markdown
| VOICE-ID@revision | 角色 | 文件 | SHA-256 | 批准人 | 时间 | lifecycle_status |
|---|---|---|---|---|---|---|
| VOICE-001@r1 | 角色A | /path.wav | 64位哈希 | 姓名 | ISO-8601 | accepted |
```

## `sound-plan.md`

```markdown
# 声音与临时对白计划

- project_id：
- artifact_revision：r1
- strategy：原生音画 / 统一后配
- lifecycle_status：accepted

| SHOT/GEN | 说话角色 | 原文对白 | 临时实测秒 | 停顿/口型要求 | 执行通道 | VOICE@rev | 权利结论 |
|---|---|---|---:|---|---|---|---|
| SHOT-EP001-001@r1 | 角色A |  | 2.4 | 话后0.5秒 | 原生模型 / 后期ADR / 无对白 | VOICE-001@r1 | accepted |

- 导演表演适配：accepted；签署人/ISO-8601
- 视频技术与权利验收：accepted；签署人/ISO-8601
```

## `post-plan.md`

```markdown
# POST 生产计划

- project_id：
- artifact_revision：r1
- lifecycle_status：accepted

| POST-REQUEST-ID | POST-ID@revision | 来源事实 | 影响SHOT | 合成类型 | 底板需求 | 验收方法 | lifecycle_status |
|---|---|---|---|---|---|---|---|
| POST-REQUEST-EP001-001 | POST-EP001-001@r1 | SRC-：原文 | SHOT-EP001-001@r1 | 精确文字 | 无字底板 | OCR+时间码截图 | accepted |
```

## `motion-reference-manifest.md`（按需）

```markdown
# 动作参考清单

- project_id：

| MOTION-ID | revision | 用途 | 本地文件 | SHA-256 | 时长秒 | 权利 | 批准证据 | lifecycle_status |
|---|---|---|---|---|---|---:|---|---|---|
| MOTION-001 | r1 | 锁定一次转身动作，不继承人物外观 | /path.mp4 | 64位哈希 | 4 | 已授权 |  | accepted |
```

## `audio-assets-manifest.md`（使用ADR、音乐、SFX或母版混音时）

```markdown
# 后期声音资产清单

- project_id：

| AUDIO-ID@revision | 类型 | 集 | 本地文件 | SHA-256 | 时长秒 | 来源/许可 | 用途 | 批准证据 | lifecycle_status |
|---|---|---|---|---|---:|---|---|---|---|
| AUDIO-ADR-EP001-001@r1 | ADR | EP001 | /path.wav | 64位哈希 | 2.4 | 已授权 | GEN-EP001-001@r1对白 | approvals/audio-approval.md#AUDIO-ADR-EP001-001 | accepted |
| AUDIO-MIX-EP001@r1 | 母版混音 | EP001 | /path.wav | 64位哈希 | 60 | 自有 | CUT-EP001@r1完整混音 | approvals/audio-approval.md#AUDIO-MIX-EP001 | accepted |
```

## `episodes/EPxxx.md`

```markdown
# EPxxx Seedance 生成执行

- project_id：
- artifact_revision：r1
- storyboard：SHOT/GEN production revision + approval hash
- capability_profile：r1

## GEN-EPxxx-001@r1｜SHOT-EPxxx-001@r1

- lifecycle_status：ready
- 目标剪辑时长：3秒
- 请求素材时长：4秒
- 预期可用区间/trim：0.5—3.5秒
- 上游：SRC-；DIR-@rN；ASSET@rN；REF-ASSET@rN
- 生成模式：reference-to-video / first-frame / first-last-frame

### 参考上传顺序

| REF-ID | upload_type/order | 本地文件/hash | 提交URL/asset ID | 绑定对象 | 用途 | 不得影响 |
|---|---|---|---|---|---|---|
| REF-GEN-EPxxx-001-01 | Image 1 | /path / hash | https://... | REF-ASSET-001@r1 | 身份 | 不改变造型 |

### 可复制核心提示词

> @Image 1只锁定角色身份。起始……触发……人物依次……摄影机……{对白}……<音效>……最终停在……始终保持……不得……

### 请求预览

- 请求文件：requests/GEN-EPxxx-001-r1.json
- 请求文件 SHA-256：

```json
{
  "model": "dreamina-seedance-2-5-260628",
  "content": [],
  "generate_audio": true,
  "ratio": "9:16",
  "duration": 4,
  "resolution": "720p",
  "return_last_frame": true
}
```

### 验收

| 类别 | 标准 | 结果 | 失败时间码/证据 | 容差 |
|---|---|---|---|---|
| 剧情/信息 |  | pass/fail |  |  |
| 身份/资产 |  | pass/fail |  |  |
| 动作/表演 |  | pass/fail |  |  |
| 摄影/首尾 |  | pass/fail |  |  |
| 声音/技术 |  | pass/fail |  |  |

### 生成记录

| OUTPUT-ID | revision | task ID | input manifest SHA-256 | prompt rev | model | submitted_at | 临时URL | 本地文件 | SHA-256 | 媒体探针 | 可用区间 | lifecycle_status |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| OUTPUT-EPxxx-001 | r1 | cgt- |  | r1 |  |  |  | /path.mp4 |  | 4s/720x1280/24fps/audio | 0.5—3.5 | accepted |
```

## `post-tasks.md`

```markdown
# 后期任务

- project_id：

| POST-ID@revision | 来源事实 | SHOT/OUTPUT | 底板/素材 | 时间码/区域 | 精确文字/效果 | POST输出文件 | SHA-256 | 责任阶段 | 验收证据 | lifecycle_status |
|---|---|---|---|---|---|---|---|---|---|---|
| POST-EP001-001@r1 | SRC-：原文 | SHOT-@r1 / OUTPUT-@r1 |  |  | 逐字内容 | /path/post.mp4 | 64位哈希 | 视频后期 | 截图/时间码+OCR | accepted |
```

## `cuts/EPxxx.md`

```markdown
# EPxxx 粗剪清单

- project_id：
- CUT-ID：CUT-EPxxx@r1
- cut_plan：cuts/EPxxx-plan.json
- cut_plan_SHA-256：
- assembly_receipt：cuts/EPxxx-assembly-receipt.json
- assembly_receipt_SHA-256：
- storyboard_revision：
- voice_strategy：
- target_ratio/resolution：9:16 / 720x1280
- lifecycle_status：accepted

| 顺序 | SHOT | OUTPUT@rev/hash | 入点 | 出点 | POST | 声音/字幕 | 状态 |
|---:|---|---|---:|---:|---|---|---|
| 1 | SHOT- | OUTPUT-@r1 / hash | 0.5 | 3.5 | POST- |  | accepted |

- 粗剪本地文件：/path/EPxxx-rough-cut.mp4
- SHA-256：
- 总时长：
- 媒体探针：
- 时间线QC：pass
- 导演批准：approvals/rough-cut-approval.md
```

## `approvals/rough-cut-approval.md`

```markdown
# 两集粗剪批准

- project_id：
| CUT-ID | 文件 | SHA-256 | cut-plan SHA-256 | 视频技术验收 | 视频签署 | 视频时间 | 导演批准 | 导演/权责批准人 | 批准时间 | assembly-receipt SHA-256 |
|---|---|---|---|---|---|---|---|---|---|---|
| CUT-EP001@r1 | /path.mp4 | 64位哈希 | 64位哈希 | accepted | 姓名 | ISO-8601 | accepted | 姓名 | ISO-8601 | 64位哈希 |
```

## `approvals/production-authorization.md`

```markdown
# Seedance 付费提交授权

- project_submission_limit：项目全部 GEN 合计允许的最大付费提交次数
- cost_limit：货币金额上限，仅作人工费用批准
- candidates_per_round：单个 GEN 每轮候选上限
- max_rounds：单个 GEN 重试轮次上限

| 请求文件 | SHA-256 | model | 最大提交次数 | 批准人 | 时间 | lifecycle_status |
|---|---|---|---:|---|---|---|
| GEN-EP001-001-r1.json | 64位哈希 | dreamina-seedance-2-5-260628 | 1 | 用户 | ISO-8601 | accepted |
```
