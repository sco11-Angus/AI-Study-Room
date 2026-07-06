# 实时视频分析监测系统 — 智慧自习室 AI 管家平台

基于「端-流-云-网」一体化架构的实时视频分析监测系统。详见 [系统设计说明书](./系统设计说明书.md)。

## 技术栈

- 前端（网）：Vue 3 + Element Plus + Vite
- 后端（云）：Python + Flask + OpenCV + YOLOv8n + Dlib
- 流媒体（流）：Nginx-RTMP
- 数据库：SQLite / MySQL

## 目录结构

```
App/
├── backend/            # Flask 业务/算法后端（云）
│   ├── app/
│   │   ├── api/        # API 层（§9 OpenAPI/Swagger）
│   │   ├── models/     # 数据模型（§8）
│   │   ├── stream/     # 流处理与跳帧调度（§3）
│   │   ├── detectors/  # 疲劳/入侵/烟火/人脸 检测算法（§4-7）
│   │   └── services/   # 告警状态机、几何判定、钉钉上报
│   ├── model_weights/  # YOLO/Dlib 权重
│   ├── snapshots/      # 告警抓拍图
│   ├── tests/
│   ├── requirements.txt
│   └── run.py
├── frontend/           # Vue 3 + Element Plus（网）
│   └── src/
│       ├── api/
│       ├── views/      # Dashboard / RegionConfig / SeatCompanion
│       ├── components/ # VideoPlayer / CanvasDraw / AlarmPanel
│       ├── store/
│       └── router/
├── streaming/          # Nginx-RTMP 配置（流）
├── deploy/             # 部署编排（§11）
├── specs/              # OpenSpec 规范驱动（§10.3）
└── 系统设计说明书.md
```

## 快速开始

```bash
# 后端
cd backend && pip install -r requirements.txt && python run.py

# 前端
cd frontend && npm install && npm run dev

# 流媒体
docker compose -f deploy/docker-compose.yml up -d
```
