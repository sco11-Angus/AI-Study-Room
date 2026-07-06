# C 任务书 — 疲劳检测 + 自习伴侣 + 人脸识别

> 角色定位：疲劳与人脸均基于 Dlib，技术栈一致合并给一人。
> 关联设计：系统设计说明书 §4、§7.2。
> 涉及文件：`backend/app/detectors/fatigue.py`、`backend/app/detectors/face.py`、`backend/app/api/seat_status.py`、`backend/app/detectors/base.py`(A 提供)。
> 依赖：A1 Detector 接口与 engine.set_enabled、D 的 seat_status/member 表、E 的告警结构。

---

## 一、任务拆解

### 任务 C1：Dlib 环境与关键点
- 安装 `dlib`，下载 `shape_predictor_68_face_landmarks.dat` 放 `backend/model_weights/`。
- 封装人脸关键点提取：BGR 帧 → 68 点坐标（`dlib.get_frontal_face_detector` + `shape_predictor`）。

### 任务 C2：疲劳检测（EAR/MAR，公式已写好）
完善 `backend/app/detectors/fatigue.py`：
- 复用 `eye_aspect_ratio()` / `mouth_aspect_ratio()`（勿改公式）。
- EAR 索引：左眼 36-41、右眼 42-47，取双眼均值；MAR 用 60-67。
- 闭眼判定：`EAR < Config.EAR_THRESH(0.2)` **持续 ≥ `EAR_DURATION`(2s)** → `sleepy`；用时间戳累计，中途睁眼清零。
- 打哈欠：`MAR > Config.MAR_THRESH(0.6)` → `yawn`。
- 返回值：`"sleepy"` / `"yawn"` / `None`。

### 任务 C3：封装疲劳 Detector 插件（弱提醒，非公用告警）
- `FatiguePlugin(Detector)`，`name="fatigue"`。
- 命中时产出**弱提醒**事件（`type="fatigue"`, `level=0` 或专用 weak 标记），E/F 据此只推给该用户专属端，**不触发大屏红闪蜂鸣**。
- 只对 `enabled=True`（studying）的座位跑，禁止自建线程。

### 任务 C4：自习状态接口（激活/挂起，§4.2）
完善 `backend/app/api/seat_status.py`：
- `POST /api/seat-status` 落库（D 的 seat_status 表）。
- `studying` → `engine.set_enabled("fatigue", True)`（针对该 region）激活。
- `resting` → `engine.set_enabled("fatigue", False)` 立即挂起，释放算力，趴桌/闭眼均不检测。
- 与 A 约定：按 region 粒度启停（可在插件内维护 `enabled_regions` 集合）。

### 任务 C5：人脸识别（供 E 抓拍调用，§7.2）
完善 `backend/app/detectors/face.py`：
- `encode(face_img) -> 128维向量`（`dlib.face_recognition_model_v1`）。
- `match(feature) -> "member:<id>" / "stranger"`：遍历 `member` 表特征，欧氏距离最近邻，`> threshold(0.6)` 判为 stranger。
- 会员注册：提供批量把会员照片编码入库的脚本（写入 `member.feature`）。
- **不是 Detector 插件**，是被 E 的 `AlarmService` 抓拍时同步调用的服务。

---

## 二、交付物清单

| 编号 | 交付物 | 文件 | 截止 |
| --- | --- | --- | --- |
| C1/C2 | EAR/MAR 疲劳判定 | `detectors/fatigue.py` | W1 |
| C3 | 疲劳插件 | `detectors/fatigue.py` | W2 |
| C4 | 状态接口+启停 | `api/seat_status.py` | W2 |
| C5 | 人脸匹配服务 | `detectors/face.py` | W2 |

---

## 三、验收标准（逐条可测）

- [ ] `studying` 下持续闭眼 2s → 弱提醒事件；**大屏不红闪、不蜂鸣**。
- [ ] 打哈欠（MAR 超标）→ yawn 弱提醒。
- [ ] 切 `resting` 后趴桌/闭眼均无任何提醒，`top` 可见该检测负载下降。
- [ ] 切回 `studying` 检测恢复。
- [ ] 会员照片匹配返回 `member:<id>`，陌生人返回 `stranger`。
- [ ] 中途睁眼后计时清零，不误报。

---

## 四、协作接口

| 方向 | 对象 | 约定 |
| --- | --- | --- |
| 依赖 | A | `Detector`/`Frame`、`engine.set_enabled(name, enabled)` |
| 依赖 | D | `seat_status`、`member` 表 |
| 依赖 | E | 弱提醒事件如何路由（只推私有端） |
| 下游 | E | 提供 `FaceMatcher.match()` 供抓拍调用 |
| 下游 | F | 伴侣页状态切换 + 弱提醒展示 |
