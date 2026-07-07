# C 任务书 — 烟火检测 + 数据层 + 接口框架

> 角色定位：横向支撑主力。承担模块三（烟火检测）+ 全系统数据层 + 接口框架。**数据表第一周必须交付**，B/D/E 都等它。
> 关联设计：系统设计说明书 §6、§8、§9、§10.3；数据库设计见 `../specs/数据库设计.md`。
> 涉及文件：`backend/app/models/entities.py`、`backend/app/models/db.py`(新建)、`backend/app/models/seed.py`(新建)、`backend/app/detectors/fire_smoke.py`、`backend/app/__init__.py`、各 `api/*.py`。
> 依赖：A1 Detector 接口。

---

## 一、任务拆解

### 任务 C1：数据层（第一周最高优先级，全员依赖）
- 新建 `backend/app/models/db.py`：SQLAlchemy `engine` + `SessionLocal` + `init_db()` 建表。
- 按 `../specs/数据库设计.md` 校对/补全 `models/entities.py` 的 **8 张表**：`camera` / `region` / `app_user` / `seat_status` / `alarm_event` / `member` / `guard` / `notification_log`。
  - 注意补 `app_user`、`guard` 两张表，`alarm_event` 补 `camera_id` 字段（数据库设计已列明）。
- 在 `create_app()` 中初始化 DB，提供会话依赖供各 API 使用。
- 新建 `seed.py`：插入 1 测试摄像头、若干防区、1 app_user、1 primary guard，便于联调。
- **交付即通知 B/D/E**：他们的落库依赖此。

### 任务 C2：接口框架统一化（§9、§10.3）
- 统一返回结构 `{code, message, data}`，封装 `ok(data)` / `err(msg, code)` 辅助函数。
- Swagger：确认 `flasgger` 在 `create_app` 正常挂载，`/apidocs` 可访问；补全各接口 docstring 注解。
- CORS 白名单（前端 5173）。
- 全局异常处理器：未捕获异常统一返回 `{code:500,...}`，不泄漏堆栈。

### 任务 C3：烟火检测（模块三，§6）
- 获取火灾/烟雾 YOLO 轻量权重（类别 `fire`/`smoke`），放 `model_weights/`。
- 完善 `detectors/fire_smoke.py`：`setup()` 加载模型；`detect(frame)` 取本帧 fire/smoke 最大置信度传入 `feed()`。
- 复用 `FireSmokeDetector.feed()`（30 帧滑动窗口，均值 > `FIRE_CONF`(0.45) 判有效，勿改逻辑）。
- 封装 `FireSmokePlugin(Detector)`，`name="fire_smoke"`，命中产出 `AlarmEvent(type="fire_smoke")`。**不自建线程池**。

---

## 二、交付物清单

| 编号 | 交付物 | 文件 | 截止 |
| --- | --- | --- | --- |
| C1 | 数据表(8张)+初始化+seed | `models/db.py`、`entities.py`、`seed.py` | **W1（全员依赖）** |
| C2 | 统一返回+Swagger+CORS | `app/__init__.py`、`api/*` | W1 |
| C3 | 烟火插件 | `detectors/fire_smoke.py` | W2 |

---

## 三、验收标准（逐条可测）

- [ ] `python -c "from app.models.db import init_db; init_db()"` 建出 8 张表，结构与 `../specs/数据库设计.md` 一致。
- [ ] `seed.py` 跑完有可用测试数据。
- [ ] `/apidocs` 打开，所有接口可见、可试调。
- [ ] 所有接口返回 `{code,message,data}` 格式统一。
- [ ] 连续 30 帧 fire/smoke 均值 > 45% → 告警；单帧高置信/光线瞬变不告警（打火机视频 + 反光视频各测一次）。
- [ ] 前端跨域请求无 CORS 报错。

---

## 四、协作接口

| 方向 | 对象 | 约定 |
| --- | --- | --- |
| 依赖 | A | `Detector`/`Frame` |
| 下游 | B | `region`/`seat_status`/`member` 表 + 会话 |
| 下游 | D | `alarm_event` 表（打架检测落库）、DB 会话 |
| 下游 | E | `alarm_event`、`notification_log`、`guard` 表；`type="fire_smoke"` 告警 |
| 下游 | F | 统一返回结构、Swagger 文档 |
