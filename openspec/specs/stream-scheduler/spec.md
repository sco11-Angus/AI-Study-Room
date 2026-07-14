# Stream Scheduler

## Purpose
通过多摄像头独立解码、共享推理和跳帧调度平衡 AI 推理负载与视频流实时性，保持预览、检测、抓拍和回放均使用一致的摄像头帧来源并控制端到端延迟。

## Requirements

### Requirement: 跳帧调度
The system SHALL 通过跳帧机制平衡推理负载和实时性，保证端到端延迟不超过 2 秒。

#### Scenario: 跳帧推理
- **GIVEN** 视频流以正常帧率到达
- **WHEN** 调度器按 SKIP_N 参数跳帧
- **THEN** 每 N 帧执行一次 AI 推理，其余帧直接转发

#### Scenario: 多摄像头调度
- **GIVEN** 多个摄像头已注册
- **WHEN** 调度器启动
- **THEN** 每个摄像头独立解码线程，共享推理引擎线程池

#### Scenario: 摄像头离线检测
- **GIVEN** 一个摄像头连续超时
- **WHEN** 连续超时次数达到阈值
- **THEN** 标记摄像头为离线，停止解码线程
