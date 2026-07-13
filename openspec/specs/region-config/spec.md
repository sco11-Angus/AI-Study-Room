# Region Config

## Purpose
提供基于实时视频的 Canvas 画区工具和参数持久化能力，支持管理员创建、编辑、查询和删除危险防区或座位防区，并让配置变更无需重启即可生效。

## Requirements

### Requirement: 防区可视化配置
The system SHALL 提供 Canvas 画区工具，允许用户在视频画面上绘制多边形防区，并将参数持久化到数据库。

#### Scenario: 创建防区
- **GIVEN** 一个已连接的摄像头
- **WHEN** 用户在画面上绘制多边形并保存
- **THEN** 防区顶点坐标和关联参数持久化到数据库

#### Scenario: 编辑防区
- **GIVEN** 一个已存在的防区
- **WHEN** 用户修改多边形顶点并保存
- **THEN** 数据库中对应的防区记录更新
