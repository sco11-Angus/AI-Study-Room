## Why

任务书要求打架检测跑通全链路并在前端展示，但当前实现存在三处「代码在、链路断」的缺口，导致打架告警在真实运行时**几乎不可能触发**：

1. **人员框来源不稳定**：`run.py` 给 `FightPlugin` 装配的是 `SharedContextProvider`（读引擎共享上下文），而共享上下文只由 `IntrusionPlugin` 写入。但 `IntrusionPlugin.detect()` 在「本摄像头没有配置危险区/占座座位」时**直接 return**（`intrusion.py:299-300`），根本不会跑 YOLO 人体检测、也就不写 `shared_ctx`。结果：只有恰好配了防区的摄像头，打架才拿得到人体框；其余摄像头视觉分恒为 0。这既不满足「必须用 YOLO 身体检测而非人脸」，也让打架检测形同虚设。

2. **双模 AND 强依赖音轨**：`FusionDebouncer.update()` 的候选条件是 `fuse > thresh AND vis_g > 0 AND aud_score > 0`（`fight.py:269`）。`aud_score > 0` 是硬门槛——只要 RTMP 音轨没解出、ffmpeg 缺失、或音频线程没喂数据，`aud_score` 恒 0，视觉再准也永不告警。因此「音轨正常」不是加分项，而是打架告警成立的**前提**，必须端到端验证音频管线活着。

3. **情绪模块半开**：声学情绪 `EmotionRecognizer`（SenseVoice）默认开（`EMOTION_ENABLED=true`）走三模态融合；但人脸情绪闸门 `FacialEmotion`（HSEmotion）默认关（`EMOTION_ENABLE=false`），关闭时闸门恒放行 1.0，无法压制欢呼/嬉闹误报。

本次变更的目标：**把打架检测的全链路真正打通**——YOLO 人体框稳定供给、RTMP 音轨端到端可用、声学+人脸双情绪模块启用，并在前端可展示打架告警与关键分数。

## What Changes

- **人员框改为 YOLO 人体框无条件供给（方案B）**：修改 `IntrusionPlugin.detect()`，把「跑 YOLO 人体检测 + 写 `shared_ctx`」提前到区域/座位早退判断**之前**执行。即无论该摄像头是否配置防区，每个推理帧都跑一次 YOLOv8n 人体检测并写入共享上下文。`FightPlugin` 继续通过 `SharedContextProvider` 读取，守住协作红线「人员框只算一次」——全系统仅 `IntrusionPlugin` 一份 YOLO 人体推理，打架/入侵共用。人脸框（`FaceBoxProvider`）不再作为打架的人员框来源。

- **音轨端到端保障（理解A：内部音轨通）**：确保 RTMP 音轨经 `_audio_loop` → `FfmpegAudioSource`（ffmpeg `-vn` 解码重采样 16k 单声道 PCM）→ `AudioWindower`（1s 窗口）→ `FightPlugin.feed_audio()` 全程有效。补齐可观测性：音频线程启动、ffmpeg 可用性、每路 `feed_audio` 是否持续收到有效 PCM 都要有明确日志，便于验证「音轨正常」。ffmpeg 缺失时按现有设计优雅降级并显式告警（此时打架因 `aud_score=0` 不告警，属预期）。前端展示的是**打架告警 + 情绪/分数标签**，不要求浏览器播放直播声音。

- **情绪模块双开（声学 + 人脸）**：`.env` 中开启 `EMOTION_ENABLE=true`（人脸情绪闸门 HSEmotion）并保持 `EMOTION_ENABLED=true`（声学情绪 SenseVoice）。三模态融合 `w_vis·vis + w_aud·aud + w_emo·emo_risk` 正常工作，人脸负面情绪（愤怒/恐惧）闸门调制视觉分压制误报。模型缺失时按现有设计降级放行，不崩。

- **前端展示打架告警**：打架告警走现有 `AlarmService → broadcast_alarm` → `AlarmPanel.vue` / `LogViewer.vue`（`fight` 类型已存在）。补齐告警详情展示——把 `extra` 中的 `fuse`/`vis_score`/`aud_score`/`emo_gate`/`emotion` 关键分数在告警面板或日志详情中可见，让「视觉+音频+情绪三模态命中」在前端可解释。

- **全链路联调验证**：用仓库内 `打架测试视频.mp4` / `打架测试2.mp4` 推流到 RTMP，端到端验证：YOLO 人体框有产出 → 视觉分非零 → 音轨解码喂数 → 音频分非零 → 情绪分参与融合 → 触发 `fight` 告警 → 前端告警面板与日志可见。

## 明确不做（守住范围）

- ❌ 前端播放直播音频（flv.js/HLS http-flv）——本次按「内部音轨通即可」，不改 canvas 显示方案、不引入音频播放器。
- ❌ 新增独立人体检测插件（方案C）——本次复用 `IntrusionPlugin` 的 YOLO，不新建插件。
- ❌ 打架检测算法调参/重训——沿用现有 `VisualConflict` / `AudioConflict` / `FusionDebouncer` 逻辑与权重，仅打通链路。
- ❌ 修改推理引擎调度、线程模型——不违反「统一引擎、检测器禁止自建线程」（音频线程属 scheduler 既有设计，非本次新增）。

## Capabilities

### Modified Capabilities

- `intrusion-detect`: 人员框（YOLO 人体检测）改为无条件写入共享上下文，供打架检测复用；不改变入侵检测本身的告警行为。

### New Capabilities

- `fight-detect`: 音视频情绪三模态融合打架检测的全链路契约——YOLO 人体框供给、RTMP 音轨管线、声学+人脸情绪、融合告警与前端展示。

## Impact

| 影响面 | 说明 |
|--------|------|
| `backend/app/detectors/intrusion.py` | `detect()` 把 YOLO 人体检测 + `shared_ctx.set()` 提前到区域/座位早退之前，无条件执行 |
| `backend/app/detectors/fight.py` | 无需改逻辑；确认 `SharedContextProvider` 取框链路，补日志 |
| `backend/app/stream/scheduler.py` | 音频线程补充可观测性日志（ffmpeg 可用性、feed_audio 心跳） |
| `.env` | `EMOTION_ENABLE=true`（开人脸情绪闸门），确认 `EMOTION_ENABLED=true`、`YAMNET_ENABLED=true` |
| `backend/run.py` | 确认 `FightPlugin(person_provider=SharedContextProvider(engine.shared_ctx))` 装配不变 |
| `frontend/src/components/AlarmPanel.vue` | 打架告警展示三模态分数（fuse/vis/aud/emo） |
| `frontend/src/views/LogViewer.vue` | 打架告警日志详情展示关键分数与情绪标签 |
| 全链路验证 | 用 `打架测试视频.mp4` 推流联调，确认端到端触发与前端展示 |
