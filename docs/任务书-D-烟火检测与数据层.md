# D 任务书 — 烟火检测 + 数据层 + 接口框架

> 角色定位：烟火检测本身较轻，配上数据层与接口框架横向支撑。**数据表第一周必须交付**，B/C/E 都等它。
> 关联设计：系统设计说明书 §6、§8、§9、§10.3。
> 涉及文件：`backend/app/models/entities.py`、`backend/app/models/db.py`(新建)、`backend/app/detectors/fire_smoke.py`、`backend/app/__init__.py`、各 `api/*.py`。
> 依赖：A1 Detector 接口。

---

## 一、任务拆解

### 任务 D1：数据层（第一周最高优先级，全员依赖）
- 新建 `backend/app/models/db.py`：SQLAlchemy `engine` + `SessionLocal` + `init_db()` 建表。
- 校对 `models/entities.py` 6 张表与 §8.2 字段一致：`camera` / `region` / `seat_status` / `alarm_event` / `member` / `notification_log`。
- 在 `create_app()` 中初始化 DB，提供会话依赖供各 API 使用。
- 写 `seed.py`：插入 1 个测试摄像头、若干测试防区，便于他人联调。
- **交付即通知 B/C/E**：他们的落库依赖此。

### 任务 D2：接口框架统一化（§9、§10.3）
- 统一返回结构 `{code, message, data}`，封装 `ok(data)` / `err(msg, code)` 辅助函数。
- Swagger：确认 `flasgger` 在 `create_app` 正常挂载，`/apidocs` 可访问；补全各接口的 docstring 注解。
- CORS 白名单配置（前端 5173）。
- 全局异常处理器：未捕获异常统一返回 `{code:500,...}`，不泄漏堆栈。

### 任务 D3：烟火检测（模块三，§6）
- 获取火灾/烟雾 YOLO 轻量权重（类别 `fire`/`smoke`），放 `model_weights/`。
- 完善 `detectors/fire_smoke.py`：`setup()` 加载模型；`detect(frame)` 取本帧 fire/smoke 最大置信度传入 `feed()`。
- 复用 `FireSmokeDetector.feed()`（30 帧滑动窗口，均值 > `FIRE_CONF`(0.45) 判有效，勿改逻辑）。
- 封装 `FireSmokePlugin(Detector)`，`name="fire_smoke"`，命中产出 `AlarmEvent(type="fire_smoke")`。**不自建线程池**。

---

## 二、交付物清单

| 编号 | 交付物 | 文件 | 截止 |
| --- | --- | --- | --- |
| D1 | 数据表+初始化+seed | `models/db.py`、`entities.py`、`seed.py` | **W1（全员依赖）** |
| D2 | 统一返回+Swagger+CORS | `app/__init__.py`、`api/*` | W1 |
| D3 | 烟火插件 | `detectors/fire_smoke.py` | W2 |

---

## 三、验收标准（逐条可测）

- [ ] `python -c "from app.models.db import init_db; init_db()"` 建出 6 张表，结构与 §8.2 一致。
- [ ] `seed.py` 跑完有可用测试数据。
- [ ] `/apidocs` 打开，所有接口可见、可试调。
- [ ] 所有接口返回 `{code,message,data}` 格式统一。
- [ ] 连续 30 帧 fire/smoke 均值 > 45% → 告警；单帧高置信/光线瞬变不告警（可用录制的打火机视频 + 反光视频各测一次）。
- [ ] 前端跨域请求无 CORS 报错。

---

## 四、协作接口

| 方向 | 对象 | 约定 |
| --- | --- | --- |
| 依赖 | A | `Detector`/`Frame` |
| 下游 | B | `region` 表 + 会话 |
| 下游 | C | `seat_status`、`member` 表 |
| 下游 | E | `alarm_event`、`notification_log` 表；`type="fire_smoke"` 告警 |
| 下游 | F | 统一返回结构、Swagger 文档 |
