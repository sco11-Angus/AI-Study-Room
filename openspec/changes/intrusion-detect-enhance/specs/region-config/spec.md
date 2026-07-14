## MODIFIED Requirements

### Requirement: 防区可视化配置
The system SHALL 提供 Canvas 画区工具，允许用户在视频画面上绘制多边形防区，并将参数持久化到数据库。对于 `seat` 类型防区，配置页 SHALL 提供预约成员绑定/解绑操作界面。

#### Scenario: 创建防区
- **GIVEN** 一个已连接的摄像头
- **WHEN** 用户在画面上绘制多边形并保存
- **THEN** 防区顶点坐标和关联参数持久化到数据库

#### Scenario: 编辑防区
- **GIVEN** 一个已存在的防区
- **WHEN** 用户修改多边形顶点并保存
- **THEN** 数据库中对应的防区记录更新

#### Scenario: seat 防区显示预约控件
- **GIVEN** 用户选中一个 `type=seat` 的防区
- **WHEN** 防区配置页渲染编辑表单
- **THEN** 表单中显示"预约成员"下拉选择（数据来源 `GET /api/members?face_enrolled=true`）、"绑定"按钮、"解绑"按钮和当前绑定状态

#### Scenario: danger_zone 防区不显示预约控件
- **GIVEN** 用户选中一个 `type=danger_zone` 的防区
- **WHEN** 防区配置页渲染编辑表单
- **THEN** 表单中不显示预约成员相关控件

#### Scenario: 绑定预约成员后展示状态
- **GIVEN** 座位防区 A 已绑定预约成员 M
- **WHEN** 用户在防区配置页查看防区 A
- **THEN** 表单中显示"当前预约：{M 的姓名}"和解绑按钮

#### Scenario: 绑定/解绑后热更新
- **GIVEN** 用户在防区配置页为座位 A 绑定成员 M
- **WHEN** 绑定 API 返回成功
- **THEN** 前端更新绑定状态展示，后端 `IntrusionPlugin` 热更新无需重启
