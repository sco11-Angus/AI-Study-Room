# 项目上下文（OpenSpec project.md）

> 本文件为规范驱动开发的入口，向协作者与 AI 提供项目背景、技术栈与规范索引。

## 项目简介

实时视频分析监测系统（智慧自习室 AI 管家）：面向共享自习室的智能管理平台，通过视频流、CV 算法、可视化看板和第三方通知，将被动监控升级为主动感知、及时告警、闭环处置。MVP 版本 V1.0.0。

## 技术栈

- 端：IP 摄像头，采集 H.264/AAC 音视频流
- 流：Nginx-RTMP 推拉流转发
- 云：Python Flask + OpenCV + YOLOv8n + Dlib
- 网：Vue 3 + Element Plus

## 约定

- 规范驱动：先在 `specs/` 明确能力边界，再编写代码。
- 每个能力对应一份规范，变更走 `changes/` 提案流程。
- 功能状态以根目录 `feature_list.json` 为唯一事实来源。
- 会话流程见根目录 `AGENTS.md`。

## 目录索引

| 路径 | 说明 |
| --- | --- |
| `specs/spec.md` | 能力边界定义（真理源） |
| `specs/PRD.md` | 产品需求文档 |
| `specs/系统设计说明书.md` | 系统设计说明书（SDD） |
| `specs/数据库设计.md` | 数据库设计 |
| `changes/` | 变更提案与 `archive/` 归档 |
| `tasks/` | 六人任务书与协作顺序 |
| `progress/` | 会话进度与工作记录 |
| `config.yaml` | OpenSpec 配置 |
