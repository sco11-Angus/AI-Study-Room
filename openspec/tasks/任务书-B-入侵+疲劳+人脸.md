# B 任务书 — 防区入侵检测 + 疲劳检测 + 自习伴侣 + 人脸识别

> 角色定位：视觉感知主力。承担模块二（防区入侵，25 分核心）+ 模块一（疲劳/自习伴侣）+ 人脸识别，均基于「YOLO 人员检测 + Dlib 关键点」的视觉栈，集中一人减少模型重复加载。
> 关联设计：系统设计说明书 §4、§5、§7.2。
> 涉及文件：`backend/app/detectors/intrusion.py`、`backend/app/detectors/fatigue.py`、`backend/app/detectors/face.py`、`backend/app/api/regions.py`、`backend/app/api/seat_status.py`、`backend/app/detectors/base.py`(A 提供)、`backend/tests/test_intrusion.py`。
> 依赖：A1 Detector 接口与 engine.set_enabled/on_config_changed、C 的 region/seat_status/member 表、E 的 AlarmEvent 结构。

---

## 第一部分：防区入侵检测（模块二，25 分核心）

### 任务 B1：YOLOv8n 人员检测（本任务的公共基础）
- 安装 `ultralytics`，下载 `yolov8n.pt` 放 `backend/model_weights/`。
- 封装 `PersonDetector`：输入 BGR 帧，输出人员框列表 `[(x1,y1,x2,y2,conf), ...]`，只保留 `cls==0`(person) 且 `conf>0.35`。
- `setup()` 中加载模型一次，避免每帧重载。**入侵检测复用此人员框**。

### 任务 B2：接入几何判定（骨架已写好，勿改判定公式）
- 复用 `IntrusionDetector.base_point()`（底边中心 `(cx, cy)`）与 `judge(box, ts)`。
- 每个防区维护一个 `IntrusionDetector` 实例（`region_id` 索引），各自独立计时。
- 一个人对多个防区：遍历所有防区分别 `judge`。

### 任务 B3：封装入侵 Detector 插件（不得自建线程池）
```python
class IntrusionPlugin(Detector):
    name = "intrusion"
    def setup(self):        # 加载 YOLOv8n + 从 DB 读取所有 region
        ...
    def detect(self, frame):  # YOLO 出框 -> 遍历防区 judge -> 命中产出 AlarmEvent(type="intrusion")
        ...
    def on_config_changed(self, cfg):  # 防区增删改后热更新实例
        ...
```
- 告警 `type="intrusion"`，`region_id` 填触发防区，结构以 E 冻结版为准。

### 任务 B4：防区 CRUD 接口（§5.2）
完善 `backend/app/api/regions.py`，接 C 的 `region` 表落库：
- `POST /api/regions`：校验 `polygon`(≥3点) / `x_distance`(≥0) / `y_stay_time`(≥0)，写库。
- `GET /api/regions?camera_id=`、`PUT`、`DELETE`。
- 写库/删除后调 `engine.on_config_changed` 通知插件热更新。

### 任务 B5：坐标映射（防多分辨率错位）
- F 提交归一化坐标 `[0,1]`，B 按 `camera.resolution` 映射回像素存库；或约定 F 传像素坐标——**与 F 当面定死一种**，写进接口注释。

### 入侵判定逻辑（已实现，禁止改动公式）
```
D = cv2.pointPolygonTest(polygon, (cx, cy), True)
① D >= 0                      → 闯入        → 计时器累计
② D < 0 且 |D| <= X_distance  → 低于安全距离 → 计时器累计
③ 其余                        → 安全        → 计时器清零
危险无间断累计 >= Y_stay_time  → 触发告警
```

<!-- APPEND-B -->
---

## 第二部分：疲劳检测 + 自习伴侣（模块一）

### 任务 B6：Dlib 环境与关键点
- 安装 `dlib`（本仓库已用 `dlib-bin` 预编译包），下载 `shape_predictor_68_face_landmarks.dat` 放 `model_weights/`。
- 封装 68 点关键点提取：BGR 帧 → 68 点坐标。**人脸识别（B9）复用同一检测器/关键点。**

