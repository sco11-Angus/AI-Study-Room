## ADDED Requirements

### Requirement: 打架检测使用 YOLO 人体框
打架检测的视觉侧 SHALL 使用 YOLO 人体检测框作为人员框来源，SHALL NOT 使用人脸检测框。人员框 SHALL 通过引擎共享上下文（`SharedContextProvider`）从 `IntrusionPlugin` 写入的结果复用，SHALL NOT 在打架检测器内重复加载 YOLO 模型（协作红线「人员框只算一次」）。

#### Scenario: 视觉分基于人体框计算
- **GIVEN** `IntrusionPlugin` 已把本帧 YOLO 人体框写入 `shared_ctx`
- **WHEN** `FightPlugin.detect()` 执行
- **THEN** `VisualConflict` 基于取回的人体框计算近距离聚集与高速运动分

#### Scenario: 无人体框时视觉分为零
- **GIVEN** 本帧 `shared_ctx` 中无人员框（画面无人或上游未写入）
- **WHEN** `FightPlugin.detect()` 执行
- **THEN** 视觉分为 0，不产生打架告警

### Requirement: RTMP 音轨管线端到端可用
系统 SHALL 从 RTMP/网络流解出音轨并投递给打架检测器音频侧。音轨管线 SHALL 为：`FfmpegAudioSource`（ffmpeg `-vn` 解码重采样为 16kHz 单声道 PCM）→ `AudioWindower`（聚合为 1s 分析窗口）→ `FightPlugin.feed_audio(chunk)`。系统 SHALL 对音频链路各关键环节输出可观测日志（ffmpeg 可用性、音频线程启停、feed_audio 是否持续收到有效 PCM）。

当 ffmpeg 不可用或流无音轨时，系统 SHALL 优雅降级（音频分为 0、不崩溃）并输出明确告警日志说明降级原因。

#### Scenario: 音轨正常解码并喂入检测器
- **GIVEN** RTMP 流含有效 AAC 音轨且本机 ffmpeg 可用
- **WHEN** 音频线程运行
- **THEN** `FightPlugin.feed_audio()` 持续收到 1s PCM 窗口
- **AND** 音频冲突分可为非零

#### Scenario: ffmpeg 缺失时优雅降级
- **GIVEN** 本机未安装 ffmpeg
- **WHEN** 音频线程尝试启动
- **THEN** 输出明确 WARNING 日志，音频管线跳过
- **AND** 视频链路不受影响，进程不崩溃

#### Scenario: 本地摄像头无音轨跳过
- **GIVEN** 摄像头来源为本地索引（int）而非网络流
- **WHEN** 音频线程逻辑执行
- **THEN** 直接跳过音轨处理，不报错

### Requirement: 声学与人脸情绪模块参与融合
系统 SHALL 同时启用声学情绪识别（SenseVoice，`EMOTION_ENABLED=true`）与人脸情绪闸门（HSEmotion，`EMOTION_ENABLE=true`）。声学情绪 SHALL 产出情绪风险分 `emo_risk` 参与三模态融合；人脸情绪 SHALL 产出闸门系数 `emo_gate ∈ [0,1]` 调制视觉分。任一情绪模型加载失败时系统 SHALL 降级（声学 `emo_risk=0`、人脸 `emo_gate=1.0` 放行）且不崩溃。

#### Scenario: 三模态融合
- **GIVEN** 声学情绪识别可用且 `emo_risk > 0`
- **WHEN** 融合计算执行
- **THEN** 融合分 = `w_vis·vis_g + w_aud·aud + w_emo·emo_risk`（权重归一化）

#### Scenario: 人脸情绪闸门压制误报
- **GIVEN** 人脸情绪闸门启用且画面无负面强情绪（`emo_gate → 0`）
- **WHEN** 视觉分被闸门调制
- **THEN** `vis' = vis·(floor + (1-floor)·emo_gate)`，视觉分被压制以滤除欢呼/嬉闹

#### Scenario: 情绪模型缺失时降级不崩
- **GIVEN** 声学或人脸情绪模型加载失败
- **WHEN** 打架检测运行
- **THEN** 对应情绪信号降级为中性（`emo_risk=0` / `emo_gate=1.0`）
- **AND** 打架检测仍能基于剩余模态运行

### Requirement: 音视频情绪三模态融合告警
系统 SHALL 在融合分超过阈值 `FIGHT_FUSE_THRESH`、且视觉分与音频分均非零（双模 AND）、且候选无间断持续 `>= FIGHT_DURATION` 时，触发 `fight` 类型告警。告警 SHALL 携带 `fuse`/`vis_score`/`aud_score`/`emo_gate` 分数；声学情绪风险可用时 SHALL 附带 `emo_risk` 与 `emotion` 标签。

#### Scenario: 三模态命中触发告警
- **GIVEN** 视觉分 > 0、音频分 > 0、融合分 > 阈值
- **WHEN** 候选状态无间断持续达到 `FIGHT_DURATION`
- **THEN** 产生 `AlarmEvent(type="fight")`，`extra` 含各模态分数

#### Scenario: 音频分为零不告警
- **GIVEN** 视觉分很高但音频分为 0（音轨断/无声）
- **WHEN** 融合判定执行
- **THEN** 双模 AND 不成立，不产生打架告警

#### Scenario: 持续时间不足不告警
- **GIVEN** 融合分瞬时超阈值但未持续 `FIGHT_DURATION`
- **WHEN** 候选中断
- **THEN** 不触发告警（防抖）

### Requirement: 打架告警前端展示
系统 SHALL 将打架告警经现有告警链路（`AlarmService → broadcast_alarm`）推送至前端，在告警面板与日志中以 `fight`（打架告警）类型展示。前端 SHALL 可展示告警的三模态分数（`fuse`/`vis_score`/`aud_score`/`emo_gate`）与情绪标签，使「视觉+音频+情绪」命中可解释。本需求 SHALL NOT 要求前端播放直播音频。

#### Scenario: 告警出现在告警面板
- **GIVEN** 后端触发一条 `fight` 告警
- **WHEN** 前端 WebSocket 收到告警广播
- **THEN** 告警面板显示「打架告警」类型条目

#### Scenario: 分数可解释展示
- **GIVEN** 一条打架告警携带三模态分数
- **WHEN** 用户查看该告警详情
- **THEN** 可看到 `fuse`/`vis_score`/`aud_score`/`emo_gate` 及情绪标签

#### Scenario: 日志可按类型筛选
- **GIVEN** 日志中存在打架告警记录
- **WHEN** 用户在日志页按「打架告警」类型筛选
- **THEN** 列出所有 `fight` 类型告警
