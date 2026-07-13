# AI Study Room

实时视频分析监测系统（智慧自习室 AI 管家）是一个面向共享自习室的智能管理平台。项目通过视频流、计算机视觉算法、前端可视化看板和第三方通知能力，将传统被动监控升级为主动感知、及时告警、闭环处置的自习室安全与秩序管理系统。

## 项目定位

- 服务对象：自习室运营方、现场管理员、备考自习学生。
- 核心目标：降低无人值守场景下的违规占座、尾随进入、抽烟明火、疲劳异常和突发安全风险。
- MVP 版本：V1.0.0。

## 核心能力

### 1. 用户自习状态宣告

学生可主动切换座位状态：

- `studying`：激活对应座位的疲劳检测。
- `resting`：挂起对应座位的疲劳检测，释放算力并避免打扰。

系统通过 Dlib 人脸关键点计算 EAR/MAR，用于识别闭眼、打哈欠等疲劳状态，并以弱提醒方式通知用户。

### 2. 危险区域与座位防区检测

管理员可在 Web 端视频画面上使用 Canvas 绘制多边形 ROI 防区或座位格子，并配置：

- `X_distance`：安全距离阈值。
- `Y_stay_time`：允许危险停留时间。

后端通过 YOLOv8n 检测人员框，以检测框底边中心点作为基准点，结合 `cv2.pointPolygonTest` 判断是否闯入或过近停留，并通过时空防抖减少误报。

### 3. 烟雾与明火检测

系统集成轻量化烟火检测模型，在连续 30 帧有效推理窗口内计算平均置信度。只有烟雾或明火平均置信度超过 45% 时，才触发有效灾情告警。

### 4. 告警中心与闭环通知

真实告警触发后，系统执行闭环动作：

- 抓取现场帧并裁剪人脸。
- 在 Web 看板上将对应防区或座位标记为红色闪烁。
- 通过钉钉群机器人发送告警卡片。
- 若主责安全员 3 分钟内未确认，自动升级通知负责人。

## 技术架构

项目采用“端-流-云-网”架构：

| 层级 | 组件 | 职责 |
| --- | --- | --- |
| 端 | IP 摄像头 | 采集 H.264/AAC 音视频流 |
| 流 | Nginx-RTMP | 推拉流转发，支持前端低延迟播放 |
| 云 | Python Flask + OpenCV + YOLOv8n + Dlib | 视频解码、跳帧推理、几何判定、告警状态机、数据持久化 |
| 网 | Vue 3 + Element Plus | 管理看板、Canvas 画区、参数配置、实时告警中心 |

## 性能设计

- 推理链路采用跳帧机制，默认每 5 帧执行一次 AI 分析。
- 帧队列使用有界缓冲，避免推理堆积导致延迟放大。
- 目标延迟：Web 端画面整体延迟控制在 2 秒以内。
- 目标部署规格：2 核 CPU、2GB 内存、4Mbps 带宽的低配 Linux 云服务器。

## 文档结构

| 文件 | 说明 |
| --- | --- |
| `openspec/project.md` | 项目上下文与规范驱动索引 |
| `openspec/specs/spec.md` | OpenSpec 能力边界定义 |
| `openspec/specs/PRD.md` | 产品需求文档 |
| `openspec/specs/系统设计说明书.md` | 系统设计说明书 |
| `openspec/specs/数据库设计.md` | 数据库设计 |
| `openspec/tasks/` | 六人任务书与协作顺序 |
| `openspec/progress/progress.md` | 会话进度记录 |
| `openspec/progress/claude-progress.md` | Codex/Claude 工作记录 |
| `AGENTS.md` | 协作与开工流程说明 |
| `feature_list.json` | 功能状态事实来源 |
| `init.sh` | 标准 smoke test 入口 |

## OpenSpec 工作流

新增模块或跨模块功能必须先创建 OpenSpec change，再编写代码。首次在仓库根目录安装工具依赖：

```powershell
npm install
```

常用命令：

```powershell
npm run spec:list
npm run spec:new -- <verb-noun-change-id>
npm run spec:status -- --change <change-id>
npm run spec:validate
npm run spec:archive -- <change-id> --yes
```

每个 change 必须完成 `proposal.md`、`design.md`、`tasks.md` 和受影响能力的 delta spec；`npm run spec:validate` 通过前不得开始实现。`openspec/proposals/` 仅用于历史参考，新功能统一放在 `openspec/changes/`。

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
└── openspec/           # 规范驱动开发（§10.3）
    ├── project.md      # 项目上下文
    ├── config.yaml     # OpenSpec 配置
    ├── specs/          # 真理源规范：spec / PRD / 系统设计说明书 / 数据库设计
    ├── changes/        # 变更提案与归档
    ├── tasks/          # 六人任务书与协作顺序
    └── progress/       # 会话进度记录
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

## 验证

标准入口：

```sh
./init.sh
```

Windows PowerShell:

```powershell
.\init.cmd
```

`init.cmd`、`init.ps1` 和 `init.sh` 会先执行 OpenSpec 严格校验；首次运行前请先在仓库根目录执行 `npm install`。

PowerShell implementation script, if your execution policy allows it:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\init.ps1
```

Windows cmd:

```bat
init.cmd
```

PowerShell 不能直接执行 `./init.sh`，除非系统额外配置了兼容的 shell launcher。Windows 下使用 `.\init.cmd`；Git Bash、WSL、Linux 或 macOS 下使用 `./init.sh`。

## GitHub

仓库地址：[sco11-Angus/AI-Study-Room](https://github.com/sco11-Angus/AI-Study-Room)
