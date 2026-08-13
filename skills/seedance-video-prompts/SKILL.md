---
name: seedance-video-prompts
description: 面向已冻结 Seedance 生产分镜和真实参考资产的短剧生成执行，也可在美术与分镜前做 Seedance 技术预检。用户要求核实模型能力、编写镜头视频提示词、映射图片/视频/音频参考、编译可提交请求、生成和验收视频、定向重试、管理角色声音、精确文字与屏幕合成、组接粗剪、归档产物或提交导演回审时使用。只有环境和授权满足时实际调用接口；不改剧本、导演意图、资产设计和镜头边界。
---

# Seedance 视频生成执行

把冻结分镜编译成真实 Seedance 任务，再把生成结果推进到**可剪辑、可回审、可归档**的两集粗剪。

## 核心原则

- 忠于冻结镜头，不在提示词阶段重新导演。
- 提示词写时间中发生的动作、反应、摄影和声音，不复述参考图已锁定的长相。
- 一条 `GEN` 只执行一个明确镜头意图；参考少而准确。
- 每个参考按真实上传顺序编号并明确用途，禁止裸 `REF-001` 跨任务复用。
- 生成失败只改失败变量；上游错误退回上游，不用反复抽卡掩盖。
- 平台返回 URL 是临时下载地址，不是交付文件。

## 职责边界

### 负责

- 在美术和分镜前建立平台能力档案与制作技术约束；
- 把生产分镜编译为提示词、参考映射和真实请求参数；
- 管理图片、视频、音频参考的上传顺序、平台 URL/asset ID、有效期和请求映射；
- 在用户授权、费用范围和接口可用时提交、轮询、下载、归档、验收和定向重试；
- 冻结角色声音策略与音频参考，管理跨镜音色连续；
- 登记动作/运镜参考视频的文件、哈希、时长、权利和批准证据；
- 管理精确文字、手机屏幕、跟踪合成、字幕等 `POST-ID`；
- 组接 accepted 镜头，完成声音、字幕、粗剪和时间线 QC；
- 把两集粗剪交导演回审，并执行定点重剪、重生成或后期修复。

### 不负责

- 修改剧本、对白、导演解释和信息揭示；
- 改变 `SHOT` 任务、构图、切点和目标剪辑边界；
- 临时重设计角色、造型、场景和道具；
- 在没有接口、媒体或批准时声称已生成、已验收或已成片；
- 代替导演判断戏是否成立，或代替独立审查做全链终审。

## 生产契约

- 对外交接使用 `project_id/ID@rN`；所有产物记录 revision 和 SHA-256。
- 视频阶段每个当前 Markdown（含声音、POST、粗剪与批准）都必须写同一 `project_id`；请求 JSON 不加非 API 字段，由项目 `requests/` 路径、生成记录和 hash 绑定身份。
- 状态只用 `draft / ready / blocked / stale / submitted / accepted / deprecated`。
- `accepted` 必须有任务、输入、模型、产物和验收证据；不能只写主观结论。
- 同一缺口继承原 `BLOCK-ID`，并写唯一责任人和解锁证据。
- `GEN` 不改变 `SHOT`；目标剪辑时长与请求素材时长分别继承。
- 未完成的 `POST-ID` 或声音任务会阻断粗剪 accepted。

## 两种模式

### 技术预检模式

在正式美术和分镜前运行。读取用户平台、发布渠道、单集时长和制作形态，输出 `capability-profile.md`：模型/入口、输入类型、比例、生成时长、分辨率、声音、首尾帧、参考上限、合规、费用/候选/重试上限、交付规格。

平台未定时只能发布 `platform-agnostic` 档案；分镜只能做 creative-draft。

若目标为 BytePlus ModelArk Seedance 2.5，读取 [官方能力快照](references/seedance-2-5-byteplus.md)。文档版本或入口变化时重新用官方资料核实，不凭记忆沿用。

### 生成执行模式

只有以下输入满足才开始：

1. `capability-profile.md` 已核实；
2. `seedance-storyboard/episodes/EPxxx-production.md` 状态 accepted 且批准哈希有效；
3. 美术 `reference-manifest.md` 中所需参考均 accepted、文件和哈希有效；
4. 导演底稿的 `SRC/DIR` 仍有效；
5. 声音策略、音色权利、临时对白计时、候选数、重试上限和费用范围已确认。

缺任何一项，只输出 blocked 任务，不提交接口。

## 工作流

### 1. 冻结项目技术档案

