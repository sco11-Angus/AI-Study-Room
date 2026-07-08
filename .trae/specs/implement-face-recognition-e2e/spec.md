# 人脸识别端到端测试 Spec

## Why
当前后端已有 `FaceMatcher`（特征提取+匹配）和 `Member` 表，但缺少一个完整的端到端链路：从 RTMP 视频流中检测人脸、提取关键帧、与会员库比对、并将结果实时推送到前端展示。告警中心尚未完成，因此本功能绕过告警闭环，直接走“识别→推送→前端展示”的轻量路径。

## What Changes
- 新增 **FaceDetector** 检测器（实现 `Detector` 接口），集成到推理引擎
- 完善 **AlarmService** 的 WebSocket 推送能力（人脸识别结果通道）
- 新增后端 WebSocket 端点 `/ws/face_recognition` 推送识别结果
- 新增前端人脸识别结果展示组件：匹配会员显示“欢迎你, XXX”，未匹配显示“陌生人”
- 在 `run.py` 中注册 FaceDetector 到推理引擎
- 新增端到端测试脚本验证完整链路

## Impact
- Affected specs: 任务书-B（人脸检测），任务书-E（告警中心——仅借用 WebSocket 通道）
- Affected code:
  - `backend/app/detectors/face.py` — 新增 FaceDetector 类
  - `backend/app/services/alarm.py` — 实现 WebSocket 推送
  - `backend/app/api/ws.py` — 新增 `/ws/face_recognition` 端点
  - `backend/run.py` — 注册 FaceDetector
  - `frontend/src/views/Dashboard.vue` — 展示识别结果
  - `backend/tests/test_face.py` — 新增 E2E 测试

## ADDED Requirements

### Requirement: 人脸检测器 FaceDetector
系统 SHALL 提供一个实现 `Detector` 接口的人脸检测器，对每帧进行人脸检测、特征提取和会员匹配。

#### Scenario: 帧中检测到人脸并匹配会员
- **GIVEN** Member 表中有会员"张三"的特征数据
- **WHEN** 推流画面中出现张三的人脸
- **THEN** FaceDetector 产出一个 AlarmEvent，其中 `type="face_recognition"`, `extra` 包含 `{"face_match": "member:1", "name": "张三"}`

#### Scenario: 帧中检测到人脸但未匹配
- **GIVEN** Member 表中无匹配的特征数据
- **WHEN** 推流画面中出现陌生人的人脸
- **THEN** FaceDetector 产出一个 AlarmEvent，其中 `type="face_recognition"`, `extra` 包含 `{"face_match": "stranger"}`

#### Scenario: 帧中未检测到任何人脸
- **WHEN** 推流画面中没有人脸
- **THEN** FaceDetector 返回空列表，不产生任何事件

### Requirement: 人脸识别结果实时推送
系统 SHALL 通过 WebSocket 将人脸识别结果实时推送到前端。

#### Scenario: 前端接收识别结果
- **GIVEN** 前端已连接 `/ws/face_recognition`
- **WHEN** 后端完成一次人脸识别匹配
- **THEN** 前端收到 JSON 消息 `{"member_id": 1, "name": "张三", "type": "member"}` 或 `{"type": "stranger"}`

### Requirement: 前端人脸识别展示
前端 SHALL 在 Dashboard 页面实时展示人脸识别结果。

#### Scenario: 会员识别成功展示
- **GIVEN** 前端收到 `{"type": "member", "name": "张三"}`
- **THEN** 页面显示“欢迎你, 张三”的提示（持续展示直到新结果到来）

#### Scenario: 陌生人识别展示
- **GIVEN** 前端收到 `{"type": "stranger"}`
- **THEN** 页面显示“陌生人”提示

### Requirement: 端到端测试验证
系统 SHALL 提供端到端测试脚本，验证从视频流到前端展示的完整链路。

#### Scenario: E2E 测试通过
- **GIVEN** 测试脚本启动后端，通过 RTMP 推流含已知人脸的视频
- **WHEN** 系统完成人脸检测、特征提取、匹配
- **THEN** 测试断言 FaceDetector 正确返回匹配结果
