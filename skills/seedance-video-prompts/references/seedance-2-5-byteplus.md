# BytePlus ModelArk Seedance 2.5 能力快照

核实日期：2026-08-13。正式执行前若平台或文档已更新，重新核实。

官方来源：

- <https://docs.byteplus.com/en/docs/ModelArk/2607688>
- <https://docs.byteplus.com/en/docs/ModelArk/2607689>
- <https://docs.byteplus.com/en/docs/ModelArk/1520757>

## 生产约束

- 模型：`dreamina-seedance-2-5-260628`。
- 创建端点：`POST https://ark.ap-southeast.bytepluses.com/api/v3/contents/generations/tasks`。
- 支持 text、image、video、audio 多模态参考。
- 内容角色：`reference_image`、`reference_video`、`reference_audio`、`first_frame`、`last_frame`。
- 提示词按上传顺序显式引用 `@Image 1 / @Video 1 / @Audio 1`，并说明各素材提供什么、不得影响什么。
- 首帧/首尾帧模式：`ratio=adaptive`；输出比例跟随首帧；首尾帧须使用相同比例。
- reference-to-video 竖屏可设 `ratio=9:16`。
- 短剧 omni 参考生成显式设 `omni_reference_task_type=reference`，把任务判型提前；编辑/延长任务不得手改绕过独立适配。
- `duration`：`4—30` 秒或 `-1`；视频编辑只支持 `-1`，输入编辑视频须为 4—30 秒。
- 本 Skill 的请求编译器只处理短剧生成单元的 `4—30` 秒任务；`duration=-1` 的视频编辑任务需另建已核实的编辑适配器，不得手改绕过。
- `resolution`：`480p` 或 `720p`；9:16 对应 480×854 或 720×1280。
- `generate_audio` 控制同步人声、音效和音乐；默认 true。
- `return_last_frame=true` 可在查询结果中取得 PNG 尾帧。
- 输出格式：`mp4` 默认；专业后期/视频编辑可用 `mov`。
- 单次请求全部参考素材合计最多 50 个；其中图片最多 30 张，视频最多 10 段且合计不超过 30 秒，音频最多 10 段且合计不超过 30 秒。
- 图片可用公网 URL、Base64 或 asset ID；视频可用公网 URL或 asset ID；音频可用公网 URL、Base64 或 asset ID。
- 参考 URL 必须能被平台访问；不要把本地路径直接写进 API URL 字段。
- Seedance 2.5 不支持直接上传含真人脸的普通参考图/视频。生产必须明确选用“同账号可信模型原始输出 / 平台预设数字人 / 已授权真人资产机制”之一，并保留平台可接受形式和授权证据；普通 HTTPS 地址不等于可用。
- 任务记录保留 7 天；结果视频 URL 只保留 24 小时，最多下载 100 次。成功后立即本地归档。

## 提示词核心

- 顺序：主体 + 动作/事件 + 场景 + 必要风格 + 摄影/切镜 + 声音；无关项省略。
- `{}` 可标对白，`<>` 标音效，`()` 标音乐，`【】` 标字幕；精确字幕仍优先后期合成。
- 多参考时先绑定角色和素材，再写动作过程；素材已足够准确时不要重复长篇描述。
- 时间分配必须与动作容量相符；不要用时间戳控制高频微动作。
