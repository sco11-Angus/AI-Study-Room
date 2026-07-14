# 异常声学事件检测与音视频联动分析 Spec

## Why
当前系统的打架检测（FightPlugin）在音频侧仅使用经典 DSP 特征（能量、过零率、谱质心），无法区分"尖叫"与"大声说话"、"打斗声"与"关门声"，容易漏报/误报。代码中已明确标注 TODO："语义增强（YAMNet/小CNN 识别 尖叫/glass break）留作加分"。同时系统完全不具备情感识别能力，无法将"愤怒情绪"与"危险区域布防"联动做预判。本次变更旨在填补这些空白，引入可即下即用的开源深度学习模型，增强音频事件语义理解能力和情感-布防联动分析能力。

## What Changes
- 新增 **AudioEventDetector**：基于 YAMNet 的深度语义声学事件检测器，替代现有 DSP-only 的 AudioConflict 评分
- 新增 **EmotionRecognizer**：基于 SenseVoiceSmall 的情感识别器，输出 ANGRY/SAD/HAPPY 等情绪标签
- 增强 **FusionDebouncer**：三模态融合（视频打架分 + 音频语义事件分 + 情绪风险分），替代现有(0.6*vis + 0.4*aud)的简单加权
- 新增 **ZoneEmotionRisk 联动**：当识别到 ANGRY 情绪的人进入 danger_zone 区域时，自动提升该区域的报警灵敏度
- 保留原有 DSP 特征作为 fallback 路径（模型加载失败或推理超时时降级）
- 新增 `abnormal_sound` 告警类型（独立于 fight 的声学事件告警，如尖叫/呼救但无视觉打架证据时触发）

## Impact
- Affected specs: fight-detection (D2/D3/D4/D5), alarm-center (Task E)
- Affected code:
  - `backend/app/detectors/fight.py` — AudioConflict 重构，FusionDebouncer 升级
  - `backend/app/detectors/audio_event.py` — 新增，YAMNet 声学事件检测
  - `backend/app/detectors/emotion.py` — 新增，SenseVoiceSmall 情感识别
  - `backend/app/detectors/zone_emotion.py` — 新增，区域-情绪联动
  - `backend/app/config.py` — 新增配置项
  - `backend/app/models/entities.py` — 新增 abnormal_sound 告警类型
  - `backend/app/services/alarm.py` — 新增 abnormal_sound 告警处理
  - `backend/run.py` — 注册新检测器
  - `backend/requirements.txt` — 新增依赖
  - `init.sql` — 新增 alarm_type

## ADDED Requirements

### Requirement: YAMNet 声学事件检测
系统 SHALL 使用 YAMNet 模型对实时音频流进行语义级声学事件分类，识别与异常行为相关的声音类别。

#### Scenario: 检测到尖叫声
- **GIVEN** 系统正在处理来自摄像头麦克风的实时音频流
- **WHEN** 音频中出现 >0.96s 的尖叫声且 YAMNet 置信度 > 0.3
- **THEN** AudioEventDetector 输出 `audio_event="Scream"` 且 `audio_confidence >= 0.3`

#### Scenario: 检测到呼救/哭泣声
- **GIVEN** 系统正在处理实时音频流
- **WHEN** 音频中出现哭泣/呜咽声且 YAMNet 置信度 > 0.3
- **THEN** AudioEventDetector 输出 `audio_event="Crying"` 且标记为潜在呼救事件

#### Scenario: 检测到玻璃破碎声
- **GIVEN** 系统正在处理实时音频流
- **WHEN** 音频中出现玻璃破碎类声音
- **THEN** AudioEventDetector 输出 `audio_event="Glass"` 且触发环境破坏告警

#### Scenario: 无异常声音
- **GIVEN** 系统正在处理实时音频流
- **WHEN** 音频中仅包含正常交谈、环境噪声等
- **THEN** AudioEventDetector 不输出任何异常事件

#### Scenario: YAMNet 模型加载失败时降级
- **GIVEN** YAMNet 模型权重缺失或加载失败
- **WHEN** 系统调用 AudioEventDetector
- **THEN** 系统 SHALL 降级到现有 DSP 特征（RMS/ZCR/谱质心）作为 fallback，不中断检测流程

### Requirement: SenseVoiceSmall 情感识别
系统 SHALL 使用 SenseVoiceSmall 模型识别音频中说话人的情感状态（愤怒/悲伤/快乐/中性）。

#### Scenario: 识别到愤怒情绪
- **GIVEN** 系统正在处理包含语音的音频片段
- **WHEN** SenseVoiceSmall 分类结果为 ANGRY 且置信度 > 0.5
- **THEN** EmotionRecognizer 输出 `emotion="ANGRY"` 且 `emotion_confidence >= 0.5`

#### Scenario: 识别到哭泣/悲伤情绪
- **GIVEN** 系统正在处理包含语音的音频片段
- **WHEN** SenseVoiceSmall 检测到 CRY 事件或 SAD 情绪
- **THEN** EmotionRecognizer 输出 `emotion="SAD"` 或 `audio_event="CRY"`

#### Scenario: 正常交谈无异常情绪
- **GIVEN** 系统正在处理包含正常交谈的音频
- **WHEN** SenseVoiceSmall 分类为 HAPPY/NEUTRAL
- **THEN** EmotionRecognizer 不触发异常标记

#### Scenario: SenseVoiceSmall 模型不可用时降级
- **GIVEN** SenseVoiceSmall 模型权重缺失或加载失败
- **WHEN** 系统调用 EmotionRecognizer
- **THEN** 系统 SHALL 跳过情感识别，仅依靠 YAMNet + DSP fallback 进行声学检测