明确：目标平台/模型、入口、9:16 或发布比例、分辨率、生成时长范围、首尾帧规则、声音策略、输出格式、内容合规、肖像/版权、候选数、重试上限、费用上限、稳定归档目录和粗剪交付规格。人像必须锁定 `no-real-human-face / trusted-model-output / preset-avatar / authorized-real-person` 其一及证据；不得把普通含真人脸 HTTPS 素材当作 Seedance 2.5 可直传参考。

实际付费提交前，用户必须明确授权费用范围，并在 `approvals/production-authorization.md` 按请求文件/hash/model 冻结每个 GEN 的最大提交次数及项目 `project_submission_limit`。货币 `cost_limit` 只是人工费用批准，不充当次数。默认建议每轮 2 个候选、最多 3 轮，仅供单个 GEN 计划；未确认不得自动付费执行。

### 2. 在生产分镜前冻结声音与 POST 计划

项目只选一种主策略：

- **原生音画**：`generate_audio=true`，为角色登记获批音频参考并验收跨镜音色、对白归属和口型；
- **统一后配**：生成画面时关闭或弃用原生人声，后期统一对白/ADR、环境声、音乐和混音。

`voice-manifest.md` 登记 `VOICE-ID@revision`、角色、语言/口音、声音锚点、参考文件、SHA-256、权利和生成前批准证据；平台 URL/asset ID 只进入 GEN 上传映射。没有 accepted 音色参考时，不承诺跨镜原生音色稳定；不得用粗剪批准倒签音色批准。

输出 accepted `sound-plan.md`：逐场对白角色、临时对白时长、停顿/口型要求、执行通道（原生模型/后期ADR/无对白）、角色到 `VOICE-ID` 的映射及权利结论。导演签表演适配，视频执行岗位签技术与权利。生产分镜必须绑定其文件/hash。后期ADR的 GEN 关闭 `generate_audio`，归档无声底板；ADR 与母版进入 `audio-assets-manifest.md`，不得假装模型已经说出。

读取创意分镜的 `POST-REQUEST-ID`，输出 `post-plan.md`，分配正式 `POST-ID`、事实来源、责任阶段、合成类型和验收方法。此时只规划，不假装已有 POST 输出；生产分镜再绑定正式 ID。

确需动作或运镜参考时，在 `motion-reference-manifest.md` 登记 `MOTION-ID@revision`、用途、文件、提交 URL/asset ID、SHA-256、时长、权利和批准状态；不用视频参考则不创建空清单。

### 3. 预检每个 GEN

检查一个空间/时间段、主体、动作顺序、表演转折、摄影运动、对白长度、首尾状态和前后衔接。发现动作过载、精细交接、复杂接触或镜头边界不成立时，退回分镜；不擅自拆 GEN。

### 4. 选择生成模式与参考

- 身份/环境最脆弱：reference image；
- 起始构图必须精确：first frame；
- 首尾状态都必须精确：first + last frame；
- 动作/运镜难以文字定义：reference video；
- 音色/节奏是核心：reference audio；
- 文本足够且参考会引入冲突：不用多余参考。

每个任务使用 `REF-GEN-EP001-001-01` 形式，记录上传序号、绑定对象、真实文件、SHA-256、提交 URL/asset ID、用途和不得影响项。图片绑定美术 `REF-ASSET@revision`，视频绑定 `MOTION-ID@revision`，音频绑定 `VOICE-ID@revision`；字段必须逐项匹配各自权威清单。提示词中的 `@Image 1 / @Video 1 / @Audio 1` 必须与请求 `content[]` 和参考上传表的顺序一一对应。

严格 `first_frame/last_frame` 与 omni `reference_image/video/audio` 互斥。选择严格首尾帧时，只提交帧图，身份、造型、场景和构图必须已烘进获批帧；需要额外图片/视频/音频参考时改用 omni，并把首尾构图作为提示词约束而非严格帧角色。

### 5. 写时间化核心提示词

按镜头需要压缩为：

1. 起始构图、姿态、视线和持物；
2. 触发动作/对白/声音；
3. 按先后发生的可见行动、停顿和反应；
4. 唯一主要摄影运动及终点；
5. 承担叙事作用的环境与声音；
6. 尾帧位置、表情、视线、持物和构图；
7. 2—5 项最可能破坏本镜的硬约束。

使用具体动词和先后关系。删除“电影感、极致、细腻、氛围拉满”等空词；不加入分镜没有的动作、台词、角色和转场。

### 6. 编译真实请求

输出完整请求预览，不只写自然语言参数。对 BytePlus Seedance 2.5：

