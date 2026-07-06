# B 任务书 — 防区入侵检测（模块二，25 分核心）

> 角色定位：分值最高的核心模块。几何判定与时空防抖骨架已在 `intrusion.py` 写好，你负责接入 YOLOv8n、封装插件、打通前后端。
> 关联设计：系统设计说明书 §5。
> 涉及文件：`backend/app/detectors/intrusion.py`、`backend/app/api/regions.py`、`backend/app/detectors/base.py`(A 提供)、`backend/tests/test_intrusion.py`。
> 依赖：A1 Detector 接口、D 的 region 表、E 的 AlarmEvent 结构。

---

## 一、任务拆解

### 任务 B1：YOLOv8n 人员检测
- `pip` 安装 `ultralytics`，下载 `yolov8n.pt` 放 `backend/model_weights/`。
- 封装 `PersonDetector`：输入 BGR 帧，输出人员框列表 `[(x1,y1,x2,y2,conf), ...]`，只保留 `cls==0`(person) 且 `conf>0.35`。
- 在 `setup()` 中加载模型一次，避免每帧重载。

### 任务 B2：接入几何判定（骨架已写好，勿改判定公式）
- 复用 `IntrusionDetector.base_point()`（底边中心 `(cx, cy)`）与 `judge(box, ts)`。
- 每个防区维护一个 `IntrusionDetector` 实例（用 `region_id` 索引），各自独立计时。
- 一个人对多个防区：遍历所有防区分别 `judge`。

### 任务 B3：封装为 Detector 插件（不得自建线程池）
新建 `IntrusionPlugin(Detector)`，实现 A 的接口：

```python
class IntrusionPlugin(Detector):
    name = "intrusion"
    def setup(self):        # 加载 YOLOv8n + 从 DB 读取所有 region
        ...
    def detect(self, frame):  # YOLO 出框 -> 遍历防区 judge -> 命中则产出 AlarmEvent(type="intrusion")
        ...
    def on_config_changed(self, cfg):  # 防区增删改后热更新实例
        ...
```
- 告警事件 `type="intrusion"`，`region_id` 填触发防区，字段结构以 E 冻结版为准。

### 任务 B4：防区 CRUD 接口（§5.2）
完善 `backend/app/api/regions.py` 四个接口，接 D 的 `region` 表真正落库：
- `POST /api/regions`：校验 `polygon`(≥3点) / `x_distance`(≥0) / `y_stay_time`(≥0)，写库。
- `GET /api/regions?camera_id=`、`PUT`、`DELETE`。
- 写库/删除后调用 `engine` 的 `on_config_changed` 通知插件热更新。

### 任务 B5：坐标映射（防多分辨率错位）
- F 提交归一化坐标 `[0,1]`，B 侧按 `camera.resolution` 映射回像素后存库；或约定 F 直接传像素坐标——**与 F 当面定死一种**，写进接口注释。

---

## 二、交付物清单

| 编号 | 交付物 | 文件 | 截止 |
| --- | --- | --- | --- |
| B1 | 人员检测 | `detectors/intrusion.py` | W1 |
| B2/B3 | 入侵插件 | `detectors/intrusion.py` | W2 |
| B4 | regions CRUD | `api/regions.py` | W1（D 表就绪后） |
| B5 | 坐标映射 | `api/regions.py` | 与 F 联调时 |

---

## 三、判定逻辑（已实现，禁止改动公式）

```
D = cv2.pointPolygonTest(polygon, (cx, cy), True)
① D >= 0                      → 闯入        → 计时器累计
② D < 0 且 |D| <= X_distance  → 低于安全距离 → 计时器累计
③ 其余                        → 安全        → 计时器清零
危险无间断累计 >= Y_stay_time  → 触发告警
```

---

## 四、验收标准（逐条可测）

- [ ] 用测试视频，人员进入防区停留超 `Y_stay_time` 秒 → 产生 1 条 intrusion 告警。
- [ ] 人员在边界外 `X_distance` 像素内停留 → 同样告警（②分支）。
- [ ] 短暂进出（<`Y_stay_time`）不告警（计时清零）。
- [ ] `pytest backend/tests/test_intrusion.py` 全绿（已含 3 用例，可补充②分支用例）。
- [ ] 新建/删除防区后无需重启，判定立即生效（热更新）。
- [ ] 画区参数与后端判定坐标一致，1080p/720p 均不错位。

---

## 五、协作接口

| 方向 | 对象 | 约定 |
| --- | --- | --- |
| 依赖 | A | `Detector`/`Frame`、`engine.on_config_changed` |
| 依赖 | D | `region` 表结构、DB 会话 |
| 依赖 | E | `AlarmEvent` 结构（type="intrusion"） |
| 依赖 | F | 画区坐标格式（归一化 or 像素，二选一定死） |
