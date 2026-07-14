## Context

打架检测（`FightPlugin`）是音视频情绪三模态融合检测器：视觉冲突分（近距离聚集 + 高速肢体运动）+ 音频冲突分（YAMNet 语义 / DSP 兜底）+ 声学情绪风险分（SenseVoice），再叠加人脸情绪闸门（HSEmotion）压制误报。所有子模块代码均已存在，但真实运行时链路有三处断点（见 proposal「Why」）。本设计聚焦「如何打通」而非「重写算法」。

### 现有链路（含断点）

```
RTMP /live/<name> (视频 + AAC 音轨)
   │
   ├─视频─▶ StreamScheduler(cv2 拉流,跳帧 SKIP_N) ─▶ Frame
   │                                                   │
   │                                    InferenceEngine.dispatch_async
   │                                                   │
   │        ┌──────────────────────────────────────────┤
   │        ▼                                            ▼
   │   IntrusionPlugin.detect()                    FightPlugin.detect()
   │   ├ 若无 region/seat → return ✗ (断点1)        ├ boxes = shared_ctx 读 (可能空)
   │   └ 否则 YOLO人体 → shared_ctx.set()           ├ vis = VisualConflict(boxes)
   │                                                 ├ aud = 最近 feed_audio 的分 (可能0,断点2)
   │                                                 ├ emo_gate = FacialEmotion (默认关,断点3)
   │                                                 └ Fusion: vis>0 AND aud>0 AND fuse>阈值
   │
   └─音频─▶ _audio_loop(每路线程) ─▶ FfmpegAudioSource(-vn,16k PCM)
                                     ─▶ AudioWindower(1s) ─▶ fight.feed_audio(chunk)
```

## Goals / Non-Goals

**Goals**
- 打架检测稳定使用 YOLO 人体框（非人脸），且全系统只算一份人体推理。
- RTMP 音轨端到端有效，音频分能非零参与融合；链路各环节可观测。
- 声学 + 人脸情绪模块均启用并参与三模态融合。
- 打架告警在前端可见，且三模态分数可解释。

**Non-Goals**
- 不重写/调参检测算法。
- 不让前端播放直播音频。
- 不新增独立人体检测插件、不改推理引擎线程模型。

## Decisions

### 决策1：YOLO 人体框——共享上下文无条件写（方案B）

**问题**：`IntrusionPlugin.detect()` 在无 region/seat 时早退，导致 `shared_ctx` 不被写入，`FightPlugin` 拿不到框。

**选项对比**：

| 方案 | 做法 | 算力 | 合规（人员框只算一次） | 改动 |
|------|------|:---:|:---:|:---:|
| A | FightPlugin 用 `YoloPersonProvider` 自加载 yolov8n | 双份 YOLO ✗ | 违反 ✗ | 小 |
| **B** | **IntrusionPlugin 无条件跑 YOLO 写 shared_ctx** | **一份 YOLO ✓** | **守住 ✓** | **小** |
| C | 新建独立 PersonDetector 插件供全体读 | 一份 YOLO ✓ | 守住 ✓ | 大 |

**选择 B**。改法：把 YOLO 人体检测 + `shared_ctx.set()` 从 `intrusion.py:302-310` 提到区域/座位早退判断（`:297-300`）**之前**，无条件执行；早退逻辑保留在计数/告警部分。

**权衡**：原本「无防区不跑 YOLO」是省算力设计。方案B 让每个推理帧都跑一次人体检测。但：
- 推理已按 `SKIP_N` 跳帧，且引擎有背压丢帧（`dispatch_async` 队列 > 2 丢弃），可控。
- 人体检测本就是入侵检测的核心开销，打架复用零额外模型加载。
- 若后续算力吃紧，可用 `camera_ids` 白名单把 YOLO 限定到需要打架/入侵的路（与 StreetDetector 同套路），本次不做。

### 决策2：音轨是打架告警的前提，不是加分项

**关键认知**：`FusionDebouncer` 的 `aud_score > 0` 是硬 AND 条件。音轨链路断 = 打架永不告警。因此音轨验证不是可选项。

**不改融合逻辑**（双模 AND 是降误报的核心设计），而是**保障 + 可观测**音频链路：
- `_audio_loop` 启动时日志：ffmpeg 是否可用、是否为网络流、feed 目标检测器。
- `feed_audio` 增加周期性心跳日志（如每 N 个 chunk 记一次 `aud_score`），验证「音轨正常」。
- ffmpeg 缺失是常见坑（Windows 开发机）：显式 WARNING，并在联调文档中列为前置检查项。

**降级语义**：ffmpeg 缺失/音轨不存在时，`aud_score` 恒 0，打架不告警——这是**预期行为**（宁可不报，不误报），但必须让运维知道「为什么没报」。

### 决策3：情绪双开，融合权重不变

- `EMOTION_ENABLED=true`（声学 SenseVoice）：产出 `emo_risk`，`emo_risk > 0` 时启用三模态，权重 `w_vis=0.5, w_aud=0.3, w_emo=0.2`。
- `EMOTION_ENABLE=true`（人脸 HSEmotion）：产出 `emo_gate ∈ [0,1]`，调制视觉分 `vis' = vis·(floor + (1-floor)·emo_gate)`，`floor=0.4`。无负面情绪时把视觉分打折压制欢呼误报。
- 两套模型任一加载失败 → 按现有降级：声学 `emo_risk=0` 归一到双模；人脸 `emo_gate=1.0` 全放行。**不崩**。

### 决策4：前端展示——复用告警链路 + 补分数可解释性

- 打架告警 `AlarmEvent(type="fight")` 经 `AlarmService.raise_alarm` → `broadcast_alarm` → `AlarmPanel.vue`。`fight` 类型标签前端已有。
- 增强：`extra` 已带 `fuse/vis_score/aud_score/emo_gate/emotion`，在告警面板/日志详情中展示这些分数，让「三模态命中」可解释、可演示。
- 前端不播放音频（决策符合「理解A」）。

## Risks / Trade-offs

| 风险 | 影响 | 缓解 |
|------|------|------|
| 方案B 每帧跑 YOLO 增加算力 | 推理池压力↑ | 已有 SKIP_N + 背压丢帧；必要时用 camera_ids 限路 |
| ffmpeg 未安装 | 打架永不告警且易误判为「功能坏了」 | 显式日志 + 联调前置检查清单 |
| RTMP 推流无音轨（如视频文件无音频） | 同上 | 联调用带音轨的测试视频；日志暴露 aud_score |
| 人脸情绪模型缺失 | 闸门不生效（放行） | 降级放行不崩；缺模型时等价于只用声学+视觉双模 |
| 音视频时间对齐 | `FIGHT_ALIGN_TOL=2s` 容差外音频视为 0 | 保持现有容差；联调观察对齐日志 |

## Migration Plan

1. 改 `intrusion.py`：YOLO + shared_ctx 提前无条件执行。
2. 改 `.env`：`EMOTION_ENABLE=true`。
3. 补 scheduler / fight 可观测日志。
4. 前端告警面板/日志补分数展示。
5. 推流联调 → 验证端到端触发 → 前端确认。

无数据库 schema 变更，无破坏性操作，可随时回退（改动集中且独立）。

## Open Questions

- 是否需要把打架的 `person_boxes` 也推到前端画框展示（类似 face_boxes）？本次先只展示告警+分数，画框可作后续增强。