- 使用已核实模型和 `content[]` 角色；
- first/last frame 模式设 `ratio=adaptive`，且两帧比例一致；
- reference-to-video 竖屏设 `ratio=9:16`；
- `duration` 使用 GEN 请求素材时长，必须符合平台范围；
- 需要声音时显式设置 `generate_audio`；
- 连续镜头需要尾帧串联时设置 `return_last_frame=true`；
- 图片/视频/音频 URL 必须可由平台访问，或使用平台支持的 asset ID/Base64 形式。

请求 manifest 记录上传序号并计算整体 SHA-256，作为生成输入身份。当前短剧生成编译器只允许白名单字段，omni 生成显式锁定 `omni_reference_task_type=reference`与 `output_format=mp4`；未冻结字段、编辑或延长语义必须退回新的技术适配，不得手改 JSON。

`requests/` 只保留当前生产 GEN 使用的请求。文件名必须由 `GEN-ID@revision` 唯一推导；旧 revision、孤儿请求和多个 GEN 共用同一请求都会阻断生产，避免误提交过期任务。

批量任务优先先写结构化 `request-specs.json`，再运行：

```bash
uv run python <skill-dir>/scripts/compile_requests.py request-specs.json requests/
```

编译器会校验 `@Image/@Video/@Audio` 顺序、角色字段、时长与首尾帧比例；失败时不得手工绕过。

### 7. 提交、轮询与立即归档

只有用户明确要求实际生成且接口/登录态、资产、授权和费用均满足时执行。记录 task ID、模型、输入 manifest hash、提示词 revision、参数、提交时间、状态和错误码。

API 执行必须把生成记录中冻结的请求 hash 传给脚本。正式生产只使用绑定项目根目录的一键流程；脚本会先强制运行四阶段付费前门禁，损坏的提交日志必须 fail-closed：

```bash
uv run python <skill-dir>/scripts/seedance_api.py run request.json output.mp4 \
  --expected-sha256 <冻结的64位SHA-256> \
  --project-root <项目根目录> \
  --authorization approvals/production-authorization.md \
  --submission-log approvals/submission-log.jsonl \
  --last-frame-output output-last-frame.png
```

`seedance_api.py` 禁止 `--allow-fixture`；测试素材只能进入编译器和机械门禁，绝不能触发正式 BytePlus 端点。请求顶层、`content[]` 与媒体容器都使用白名单；未冻结字段一律拒绝。

该命令原子预留授权次数，提交后轮询并立即归档。网络中断、超时或归档失败后不得重提；用日志中的 task ID 续收：

```bash
uv run python <skill-dir>/scripts/seedance_api.py collect <task-id> request.json output.mp4 \
  --expected-sha256 <冻结的64位SHA-256> \
  --submission-log approvals/submission-log.jsonl \
  --last-frame-output output-last-frame.png
```

若平台已受理、但进程在 task ID 写入本地日志前硬崩溃，立即冻结该 reservation 并人工从平台控制台/账单对账；在找回 task ID 或明确核销前禁止自动重提。当前公开接口资料未提供可依赖的幂等键或按客户端 token 恢复能力，不伪造自动恢复。

成功后自动：

1. 下载到稳定本地路径；
2. 计算 SHA-256；
3. 用媒体探针检查容器、时长、分辨率、帧率和音轨；
4. 下载并登记返回尾帧（若请求）；
5. 将临时 URL 与归档路径分开记录。

### 8. 镜头级验收

按顺序检查：剧情/信息 → 身份资产 → 动作表演 → 摄影与首尾 → 声音 → 技术质量。

每项记录 pass/fail、失败时间码、截图/帧证据、允许容差和结论。accepted 至少包含 task ID、输入 hash、模型版本、产物 hash、可用区间和 trim 点。

### 9. 定向重试

先分类：平台错误、身份、构图、动作、表演、运镜、声音、技术形变。平台错误不改提示词；内容错误每轮只改最少变量并保留已通过项。到达候选/轮次上限后，按责任退回导演、美术、分镜或平台适配，不无限抽卡。

精确文字错误不得靠反复生成解决，转 `POST-ID`。

### 10. 执行后期任务

为手机照片、聊天界面、欠条文字、招牌、字幕、遮罩和需要跟踪的合成建立 `POST-ID`：来源事实、镜头、底板/素材、时间码、区域、精确文字、跟踪/合成方法、责任阶段和逐字验收。

来源事实未确认时继承 `BLOCK-ID`。任何必需 POST 未 accepted，对应镜头和粗剪都不能 accepted。

