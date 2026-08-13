# Seedance 短剧导演输出模板

只复制需要的结构；删除空节、说明和占位符。同一判断只写一次。

## `project-brief.md`

```markdown
# 项目导演简报

- project_id：
- artifact_revision：r1
- 制作模式：前两集试播 / 后续单集 / 指定范围
- 深度拆解：
- 全局材料用途：

## 当前来源

本表只保留当前制作使用的剧本修订版；旧稿移出本表。

| SRC-ID | 绝对本地路径 | 版本 | SHA-256 | 覆盖范围（原子单元，顺序无关） |
|---|---|---|---|---|
| SRC-EP001-001 |  |  |  | EP001 |

## 可导演性诊断

- 结论：可进入导演拆解 / 可拆解但有导演风险 / 存在事实阻断
- 核心成立点：
- 高影响风险：最多 3 项

## 导演基线

- 故事承诺：
- 观众站位：
- 主角欲望与失败代价：
- 核心关系矛盾：
- 核心情绪体验：

## 导演原则

- 表演：
- 画面：
- 声音：
- 信息揭示：
- 视觉母题：没有则删除
- 必须避免：

## 项目导演决定

| DIR-ID@revision | supersedes | 决定 | 状态 | 来源 | 影响范围 | 替代/失效理由 |
|---|---|---|---|---|---|---|
| DIR-PROJ-001@r1 | 无 |  | 生效 | SRC-EP001-001：位置 | 美术/分镜/视频 |  |

## 事实阻断

| BLOCK-ID | 缺失事实 | 权威责任人 | 影响范围 | 状态 | 解锁证据 |
|---|---|---|---|---|---|
| BLOCK-EP001-001 |  | 用户/编剧 |  | 待解决 |  |
```

## `pilot-brief.md`

```markdown
# 前两集试播导演简报

- artifact_revision：r1

## 试播创作假设

- 两集要让观众尝到的核心体验：
- 预期观众在 EP002 结尾追问：
- 本试播不证明：市场喜好与续拍价值

## 承诺—回应—升级

- EP001进入核心矛盾：
- EP001故事承诺：
- EP001集尾观看需求：
- EP002回应：
- EP002升级：
- EP002集尾追看理由：

## 跨集桥

- EP001结束的人物状态：
- 观众正在等待：
- EP002如何接住：

## 批准门｜导演底稿

- lifecycle_status：ready / blocked / accepted
- 批准证据：approvals/director-approval.md
```

## `episodes/EPxxx.md`

```markdown
# EPxxx 导演底稿

- artifact_revision：r1

## 来源

- 剧本：SRC-EPxxx-xxx
- 覆盖场次：

## 本集任务

- 不可逆变化：
- 目标、阻力与策略变化：
- 关系/信息/主动权变化：
- 观众核心体验：
- 本集戏眼：
- 集尾力量：

## 观众体验路线

1.
2.
3.

## 关键信息关系

| 节点 | 人物知道/误解/隐瞒 | 观众知道 | 揭示边界 |
|---|---|---|---|
|  |  |  |  |

## 分场行动卡

### SCENE-EPxxx-001｜场景名

- 场景结果：
- 行动策略链：
- 交锋与潜台词：
- 表演节点：触发 → 可见反应
- 信息边界：
- 导演必保瞬间：
- 声音重点：
- Seedance 高风险与戏剧底线：
- 入场剧情状态：
- 离场剧情状态：
- 剧本来源：SRC-EPxxx-xxx：原文位置

## 剧情连续性

只记录戏剧状态；服装、持物、伤势和道具位置交美术资产 Skill。

- 知情与误解：
- 关系与情绪：
- 决定与未完成行动：
- 不得提前揭示：

## 给美术资产 Skill 的剧情约束

- 必须传达或不得泄露的剧情结果。｜依据：SRC-EPxxx-xxx；DIR-EPxxx-001@r1

## 给分镜脚本 Skill 的导演交底

- 观众必须看懂的行动、反应或揭示时点。｜依据：DIR-EPxxx-001@r1

## 本集导演决定

| DIR-ID@revision | supersedes | 决定 | 状态 | 来源 | 影响范围 | 替代/失效理由 |
|---|---|---|---|---|---|---|
| DIR-EPxxx-001@r1 | 无 |  | 生效 | SRC-EPxxx-xxx：位置 | 美术/分镜/视频 |  |

## 事实阻断

| BLOCK-ID | 缺失事实 | 权威责任人 | 影响范围 | 状态 | 解锁证据 |
|---|---|---|---|---|---|
| BLOCK-EPxxx-001 |  | 用户/编剧 |  | 待解决 |  |

## 待用户确认

- 当前理解：
- 对成片的影响：
- 推荐方向：
```

## `approvals/user-confirmations.md`

仅在用户确认关键事实或创作方向时创建。必须忠实保存原话。

```markdown
# 用户关键确认

- artifact_revision：r1

| CONF-ID | 类型 | 对应 BLOCK/DIR | 用户原话 | 生效结论 | 确认角色 | 时间 |
|---|---|---|---|---|---|---|
| CONF-EP001-001 | 事实 / 创作方向 | BLOCK-EP001-001；DIR-EP001-001@r1 |  |  | 最终权责人 | ISO-8601 |
```

## `reviews/*.md`

```markdown
# 导演回审｜目标

## 回审对象

- 类型：核心视觉 / 分镜或animatic / 两集粗剪
- 文件或媒体版本：
- 使用的来源/决定：SRC- / DIR-

## 结论

- 通过 / 定点修改后通过 / 退回

## 定点问题

| 依据 | 产物证据/时间码 | 对观众的影响 | 必须修到的结果 | 负责 Skill |
|---|---|---|---|---|
| DIR- |  |  |  | seedance-art-assets / seedance-storyboard / seedance-video-prompts |

## 签署

- 责任岗位验收：accepted / rejected；签署人；ISO-8601
- 最终权责批准：accepted / rejected；批准人；ISO-8601

> 只审导演忠实度，不替代责任 Skill 的技术终审。
```

## `approvals/director-approval.md`

```markdown
# 导演底稿批准

| 文件 | artifact_revision | SHA-256 | 导演验收 | 导演签署 | 导演时间 | 最终批准 | 权责批准人 | 批准时间 |
|---|---|---|---|---|---|---|---|---|
| project-brief.md | r1 | 64位哈希 | accepted | 导演姓名 | ISO-8601 | accepted | 用户/制片人姓名 | ISO-8601 |
| pilot-brief.md | r1 | 64位哈希 | accepted | 导演姓名 | ISO-8601 | accepted | 用户/制片人姓名 | ISO-8601 |
| episodes/EP001.md | r1 | 64位哈希 | accepted | 导演姓名 | ISO-8601 | accepted | 用户/制片人姓名 | ISO-8601 |
| approvals/user-confirmations.md | r1 | 64位哈希 | accepted | 导演姓名 | ISO-8601 | accepted | 用户/制片人姓名 | ISO-8601 |
```

没有关键确认时删除 `user-confirmations.md` 及其批准行。同一人兼任两个角色时也要分别签署。
