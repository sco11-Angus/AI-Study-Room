# G 任务书 — 违规抓拍回放与视频取证（告警中心增强）

> 角色定位：告警中心（E）的取证增强。在原有「单张抓拍图」基础上，增加**违规视频片段录制 + 回放**能力：检测到违规后，除了告警文字（如何违规），把违规发生前后的**视频片段**（含音频）一并保存并推送，供安全员在告警中心回放取证。
> 关联设计：系统设计说明书 §7（告警中心）、§3.3（低延迟环形缓冲）、任务书 A（流媒体/环形缓冲）、任务书 D（音视频打架）、任务书 E（告警闭环）、任务书 F（前端）。
> 涉及文件（预估）：`backend/app/stream/scheduler.py`、`backend/app/services/clip_recorder.py`(新)、`backend/app/services/alarm.py`、`backend/app/api/alarms.py`、`backend/app/models/entities.py`、`init.sql`、`frontend/src/components/AlarmPanel.vue`。

---

## 〇、需求澄清（先对齐概念，避免理解偏差）

你们的原始需求有两层，务必分开：

1. **告警文字**：「警告用户如何违规」——这是**结构化描述**，不是视频。已有 `AlarmEvent.type` + `extra`（如打架的 `vis_score/aud_score/fuse`）。本任务只需把这些字段**翻译成人话**（见 G4）。
2. **违规视频记录**：「凡是违规的视频片段都会被记录下来」——这是**新增的核心工作**。要点：
   - 违规是**瞬时检测**（某一帧/某个窗口触发），但视频片段需要**违规前 N 秒 + 后 M 秒**，所以必须**提前缓存历史帧**，不能等检测到了再开始录（那样只有「之后」没有「之前」）。
   - "综合音视频判断"指的是：**打架（D）**这类告警的视频片段要**带音频**（因为判断依据里有声音）；其余纯视觉告警（入侵/烟火/疲劳）可只存视频或视频+静音。

> ⚠️ 关键技术约束：违规视频片段的「前 N 秒」要求系统**始终在后台缓存最近若干秒的帧**。这是整个功能的技术核心，三个方案的主要区别就在**这段缓存怎么存、片段怎么合成**。

---

## 一、现状盘点（基于现有代码）

| 已有能力 | 位置 | 可复用点 |
| --- | --- | --- |
| 环形帧缓冲 `ring_buffer`（deque maxlen=5，存 JPEG bytes） | `stream/scheduler.py:48` | 已有「近 5 帧」缓存，但太短（约 0.2s），需扩容或另建缓冲 |
| 单帧抓拍落盘 `_save_snapshot()` | `services/alarm.py:120` | 片段录制与它并列，复用 `SNAPSHOT_DIR` 存储约定 |
| 告警落库 `alarm_event` 表 | `models/entities.py:51` | 需新增 `clip_url` 字段存片段路径 |
| 告警闭环 `raise_alarm(event, frame)` | `services/alarm.py:44` | 片段录制在此触发（抓拍图之后） |
| 音频源 `FfmpegAudioSource` / `AudioWindower` | `stream/audio.py` | 打架片段合成音轨时复用 |
| 前端告警面板 | `frontend/src/components/AlarmPanel.vue` | 加「回放」按钮 + `<video>` 弹窗 |
| 静态文件访问 `/api/alarms/snapshots/<file>` | `api/alarms.py` | 仿照它加 `/api/alarms/clips/<file>` |

**结论**：抓拍图链路已完整，本任务是「把单帧扩展成片段」。最大的新增点是**预录缓冲（pre-event buffer）**——目前 `ring_buffer` 只有 5 帧，远不够「违规前 5~10 秒」。

---

## 二、三个技术方案（重点：链路 + 优缺点）

### 方案 A：JPEG 环形缓冲 + 事后合成 MP4（推荐，纯 Python，改动最小）