### 11. 组接声音与两集粗剪

按 SHOT 顺序和 trim 点组接 accepted 版本；完成对白/ADR、环境声、音乐、字幕、音色连续、响度和混音。不得用转场掩盖错误镜头，也不得改变冻结剧情顺序。

先写 `cut-plan.json`，每项绑定生产分镜文件/hash、SHOT、accepted OUTPUT 原文件/hash、入点/出点及可选的 `POST-ID + POST输出文件/hash`。无需后期声音加工时可用 `audio_mode=native`；存在ADR、音乐、SFX、响度处理或统一后配时用 `audio_mode=master_mix`，并以 `mix_id` 绑定 `audio-assets-manifest.md` 中的整集混音文件/hash；`fixture_silence` 只允许机械测试。音乐、SFX、ADR 与母版混音均登记文件/hash/来源/许可/用途/批准/响度。再运行：

```bash
uv run python <skill-dir>/scripts/assemble_cut.py cut-plan.json rough-cut.mp4 \
  --receipt assembly-receipt.json
```

组接脚本只执行冻结时间线，不自行改镜头顺序或补转场；输出的 receipt 必须绑定当前 plan、每个 OUTPUT/POST、入出点及粗剪 hash，缺失或不匹配不能 accepted。

粗剪中 GEN 的顺序必须与生产分镜完全一致；同一 SHOT 的多个 GEN 必须连续并按分段顺序出现。任何换序都先退回分镜或取得新冻结版本，不能在剪辑层静默改故事。

输出 `CUT-EP001@r1`：时间线、每镜文件/hash/入出点、声音、POST、总时长、导出参数和粗剪文件 hash。母版混音必须明确列出所包含的全部 ADR ID，assembly receipt 必须锁定实际音源。逐集做剧情连续、黑帧、跳帧、重复帧、音画同步、字幕安全区和响度 QC。

### 12. 导演回审与定点修复

提交两集粗剪给 `$seedance-short-drama-director`。根据导演回审只执行被点名的：

- 剪辑可修：只能在 accepted handles 内换取舍，且保持 SHOT 时长、镜序、叙事切点和信息落点；
- 后期可修：完成跟踪/排字/遮罩；
- 视频需重生成：建立新 OUTPUT revision；
- 资产/分镜问题：退回对应 Skill，再使依赖版本 stale。

改变 SHOT 时长、镜序、叙事切点或信息落点，必须退回分镜建立新 revision。导演批准且技术 QC 全部通过后，粗剪才标 accepted。

## 输出

使用 [视频执行模板](assets/video-prompts-template.md)：

```text
seedance-video-prompts/
├── capability-profile.md
├── sound-plan.md
├── post-plan.md
├── voice-manifest.md
├── audio-assets-manifest.md      # 统一后配或使用音乐/SFX/ADR时
├── motion-reference-manifest.md # 按需
├── requests/GEN-EP001-001-r1.json
├── episodes/EP001.md
├── episodes/EP002.md
├── post-tasks.md
├── cuts/EP001-plan.json
├── cuts/EP001-assembly-receipt.json
├── cuts/EP001.md
├── cuts/EP002.md
└── approvals/
    ├── voice-approval.md
    ├── audio-approval.md          # 使用ADR、音乐、SFX或母版混音时
    ├── motion-approval.md         # 使用动作/运镜参考时
    ├── production-authorization.md
    ├── submission-log.jsonl
    └── rough-cut-approval.md
```

发布前运行：

```bash
uv run python <skill-dir>/scripts/video_guard.py \
  <项目内seedance-video-prompts目录> \
  <项目内seedance-storyboard目录> \
  <项目内seedance-art-assets目录>
```

四阶段最终交付再运行：

```bash
uv run python <skill-dir>/scripts/pipeline_guard.py <项目根目录>
```

## 完成标准

- capability profile 在美术/分镜前提供真实平台约束；
- 每个 production GEN 有且只有一个任务，参考顺序与提示词编号一致；
- 首尾帧有真实获批图片、相同比例且请求使用 `adaptive`；
- 提示词短、准，以起始—触发—过程—结束为灵魂；
- 请求参数来自当前官方能力，剪辑时长和生成时长未混写；
- 成功结果立即本地归档并有 hash/媒体探针记录；
- accepted 镜头有逐项验收证据和可用 trim 区间；
- 声音、精确文字和其他 POST 任务有负责人并完成验收；
- 两集粗剪通过导演回审与技术 QC，形成稳定本地交付。
