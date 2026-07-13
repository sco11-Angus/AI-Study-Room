# Seat Status

## Purpose
座位状态切换驱动疲劳算法在自习、休息和空闲状态之间可靠激活或挂起，避免无关座位消耗推理资源，并确保状态变更可立即同步到运行中的检测器。

## Requirements

### Requirement: 座位状态切换驱动疲劳检测
The system SHALL 根据座位的 `studying` / `idle` 状态切换，驱动疲劳检测算法的激活或挂起。

#### Scenario: 座位进入学习状态
- **GIVEN** 一个空闲座位
- **WHEN** 座位状态切换为 `studying`
- **THEN** 疲劳检测算法对该座位的关联摄像头区域激活

#### Scenario: 座位离开
- **GIVEN** 一个学习中的座位
- **WHEN** 座位状态切换为 `idle`
- **THEN** 疲劳检测算法对该座位的关联摄像头区域挂起