### 任务 B7：疲劳检测（EAR/MAR，公式已写好）
完善 `backend/app/detectors/fatigue.py`：
- 复用 `eye_aspect_ratio()` / `mouth_aspect_ratio()`（勿改公式）。EAR 索引左眼 36-41、右眼 42-47 取均值；MAR 用 60-67。
- 闭眼：`EAR < EAR_THRESH(0.2)` **持续 ≥ `EAR_DURATION`(2s)** → `sleepy`；时间戳累计，睁眼清零。
- 打哈欠：`MAR > MAR_THRESH(0.6)` → `yawn`。返回 `"sleepy"/"yawn"/None`。

### 任务 B8：疲劳插件 + 自习状态接口
- `FatiguePlugin(Detector)`，`name="fatigue"`；命中产出**弱提醒**事件（`type="fatigue"`, `level=0`），只推该用户私有端，**不触发大屏红闪蜂鸣**。禁止自建线程。
- `POST /api/seat-status` 落库；`studying` → `engine.set_enabled("fatigue", True)`（按 region）；`resting` → `set_enabled(..., False)` 立即挂起、释放算力，趴桌/闭眼均不检测。

---

## 第三部分：人脸识别（模块四抓拍，§7.2）

### 任务 B9：人脸特征匹配（供 E 抓拍调用）
完善 `backend/app/detectors/face.py`：
- `encode(face_img) -> 128维向量`（Dlib）。
- `match(feature) -> "member:<id>" / "stranger"`：遍历 `member` 表特征，欧氏距离最近邻，`> 0.6` 判 stranger。
- 提供批量把会员照片编码入库的脚本（写 `member.feature`）。
- **不是 Detector 插件**，是 E 的 `AlarmService` 抓拍时同步调用的服务。

---

## 交付物清单

| 编号 | 交付物 | 文件 | 截止 |
| --- | --- | --- | --- |
| B1 | 人员检测（公共基础） | `detectors/intrusion.py` | W1 |
| B2/B3 | 入侵插件 | `detectors/intrusion.py` | W2 |
| B4/B5 | regions CRUD + 坐标映射 | `api/regions.py` | W1（C 表就绪后） |
| B6/B7 | Dlib + EAR/MAR | `detectors/fatigue.py` | W2 |
| B8 | 疲劳插件 + 状态接口 | `detectors/fatigue.py`、`api/seat_status.py` | W2 |
| B9 | 人脸匹配服务 | `detectors/face.py` | W3 |

> 工作量提示：B 现在承担三块（入侵/疲劳/人脸），是全组最重的一人。优先级：入侵（25分核心）> 疲劳 > 人脸。人脸可放到最后，若排期紧张与 E 协商降级。

---

## 验收标准（逐条可测）

**入侵**
- [ ] 人员进入防区停留超 `Y_stay_time` → 1 条 intrusion 告警。
- [ ] 边界外 `X_distance` 像素内停留 → 告警（②分支）。
- [ ] 短暂进出（<`Y_stay_time`）不告警。
- [ ] `pytest backend/tests/test_intrusion.py` 全绿。
- [ ] 新建/删除防区无需重启即生效（热更新）。
- [ ] 画区坐标 1080p/720p 均不错位。

**疲劳/伴侣**
- [ ] `studying` 下闭眼 2s → 弱提醒；大屏不红闪、不蜂鸣。打哈欠 → yawn。
- [ ] 切 `resting` 后无任何提醒，`top` 见负载下降；切回恢复。
- [ ] 中途睁眼计时清零，不误报。

**人脸**
- [ ] 会员照片 → `member:<id>`；陌生人 → `stranger`。

---

## 协作接口

| 方向 | 对象 | 约定 |
| --- | --- | --- |
| 依赖 | A | `Detector`/`Frame`、`engine.on_config_changed`、`engine.set_enabled` |
| 依赖 | C | `region`/`seat_status`/`member` 表、DB 会话 |
| 依赖 | E | `AlarmEvent` 结构（type=intrusion/fatigue）、弱提醒路由 |
| 依赖 | F | 画区坐标格式（归一化 or 像素，定死一种） |
| 下游 | E | 提供 `FaceMatcher.match()` 供抓拍调用 |

