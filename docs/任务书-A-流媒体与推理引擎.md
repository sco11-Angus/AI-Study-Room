# A 任务书 — 流媒体 + 统一推理引擎 + 部署

> 角色定位：项目地基。**第一天**必须冻结「帧接口」与「Detector 插件接口」，B/C/D/E/F 全部依赖你的产出。
> 关联设计：系统设计说明书 §2、§3、§10、§11。
> 涉及文件：`streaming/nginx.conf`、`backend/app/stream/scheduler.py`、`backend/app/stream/engine.py`(新建)、`backend/app/detectors/base.py`(新建)、`deploy/docker-compose.yml`、`backend/Dockerfile`。

---

## 一、任务拆解（按交付顺序）

### 任务 A1：定义 Detector 插件接口（第一天，最高优先级）
新建 `backend/app/detectors/base.py`，供 B/C/D 统一实现：

```python
from dataclasses import dataclass

@dataclass
class Frame:
    image: "np.ndarray"   # BGR 图像
    ts: float             # 帧时间戳（秒，time.time()）
    camera_id: int
    frame_idx: int

class Detector:
    name: str                          # 唯一标识，如 "intrusion"
    enabled: bool = True               # 供 C 的 seat_status 动态启停
    def setup(self) -> None: ...        # 加载模型权重（引擎启动时调用一次）
    def detect(self, frame: Frame) -> list["AlarmEvent"]: ...  # 每帧调用，返回0或多个告警
    def on_config_changed(self, cfg: dict) -> None: ...        # 防区/参数热更新（可选）
```

- **交付标准**：接口定稿并提交，通知 B/C/D 开工。之后不得随意改签名。

### 任务 A2：统一推理引擎（杜绝算力争抢的核心）
新建 `backend/app/stream/engine.py`：

```python
class InferenceEngine:
    def register(self, detector: Detector) -> None: ...    # 注册检测器
    def unregister(self, name: str) -> None: ...
    def set_enabled(self, name: str, enabled: bool) -> None: ...  # 供 C 启停
    def dispatch(self, frame: Frame) -> list["AlarmEvent"]:       # 按注册顺序串行调各 enabled 检测器
```

- 维护**唯一**的 `ThreadPoolExecutor(max_workers=2)`，所有检测器在此执行。
- **硬约束**：检测器内部禁止出现 `Thread`、`ThreadPoolExecutor`、`while True` 推理循环。Code Review 逐个检查。
- 引擎启动时对所有已注册检测器调用一次 `setup()` 加载权重。

### 任务 A3：拉流 + 跳帧调度
完善 `backend/app/stream/scheduler.py`（现有骨架）：
- 每摄像头一个解码线程，`cv2.VideoCapture` 拉 RTMP。
- 环形缓冲 `deque(maxlen=3)`，满时丢最旧帧。
- 每 `Config.SKIP_N`(=5) 帧构造 `Frame` 提交 `InferenceEngine.dispatch`，其余帧仅供显示/推流。
- 断流检测：`cap.read()` 返回 False 时 `release()` 并重连，重连间隔 2s。
- 引擎返回的告警事件转交 E 的 `AlarmService.raise_alarm`。

### 任务 A4：Nginx-RTMP 流媒体
调通 `streaming/nginx.conf`：
- `:1935` 接收摄像头 RTMP 推流（application `live`）。
- `:8080/live` 输出 HTTP-FLV 供前端 F 播放，`gop_cache off` 降延迟。
- 提供给 F 的播放地址格式：`http://<host>:8080/live?app=live&stream=cam1`。
- 后端 A3 从 `rtmp://<host>:1935/live/cam1` 拉流。

### 任务 A5：部署编排
- 调通 `deploy/docker-compose.yml`：`nginx-rtmp` 与 `backend` 两服务，进程解耦。
- 完善 `backend/Dockerfile`（含 dlib/opencv 系统依赖），`gunicorn -w 2` 启动。
- 编写 `.env.example`（`DINGTALK_WEBHOOK`、`SKIP_N` 等）。

---

## 二、交付物清单

| 编号 | 交付物 | 文件 | 截止 |
| --- | --- | --- | --- |
| A1 | Detector/Frame 接口 | `detectors/base.py` | **D1（第一天）** |
| A2 | 推理引擎 | `stream/engine.py` | W1 |
| A3 | 拉流跳帧调度 | `stream/scheduler.py` | W1 |
| A4 | Nginx-RTMP 可播放 | `streaming/nginx.conf` | W1 |
| A5 | 一键部署 | `deploy/`、`Dockerfile` | 联调期 |

（D1=第一天，W1=第一周，下同）

---

## 三、验收标准（逐条可测）

- [ ] 用测试视频推流，前端播放画面整体延迟 ≤ 2s（手机秒表对拍验证）。
- [ ] `top` 观察 2 核机器上流分发进程 CPU < 40%。
- [ ] `grep -rn "ThreadPoolExecutor\|Thread(" backend/app/detectors` 无结果（检测器无自建线程）。
- [ ] 拔掉/恢复推流，后端 5s 内自动重连并继续出帧。
- [ ] `SKIP_N` 改为 1/5/10，推理频率随之变化，画面不卡顿。
- [ ] `docker compose up` 一键起服务，`/apidocs` 可访问。

---

## 四、协作接口

| 方向 | 对象 | 约定 |
| --- | --- | --- |
| 下游 | B/C/D | 提供 `Detector`/`Frame`，检测器 `register` 进引擎 |
| 下游 | E | 引擎产出的 `AlarmEvent` 调 `AlarmService.raise_alarm(event, frame)` |
| 下游 | F | 提供 HTTP-FLV 播放地址 |
| 依赖 | E | `AlarmEvent` 结构（A 只透传，不定义） |
