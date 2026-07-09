# 人脸活体检测 Anti-Spoofing Spec

## Why
当前人脸识别系统仅做 1:1 特征匹配，无法防御静态照片、视频回放、AI 换脸等欺骗攻击。攻击者仅需在摄像头前放置一张照片或播放一段视频即可通过认证，严重威胁自习室安全管理。

## What Changes
- 新增 `LivenessDetector` 活体检测类，基于多信号融合判别真伪
- 在 `FaceDetector.detect()` 中集成活体检测流程
- 活体失败时产出 `face_spoof` 告警类型，不下发正常识别结果
- 通过 WebSocket 向前端推送欺骗告警
- 新增 liveness 相关配置项（阈值、帧窗口等）

## Impact
- Affected specs: face_recognition (增强)
- Affected code:
  - `backend/app/detectors/face.py` — 新增 LivenessDetector，增强 FaceDetector
  - `backend/app/config.py` — 新增活体检测配置项
  - `backend/app/api/ws.py` — 支持 face_spoof 消息类型
  - `backend/tests/test_face.py` — 新增活体检测单元测试

## ADDED Requirements

### Requirement: LivenessDetector 多信号融合活体检测
系统 SHALL 提供 `LivenessDetector` 类，结合以下三种信号加权融合判定人脸真伪：
1. **眨眼检测**：基于 EAR（Eye Aspect Ratio）时序变化，检测是否发生自然眨眼
2. **微动分析**：基于面部区域光流（optical flow），判断是否有自然的 3D 微动
3. **纹理分析**：基于 LBP（Local Binary Patterns）直方图，检测翻拍/打印造成的纹理异常（摩尔纹、色彩偏移、模糊等）

#### Scenario: 静态照片攻击被检测
- **GIVEN** 攻击者在摄像头前放置一张打印照片
- **WHEN** 系统连续处理视频帧
- **THEN** 眨眼检测发现 EAR 无变化，微动分析发现光流近乎为零，纹理分析检测到翻拍伪影
- **AND** 融合分数 < 活体阈值，产出 `face_spoof` 告警

#### Scenario: 视频回放攻击被检测
- **GIVEN** 攻击者使用手机播放目标人物的视频
- **WHEN** 系统连续处理视频帧
- **THEN** 纹理分析检测到屏幕摩尔纹/色彩偏移，微动分析可能发现不自然的 2D 平面运动
- **AND** 融合分数 < 活体阈值，产出 `face_spoof` 告警

#### Scenario: AI 换脸攻击被检测
- **GIVEN** 攻击者使用 AI 实时换脸工具
- **WHEN** 系统连续处理视频帧
- **THEN** 纹理分析检测到面部区域边缘不自然的融合伪影或像素级异常
- **AND** 融合分数 < 活体阈值，产出 `face_spoof` 告警

#### Scenario: 真实人脸通过活体检测
- **GIVEN** 真实人员正对摄像头
- **WHEN** 系统连续处理视频帧
- **THEN** 眨眼检测检测到自然眨眼，面部区域有自然微动，纹理特征正常
- **AND** 融合分数 >= 活体阈值，继续执行正常的人脸匹配流程

### Requirement: FaceDetector 集成活体检测
系统 SHALL 在 `FaceDetector.detect()` 中，于人脸匹配前插入活体检测步骤：
- 检测到人脸 → 先执行活体检测 → 活体通过才进行匹配
- 活体失败 → 产出 `face_spoof` AlarmEvent，不再进行匹配
- `face_spoof` 事件通过 WebSocket 推送给前端

#### Scenario: 活体检测失败不下发匹配结果
- **WHEN** 活体检测判定为欺骗
- **THEN** 返回 `AlarmEvent(type="face_spoof")` 而非 `AlarmEvent(type="face_recognition")`
- **AND** 不执行会员特征匹配

### Requirement: 活体检测配置项
系统 SHALL 在 `Config` 中新增以下配置项，通过 `.env` 控制：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `LIVENESS_ENABLED` | `true` | 是否启用活体检测 |
| `LIVENESS_THRESHOLD` | `0.5` | 活体融合分阈值，低于此值判为欺骗 |
| `LIVENESS_HISTORY_SIZE` | `30` | 历史帧缓存数量（约 1 秒 @30fps） |
| `LIVENESS_EAR_BLINK_THRESH` | `0.25` | 眨眼 EAR 低阈值 |

#### Scenario: 通过 .env 关闭活体检测
- **WHEN** `LIVENESS_ENABLED=false`
- **THEN** FaceDetector 跳过活体检测，直接执行匹配，行为与修改前一致

### Requirement: WebSocket 支持 face_spoof 消息
系统 SHALL 扩展 WebSocket 消息类型，支持 `face_spoof` 类型：
```json
{
  "type": "face_spoof",
  "confidence": 0.92,
  "reasons": ["no_blink", "low_motion", "texture_anomaly"]
}
```

#### Scenario: 前端收到欺骗告警
- **WHEN** 系统检测到人脸欺骗
- **THEN** WebSocket 推送 `face_spoof` 消息，前端可展示"检测到欺骗攻击"警告
