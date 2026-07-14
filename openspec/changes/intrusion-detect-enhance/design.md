## Context

当前 `IntrusionPlugin` 的座位占用检测流程：

1. `_load_active_seats()` 查询 `SeatStatus.status == "studying"` 的记录，取 `seat_status.user_id` 作为预约人 ID。
2. `detect()` 中遍历每个 seat，对 person boxes 逐个做 `judge()`（几何 + 时间防抖），命中后调用 `_match_person()` 裁剪 person box 做人脸匹配。
3. 若 `face_match != f"member:{seat.user_id}"` 则产生 `occupy` 告警，然后 `break` 跳出该 seat 的循环。

**核心问题：** `seat_status.user_id` 指向 `app_user.id`，但人脸匹配返回 `member:{member_id}`，两个 ID 空间不同，对比逻辑无效。且 `break` 导致同座位多人时只判断第一个人。

**现有基础设施：**
- `FaceMatcher` 已有 `detect_faces(image)` 返回 dlib rectangle 列表、`encode_from_rect(image, rect)` 从指定矩形提取特征、`match(feature)` 返回 `"member:{id}"` / `"stranger"`
- `AlarmService.raise_alarm` 已支持 `level` 参数和 `extra` JSON
- `_notify_intrusion_changed()` 已在 regions API 中调用 `engine.on_config_changed("intrusion", {})` 触发热重载

## Goals / Non-Goals

**Goals:**
- 建立独立的 `seat_reservation` 表，以 `region_id` 唯一绑定 `member_id`，长期有效直到手动解绑
- 预约成员进入绑定座位不报警；其他 member 或 stranger 停留超阈值后告警
- 同一座位多人同时出现时，各自独立计时，分别判定
- 人脸识别改为整帧检测后按中心点关联到 person box，提升检出率
- 绑定/解绑后热更新，无需重启
- `seat_status` 与预约逻辑完全解耦

**Non-Goals:**
- 不引入完整 MOT（DeepSORT/ByteTrack），用轻量 IoU 做帧间 box 关联
- 不做跨摄像头追踪
- 不自动迁移历史 `seat_status` 数据为预约关系（避免把不一致的 `app_user.id` 错误绑定到 `member_id`）
- 不改变危险防区（`danger_zone`）的入侵检测逻辑
- 不改变 `seat_status` 的自习/休息/疲劳检测职责

### D6: 将实时防区状态与历史告警记录分离

**选择：** 告警首次触发仍持久化为 `AlarmEvent`；轨迹离开时不再新增或修改
历史告警，而是通过告警 WebSocket 发送瞬态 `region_state` 事件：

```json
{
  "event": "region_state",
  "state": "cleared",
  "region_id": 10,
  "camera_id": 6,
  "alarm_type": "occupy",
  "track_key": "seat-10-track-3"
}
```

前端按当前活跃 `track_key` 集合决定一个防区是否闪红；历史中未确认的
告警仅用于告警记录列表，不能重新激活红框。多人同时处于一个防区时，只在
最后一个活跃告警轨迹解除后恢复绿色。

**理由：** 人员是否仍在场是实时观测状态，人工确认是告警处置状态；将两者
混在 `alarm_event.status` 会导致离开后持续闪红，也会在确认其中一条多人告警时
错误地清除整个防区。

## Decisions

### D1: 新增 `seat_reservation` 表，以 `region_id` 唯一绑定 `member_id`

**选择：** 新建 `seat_reservation` 表，`region_id` 为唯一键，`member_id` 外键指向 `member.member_id`，含 `enabled` 字段和 `created_at` / `updated_at` 时间戳。

```sql
CREATE TABLE seat_reservation (
    id INT PRIMARY KEY AUTO_INCREMENT,
    region_id INT NOT NULL UNIQUE,
    member_id INT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    FOREIGN KEY (region_id) REFERENCES region(id) ON DELETE CASCADE,
    FOREIGN KEY (member_id) REFERENCES member(member_id) ON DELETE CASCADE
);
```

**理由：** 彻底消除 `app_user.id` 与 `member.member_id` 混用。预约关系独立于自习状态，长期有效。`region_id` 唯一约束保证一个座位只有一个预约人。

**替代方案：** 在 `Region` 表加 `reserved_member_id` 列 → 语义不够明确，且无法记录启用状态和时间。

### D2: `SeatRuntime` 持有 `member_id` 而非 `user_id`，并维护多人计时器

**选择：** `SeatRuntime` 改为：

```python
@dataclass
class SeatRuntime:
    id: int
    camera_id: int
    name: str
    member_id: int          # 预约人 member_id
    member_name: str        # 预约人姓名（缓存避免频繁查库）
    detector: IntrusionDetector
    # 多人独立计时：track_key -> {enter_ts, alarmed}
    _timers: dict[str, dict]  # track_key 由 IoU 关联生成
```