**链路**：
```
scheduler 解码循环
  └─ 每帧编码 JPEG → 写入「预录环形缓冲」PreBuffer(deque, 存最近 PRE_SECONDS×fps 帧, 带时间戳)
      （与现有 ring_buffer 并列，只是 maxlen 放大到 ~150~300 帧）

检测器产出 AlarmEvent
  └─ raise_alarm() 抓拍图之后，调 ClipRecorder.record(camera_id, event)
       ├─ 1) 从 PreBuffer 复制「触发前 PRE_SECONDS 秒」的帧（快照，避免边写边读）
       ├─ 2) 再继续从 scheduler 收「触发后 POST_SECONDS 秒」的帧（后台线程，不阻塞告警主流程）
       ├─ 3) 用 cv2.VideoWriter 或 ffmpeg 把这批 JPEG 合成 MP4
       ├─ 4)（打架等）用 ffmpeg 把同时间段音频 mux 进 MP4
       └─ 5) 写文件到 CLIP_DIR，回填 alarm_event.clip_url
```

**优点**：
- 复用现有 `ring_buffer` 的解码帧，**不额外拉一路流**，CPU/带宽开销小。
- 纯 Python + OpenCV/ffmpeg，无新中间件，部署简单（Docker 已有 ffmpeg）。
- 「前 N 秒」天然支持（预录缓冲一直在填）。
- 合成在后台线程，不阻塞 `raise_alarm` 告警主流程。

**缺点**：
- 内存占用：预录缓冲要常驻。粗算 640×360 JPEG 约 20~40KB/帧，10秒×25fps×2KB… 实际 ~250帧×30KB≈7.5MB/路，多路要乘。可接受。
- MP4 合成有 CPU 峰值（一次告警一次编码），高并发告警时需限流（已有 30s 去重天然缓解）。
- 音视频对齐靠时间戳，精度取决于音频缓冲同步（打架片段需仔细调）。

---

### 方案 B：ffmpeg 常驻分段录制（segment）+ 事后裁剪（工业级，最省 CPU）

**链路**：
```
每路摄像头额外起一个常驻 ffmpeg 进程：
  ffmpeg -i rtmp://.../live/test -c copy -f segment -segment_time 2 seg_%Y%m%d_%H%M%S.ts
  （不重新编码，-c copy 直接切成 2 秒 .ts 分片，滚动保留最近 N 分钟）

检测器产出 AlarmEvent（带 ts）
  └─ raise_alarm() → ClipRecorder.record()
       ├─ 根据 ts 定位覆盖 [ts-PRE, ts+POST] 的那几个 .ts 分片
       ├─ 用 ffmpeg concat + 精确裁剪合成 MP4（含原始音轨）
       └─ 回填 clip_url
```

**优点**：
- `-c copy` 不重新编码，**CPU 开销极低**，画质无损，原生带音频。
- 分段文件天然是「滚动录像」，除了告警片段，还能支持「任意时刻回放」（扩展性最好）。
- 音视频对齐由 ffmpeg 保证，最准。

**缺点**：
- 每路多一个常驻 ffmpeg 进程，**进程管理复杂**（崩溃重启、磁盘清理、与 scheduler 拉流是两条独立连接 = 双倍拉流带宽）。
- 需要「等 POST 秒的分片落盘」才能裁剪，有延迟（≈POST+segment_time）。
- 磁盘占用大（滚动全量录像），要写清理策略。
- 与现有「从 ring_buffer 取帧」架构并行，属于**新增子系统**，联调面更大。

---

### 方案 C：前端 MediaRecorder 录制（最轻后端，但取证性弱）

**链路**：
```
前端已通过 WebSocket 收 JPEG 帧渲染到 canvas
  └─ 前端维护一个「近 N 秒帧」的 JS 缓冲
检测到告警（WebSocket 推来 AlarmEvent）
  └─ 前端用 MediaRecorder/canvas.captureStream 把缓冲帧导出 webm
      → 上传到 /api/alarms/{id}/clip 存盘
```

**优点**：
- 后端几乎零改动，最快出 demo。

**缺点**（**取证场景基本否决**）：
- 依赖前端在线且正在观看该摄像头——**没人看就没录像**，违反「凡是违规都记录」。
- 无音频（canvas 无声）、画质受前端渲染影响、可被篡改，**不具备取证效力**。
- 只作为"锦上添花的客户端预览"，不能作为主方案。

---

## 三、方案对比与推荐

