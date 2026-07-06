# E 任务书 — 告警中心 + 钉钉逐级闭环（模块四主体，加分项）

> 角色定位：告警枢纽。**第一天**牵头冻结「统一告警事件结构」，B/C/D 触发告警都往此结构塞，F 据此渲染。
> 关联设计：系统设计说明书 §7、§10.2。
> 涉及文件：`backend/app/services/alarm.py`、`backend/app/services/dingtalk.py`、`backend/app/api/ws.py`、`backend/app/api/alarms.py`、`backend/app/detectors/base.py`(与 A 共同定 AlarmEvent)。
> 依赖：A 抓拍帧、C 的 FaceMatcher、D 的 alarm_event/notification_log 表。

---

## 一、任务拆解

### 任务 E1：统一告警事件结构（第一天，最高优先级）
在 `detectors/base.py` 旁定义（与 A 协作），B/C/D/F 共用：

```python
@dataclass
class AlarmEvent:
    type: str          # intrusion | fire_smoke | occupy | fatigue
    region_id: int
    camera_id: int
    ts: float
    level: int = 1     # 0=弱提醒(疲劳,私有) 1=普通 2+=升级后
    snapshot_url: str = ""   # 由告警服务回填
    face_match: str = ""     # 由告警服务回填
    extra: dict = None       # 各检测器附加信息
```
- **交付即广播**：B/C/D 按此产出，F 按此渲染。之后不得随意改字段。

### 任务 E2：告警服务（抓拍 + 去重 + 状态机，§7.1/§7.2/§10.2）
完善 `services/alarm.py` 的 `raise_alarm(event, frame)`：
1. **去重**：`(region_id, type)` 冷却窗口（默认 30s）内合并，`_dedup` 已有骨架。
2. **抓拍**：当前帧存 `snapshots/`，回填 `snapshot_url`。
3. **人脸**（仅 intrusion/occupy）：裁剪面部 → 调 C 的 `FaceMatcher.match()` → 回填 `face_match`。
4. **落库**：写 `alarm_event` 表（status=pending）。
5. **分发**：level=0(疲劳弱提醒) 只推私有端；level≥1 推大屏 WebSocket + 触发钉钉。

### 任务 E3：WebSocket 看板推送（§7.3）
- `api/ws.py` 用 flask-sock 实现 `/ws/alarms`，在 `create_app` 初始化 `Sock(app)`。
- 维护订阅连接列表，`raise_alarm` 分发时向所有连接 `send` 告警 JSON。
- 前端 F 据此把对应格子绿→红闪 + 蜂鸣。约定推送 JSON = `AlarmEvent` 序列化 + `id`。

### 任务 E4：钉钉逐级上报（§7.4）
完善 `services/dingtalk.py`：
- `notify(alarm_id, ...)`：发 ActionCard 卡片给主责安全员，卡片含抓拍图、类型、位置、时间、「确认处理」按钮（`singleURL` 指向确认页/接口）。
- 启动 `threading.Timer(ESCALATE_TIMEOUT=180)` 升级计时（骨架已有）。
- `confirm(alarm_id)`：收到确认回调 → `timer.cancel()`，`alarm_event.status=confirmed`。
- `_escalate`：超时未确认 → `level+1`，`status=escalated`，推送科长/负责人（第二 webhook 或 @负责人）。
- 每次发送写 `notification_log`（stage=primary/escalated）。

### 任务 E5：确认回调接口
完善 `api/alarms.py`：
- `POST /api/alarms/{id}/confirm` → 调 `DingTalkNotifier.confirm(id)`。
- `GET /api/alarms?status=` → 从 D 的表查列表供大屏。

---

## 二、交付物清单

| 编号 | 交付物 | 文件 | 截止 |
| --- | --- | --- | --- |
| E1 | AlarmEvent 结构 | `detectors/base.py` | **D1** |
| E2 | 告警服务 | `services/alarm.py` | W2 |
| E3 | WebSocket 推送 | `api/ws.py` | 联调期 |
| E4 | 钉钉升级 | `services/dingtalk.py` | 联调期 |
| E5 | 确认/查询接口 | `api/alarms.py` | 联调期 |

---

## 三、验收标准（逐条可测）

- [ ] intrusion 告警瞬间抓拍落盘，`snapshot_url` 可访问，`face_match` 标注会员/陌生人。
- [ ] 同防区同类型 30s 内多次触发只产 1 条告警（去重生效）。
- [ ] 疲劳 level=0 告警**不**推大屏、不触发钉钉，仅私有端。
- [ ] 前端 WebSocket 收到告警，对应格子红闪 + 蜂鸣。
- [ ] 钉钉群收到卡片；3 分钟不点确认 → 自动收到升级卡片（`status=escalated`）。
- [ ] 3 分钟内点「确认处理」→ 不再升级，`status=confirmed`。
- [ ] `notification_log` 记录每次 primary/escalated 发送。

---

## 四、协作接口

| 方向 | 对象 | 约定 |
| --- | --- | --- |
| 上游 | A | 抓拍帧、`raise_alarm(event, frame)` 入口 |
| 依赖 | B/C/D | 遵循 `AlarmEvent` 产出告警 |
| 依赖 | C | `FaceMatcher.match(feature)` |
| 依赖 | D | `alarm_event`、`notification_log` 表 |
| 下游 | F | WebSocket 推送 JSON、确认接口 |
| 外部 | 钉钉 | 群机器人 Webhook（密钥走 `.env`） |