每帧对每个 seat 内的 person box：
1. 用 IoU 与上一帧的 box 匹配，生成 track_key（`f"seat{seat_id}_box{idx}"` 或基于 IoU 的稳定 key）
2. 为每个 track_key 维护独立的 `enter_ts` 和 `alarmed` 状态
3. person box 离开防区或 IoU 匹配失败（超时）时清除对应计时

**理由：** 当前单计时器无法区分同座位多人，`break` 导致漏判。多人独立计时保证每个人各自计时、各自告警。

**替代方案：** 引入 ByteTrack → 增加 ~20ms/帧延迟 + 额外依赖，收益不匹配。轻量 IoU 在单座位场景足够。

### D3: 整帧人脸检测 + 人脸中心点关联到 person box

**选择：** `detect()` 中对整帧调用 `face_matcher.detect_faces(frame.image)`，获取所有人脸 rectangle。对每个进入座位停留超阈值的 person box，找到中心点落在该 box 内的人脸 rectangle，调用 `encode_from_rect(frame.image, face_rect)` 提取特征并匹配。

```python
def _match_person_fullframe(self, image, box, face_rects):
    """整帧人脸检测后，按中心点关联到 person box。"""
    cx = (box[0] + box[2]) / 2
    cy = (box[1] + box[3]) / 2
    # 找中心点落在 person box 内的人脸
    for rect in face_rects:
        fx = (rect.left() + rect.right()) / 2
        fy = (rect.top() + rect.bottom()) / 2
        if box[0] <= fx <= box[2] and box[1] <= fy <= box[3]:
            feature = self.face_matcher.encode_from_rect(image, rect)
            if feature is not None:
                return self.face_matcher.match(feature), rect
            return "stranger", rect
    # person box 内无人脸 → stranger
    return "stranger", None
```

**理由：** 当前 `_match_person()` 裁剪 person box 后在裁剪图上做人脸检测，当 person box 较大时裁剪图分辨率足够，但 person box 较小或人脸偏移时容易漏检。整帧检测利用全分辨率，检出率更高。`encode_from_rect()` 已存在且更稳定。

**替代方案：** 保持裁剪方式但扩大裁剪区域 → 治标不治本，且裁剪后 dlib 检测可能因尺寸不足返回空。

### D4: 预约 API 路径 `/api/seat-reservations/{region_id}`，PUT 幂等

**选择：**
- `GET /api/seat-reservations?camera_id=` — 查询绑定状态，返回 `[{region_id, member_id, member_name, enabled, ...}]`
- `PUT /api/seat-reservations/{region_id}` — body `{member_id}`，upsert 语义（不存在则插入，存在则更新）
- `DELETE /api/seat-reservations/{region_id}` — 删除绑定记录
- `GET /api/members?face_enrolled=true` — 过滤 `feature IS NOT NULL AND feature != ''` 的成员

绑定/更新/解绑后调用 `_notify_intrusion_changed()` 触发 `IntrusionPlugin._reload_regions()` 热更新。

**理由：** RESTful 风格，`region_id` 作为资源标识符，PUT 幂等语义适合 upsert。

### D5: 告警 `extra` 结构标准化

**选择：** `occupy` 告警的 `extra` 固定包含：

```python
{
    "kind": "unauthorized_seat",
    "seat_name": seat.name,
    "reserved_member_id": seat.member_id,
    "reserved_member_name": seat.member_name,
    "actual_face_match": face_match,  # "member:2002" 或 "stranger"
    "person_box": [x1, y1, x2, y2],
    "track_key": track_key,
}
```

告警 `message` 字段：`"非预约人员占用座位「{seat_name}」"`

**理由：** 前端和大屏需要明确展示"谁预约了座位"和"实际是谁在坐"，当前 `expected_user_id` 字段名误导且指向 `app_user.id`。

## D7: Fast seat authorization and notification observability

Reserved-seat matching runs from the first in-seat face association. When the
expected member is recognized, the detector emits a non-persistent
`region_state: allowed` message with member and seat names. The dashboard clears
only that track and briefly welcomes the reserved member. Unknown or mismatched
occupants still require a short configurable observation debounce before an
`occupy` record is persisted.

Inference-miss expiry is configurable so a deployment can restore green state
quickly. DingTalk notifier startup logs whether the webhook is configured;
without a webhook address, no code path can deliver a group message.

## Risks / Trade-offs

| 风险 | 缓解 |
|------|------|
| IoU 关联在快速移动或遮挡时可能断裂 | 设超时清理（如 3 帧无匹配则清除计时），断裂后重新计时不影响告警准确性 |
| 整帧人脸检测增加每帧开销（~5-10ms） | 仅在座位有 person box 停留超阈值时触发，非每帧都跑 |
| `member_name` 缓存可能在 member 更名后过期 | 热更新时重新加载，可接受短暂不一致 |
| 历史数据不迁移 | 设计决策：不迁移，避免错误绑定；管理员手动绑定 |
| SQLite 测试环境与 MySQL 生产差异 | 保留 SQLite 回归测试方式，SQL 语法保持两者兼容 |