### Requirement: 三模态融合升级
系统 SHALL 将原有的(0.6*vis + 0.4*aud)双模融合升级为三模态加权融合：视频打架分 + 音频语义事件分 + 情绪风险分。

#### Scenario: 三模态同时触发确认暴力事件
- **GIVEN** 视频检测到近距离高速运动(vis > 0.5)，音频检测到尖叫声(audio_event="Scream")，情感识别为 ANGRY
- **WHEN** 三模态信号持续 >= FIGHT_DURATION(3s)
- **THEN** FusionDebouncer 输出 `fuse >= FUSE_THRESH`，触发 fight 告警（高置信度）

#### Scenario: 仅有音频尖叫但无视觉异常
- **GIVEN** 音频检测到尖叫声但视频侧无打架迹象(vis ≈ 0)
- **WHEN** 音频事件持续 >= ABNORMAL_SOUND_DURATION(2s)
- **THEN** 触发 `abnormal_sound` 告警（level=1），不触发 fight 告警

#### Scenario: 仅有愤怒情绪但无声学/视觉异常
- **GIVEN** 识别到 ANGRY 情绪但无声学尖叫和视觉打架
- **WHEN** 该情绪被持续检测到
- **THEN** 不触发独立告警，但将情绪风险分传递给 ZoneEmotionRisk 联动模块

#### Scenario: YAMNet 不可用时的双模降级
- **GIVEN** YAMNet 模型不可用（已降级到 DSP fallback）
- **WHEN** 融合模块评估
- **THEN** 系统 SHALL 保持原有(0.6*vis + 0.4*aud_DSP)的双模融合逻辑作为降级路径

### Requirement: ZoneEmotionRisk 区域-情绪联动
系统 SHALL 将情感识别结果与危险区域布防联动：当检测到 ANGRY 情绪的人员进入危险区域时，提升该区域的报警灵敏度。

#### Scenario: 愤怒者进入危险区域
- **GIVEN** EmotionRecognizer 检测到 ANGRY 情绪，且该人员被 FaceDetector 识别/追踪
- **WHEN** 该人员的位置框进入 danger_zone 多边形区域
- **THEN** 系统 SHALL 将该区域的入侵告警阈值临时降低 20%（更敏感），标记 `extra.zone_emotion_risk=true`

#### Scenario: 愤怒者离开后恢复
- **GIVEN** 某危险区域因愤怒者进入而被降低告警阈值
- **WHEN** 该人员离开区域或情绪恢复正常(NEUTRAL/HAPPY)
- **THEN** 区域告警阈值 SHALL 在 EMOTION_RISK_COOLDOWN(10s) 后恢复默认值

#### Scenario: 无情绪识别时的正常布防
- **GIVEN** EmotionRecognizer 未启用或未检测到任何情绪
- **WHEN** 系统进行入侵检测
- **THEN** 区域告警阈值 SHALL 使用默认值，不引入情绪因子

#### Scenario: 陌生人且无情绪数据的保守策略
- **GIVEN** 进入危险区域的人员是陌生人(stranger)，且无情绪数据
- **WHEN** 系统评估风险
- **THEN** 系统 SHALL 使用默认告警阈值，不因缺失情绪数据而提升或降低灵敏度

### Requirement: abnormal_sound 告警类型
系统 SHALL 支持新的告警类型 `abnormal_sound`，用于独立于 fight 的纯音频异常事件告警。

#### Scenario: 音频检测到尖叫但无视觉打架
- **GIVEN** AudioEventDetector 检测到尖叫且置信度 >= ABNORMAL_SOUND_CONF(0.4)
- **WHEN** 视觉侧无打架证据且持续 >= ABNORMAL_SOUND_DURATION(2s)
- **THEN** 系统 SHALL 产生 AlarmEvent(type="abnormal_sound", level=1)，包含 snapshot、camera_id、audio_event、audio_confidence 等元数据

#### Scenario: 音频检测到哭泣/呼救声
- **GIVEN** AudioEventDetector 检测到哭泣且置信度 >= 0.3
- **WHEN** 持续 >= 2s
- **THEN** 系统 SHALL 产生 abnormal_sound 告警，extra.audio_event="Crying"

#### Scenario: 连续多类异常声音
- **GIVEN** 短时间内先后检测到尖叫、哭泣、玻璃破碎
- **WHEN** 各类事件在去重窗口内
- **THEN** 系统 SHALL 合并为一个 abnormal_sound 告警，extra.detected_events 列出所有检测到的事件类型

## MODIFIED Requirements

### Requirement: FightPlugin 音频侧升级
系统 SHALL 将 FightPlugin 的音频侧从纯 DSP 特征升级为 YAMNet 语义检测 + DSP fallback 的双轨架构。

#### Scenario: YAMNet 可用时优先语义检测
- **GIVEN** YAMNet 模型已成功加载
- **WHEN** FightPlugin.feed_audio(chunk) 被调用
- **THEN** 系统 SHALL 使用 YAMNet 的 embedding + 事件分类作为音频特征，替代原有的 rms/zcr/spectral_centroid 评分

#### Scenario: YAMNet 不可用时降级到 DSP
- **GIVEN** YAMNet 模型加载失败或推理超时
- **WHEN** FightPlugin 需要音频评分
- **THEN** 系统 SHALL 降级使用原有 RMS/ZCR/Spectral 的 aud_score 路径