| 维度 | A：JPEG缓冲+合成 | B：ffmpeg分段 | C：前端录制 |
| --- | --- | --- | --- |
| 后端改动量 | 中 | 大 | 极小 |
| CPU 开销 | 中（合成时峰值） | 低（copy不转码） | 无 |
| 内存/磁盘 | 内存中等/磁盘小 | 内存小/磁盘大 | 无 |
| 「前N秒」支持 | ✅ 天然 | ✅ 天然 | ⚠️ 依赖前端缓冲 |
| 音视频对齐 | 需手工调 | ✅ 最准 | ❌ 无音频 |
| 取证可靠性 | ✅ 高 | ✅ 最高 | ❌ 低 |
| 部署复杂度 | 低 | 高（多进程） | 低 |
| 扩展性（全量回放） | 弱 | ✅ 强 | 弱 |

**推荐：方案 A 作为一期落地**（改动小、复用现有帧缓冲、满足取证需求），**方案 B 作为二期演进**（若后续要「任意时刻回放」或对 CPU 敏感）。C 只做可选的前端即时预览。

---

## 四、任务拆解（按方案 A）

### G1：预录环形缓冲（PreBuffer）
- 在 `stream/scheduler.py` 的 `CameraStream` 增加 `pre_buffer: deque(maxlen=PRE_SECONDS×fps)`，元素 = `(ts, jpg_bytes)`。
- 解码循环 `_decode_loop` 每帧在写 `ring_buffer` 的同时写 `pre_buffer`。
- 新增 config：`CLIP_PRE_SECONDS=5`、`CLIP_POST_SECONDS=5`、`CLIP_FPS=15`、`CLIP_DIR`。

### G2：片段录制服务 `services/clip_recorder.py`（新文件）
- `ClipRecorder.record(camera_id, alarm_id, event) -> str(clip_url)`：
  1. 快照 pre_buffer 中 `[ts-PRE, ts]` 的帧。
  2. 起后台线程续收 `[ts, ts+POST]` 的帧（订阅 scheduler 新帧事件 `wait_frame`）。
  3. `cv2.VideoWriter` 合成 MP4（H.264，CLIP_FPS）。
  4. 打架等 `type=fight`：用 ffmpeg 把对应时段音轨 mux 进去。
  5. 落盘 `CLIP_DIR`，返回 `/api/alarms/clips/<file>`。
- **必须异步**：不阻塞 `raise_alarm`；片段生成完再更新 `alarm_event.clip_url`。

### G3：告警服务接入 + 数据模型
- `models/entities.py` 的 `AlarmEvent` 增加 `clip_url = Column(String(256))`；`init.sql` 同步加列。
- `services/alarm.py` 的 `raise_alarm()` 在 `_save_snapshot` 之后触发 `ClipRecorder.record()`（异步），先返回告警（clip_url 待回填），片段就绪后二次广播/更新。
- `api/alarms.py` 加 `GET /api/alarms/clips/<filename>` 静态访问（仿 snapshots），支持 HTTP Range 以便前端拖动进度条。

### G4：告警文字（如何违规）— 结构化描述生成
- 新增 `describe_alarm(event) -> str`：把 `type + extra` 翻译成人话。示例：
  - `fight`：「检测到肢体冲突：视觉冲突分 {vis_score}，音频冲突分 {aud_score}，融合分 {fuse} 超过阈值」
  - `intrusion`：「{face_match} 闯入危险区域 {region_name}」
  - `fire_smoke`：「检测到烟火，置信度 {confidence}」
- 写进告警 JSON 的 `message` 字段 + 钉钉卡片正文。

### G5：前端回放
- `AlarmPanel.vue` 每条告警加「回放」按钮（有 `clip_url` 时显示）。
- 点击弹出 `<video controls>` 播放 `clip_url`；文字区显示 G4 的 `message`。
- clip 未就绪时显示「视频生成中…」，通过 WebSocket 二次推送或轮询刷新。

---

## 五、与所有任务的关系（依赖矩阵）

```
        A(帧+音轨+环形缓冲)
         │  提供解码帧 & 音频源
         ▼
   ┌────────────── G 违规抓拍回放 ──────────────┐
   │  G1 预录缓冲(扩A的ring_buffer)               │
   │  G2 片段录制(复用A帧 + D音频 + ffmpeg)        │
   │  G3 接入E告警闭环(扩alarm_event表 by C)       │
   │  G4 告警文字(读B/C/D的extra字段)              │
   │  G5 前端回放(扩F的AlarmPanel)                 │
   └───────────────────────────────────────────┘
         ▲         ▲          ▲          ▲
         │         │          │          │
   B入侵/疲劳   C数据层     D打架       F前端
  (extra:人员框) (加clip_url列)(音视频extra) (video回放UI)
```

| 任务 | G 与它的关系 | G 需要对方做什么 / G 给对方什么 |
| --- | --- | --- |
| **A 流媒体** | **强依赖（地基）** | 需要 A 的 `scheduler.ring_buffer` 解码帧；G1 在其上扩预录缓冲。若 A 的帧率/分辨率变，G 的片段参数要跟。 |
| **B 入侵/疲劳/人脸** | 弱依赖 | G4 读 B 告警的 `face_match`、人员框生成文字；B 无需改代码，只要 `extra` 字段齐。 |
| **C 数据层/接口** | **中依赖（改表）** | G3 需要 C 在 `alarm_event` 表加 `clip_url` 列并更新 `init.sql`/接口返回结构。**必须与 C 协调 schema 变更**。 |
| **D 音视频打架** | **强依赖（音频）** | 打架片段要带音频，G2 复用 D 依赖的 A 音轨；D 的 `extra`(vis/aud/fuse) 供 G4 生成文字。「综合音视频判断」主要体现在此。 |
| **E 告警中心** | **本体（G 是 E 的增强）** | G2/G3 挂在 E 的 `raise_alarm` 闭环内；不破坏 E1 的 `AlarmEvent` 契约（clip_url 走回填，同 snapshot_url 模式）。 |
| **F 前端** | **中依赖（UI）** | G5 扩 F 的 `AlarmPanel` 加回放弹窗；F 需支持 `<video>` + Range 请求。 |

**关键协调点（否则返工）**：
1. **与 C**：`alarm_event` 加 `clip_url` 列——schema 变更要 C 点头并同步 `init.sql`。
2. **与 A**：预录缓冲扩大 `ring_buffer`/`pre_buffer`，需确认 A 的解码帧率、内存预算。
3. **与 D**：打架片段音视频对齐，需 D 明确音频窗口时间戳与视频帧时间戳的对齐方式。
4. **不破坏 E1 契约**：`clip_url` 用「告警服务回填」模式（同 `snapshot_url`），检测器 B/C/D **不用改**产出结构。

---

## 六、验收标准（逐条可测）

- [ ] 任一违规告警产生后，`CLIP_DIR` 生成对应 MP4，`alarm_event.clip_url` 可访问。
- [ ] 片段包含违规发生**前 CLIP_PRE_SECONDS 秒**的画面（验证预录缓冲生效）。
- [ ] 打架（fight）片段**带音频**，且音画基本同步。
- [ ] 片段录制**不阻塞**告警主流程（`raise_alarm` 立即返回，clip_url 稍后回填）。
- [ ] 前端告警面板出现「回放」按钮，点击可播放片段并拖动进度条（HTTP Range 生效）。
- [ ] 告警文字（message）能说明「如何违规」（类型 + 关键分值/对象）。
- [ ] 30s 去重下不会为同一违规重复生成大量片段。
- [ ] 磁盘：有片段清理/上限策略（如保留 N 天或按容量滚动）。

---

## 七、风险与待决策

| 风险 | 说明 | 建议 |
| --- | --- | --- |
| 内存占用 | 多路预录缓冲常驻内存 | 限制路数或降 CLIP_FPS/分辨率 |
| CPU 峰值 | MP4 合成瞬时占 CPU | 靠 30s 去重 + 后台线程 + 可选转码限流 |
| 音视频对齐 | 打架片段音画同步 | 一期先「视频优先、音频尽力对齐」，二期上方案 B 求精确 |
| 磁盘膨胀 | 片段累积 | 定时清理任务（可挂 Jenkins 或后端定时线程） |
| 「凡是违规都记录」的强度 | 是否连 level=0 疲劳都录？ | 建议**只录 level≥1**，疲劳弱提醒不录（省资源），待与需求方确认 |

> **待你/团队确认的决策**：
> 1. 一期用方案 A 还是直接上 B？（推荐 A）
> 2. `clip_url` 加列，C 是否同意？
> 3. 疲劳 level=0 要不要也录像？（建议不录）
> 4. 片段前后各几秒（默认 5+5）、帧率（默认 15）、保留时长？
