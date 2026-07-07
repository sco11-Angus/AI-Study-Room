# D 任务书 — 音视频融合语义判断打架（新模块）

> 角色定位：本项目的技术亮点与差异化模块。把视频画面的「剧烈肢体冲突」与音频的「尖叫/怒吼/打斗声」两条模态融合成语义判断，实现"看到 + 听到"双重确认的打架检测，显著降低单模态误报。
> 关联设计：系统设计说明书 §3（跳帧/音轨）、§7（告警闭环）；PRD「安全防范闭环——深夜突发人身安全」。
> 涉及文件：`backend/app/detectors/fight.py`(新建)、`backend/app/stream/audio.py`(新建，与 A 协作)、`backend/app/config.py`。
> 依赖：A1 Detector 接口、A 的音轨抽取支持（见 D1）、B 的人员检测框（复用）、C 的 alarm_event 表、E 的 AlarmEvent 结构。

---

## 一、模块目标

自习室/公共区域内两人及以上发生肢体冲突（推搡、挥拳、拉扯）时，系统在数秒内产出 `type="fight"` 告警并走闭环上报。核心是**音视频融合**：单看画面易把嬉闹/大动作误判，单听声音易把喧哗/关门误判，两者语义一致才确认。

```
视觉侧(D2): 剧烈冲突动作           音频侧(D3): 尖叫/怒吼/打斗声
     │  近距离多人 + 高速肢体运动         │  高能量突发 + 特定声学特征
     └──────────────┬───────────────────┘
                    AND (时间对齐 ±2s, 同 camera)
                     ▼
          语义融合(D4): 双模置信度加权 > 阈值
                     ▼
          产出 AlarmEvent(type="fight", level=2 高优先)
```

---

## 二、任务拆解

### 任务 D1：音轨抽取管线（与 A 协作）
新建 `backend/app/stream/audio.py`：
- 从同一路 RTMP/FLV 流解出 AAC 音轨（`ffmpeg` 子进程或 `av`/`ffmpeg-python`），重采样 16kHz 单声道 PCM。
- 分帧：帧长 25ms、帧移 10ms，聚合成 **1s 分析窗口**（与视频跳帧解耦，音频独立累积）。
- 输出 `AudioChunk{camera_id, ts, pcm, sample_rate}` 投递给打架检测器。
- **与 A 边界**：A 给音轨字节流/解码句柄，D 做分帧与特征；不得另起解码进程（复用 A 的进程/线程约束）。
- 注意：本机若未装 ffmpeg 需先安装（见验收备注）。

### 任务 D2：视觉侧——剧烈冲突动作识别
新建 `backend/app/detectors/fight.py` 视觉部分：
- **复用 B 的人员检测框**（不重复加载 YOLO；从引擎共享上下文取本帧人员框）。
- 冲突信号（任选/组合，MVP 先做前两项）：
  1. **近距离聚集**：≥2 人检测框 IoU/中心距小于阈值（贴身）。
  2. **高速肢体运动**：相邻推理帧间人员框/关键点位移速度突增（光流或框位移 → 运动能量）。
  3. **姿态增强（加分）**：接轻量姿态估计（YOLOv8-pose/MediaPipe），检测挥拳/踢腿等剧烈姿态。
- 输出视觉冲突置信度 `vis_score ∈ [0,1]` + 涉事人员框。

### 任务 D3：音频侧——打斗声识别
`fight.py` 音频部分：
- 基础特征：每窗口 RMS/dBFS 能量、过零率、谱质心；**高能量突发**（能量骤升且持续）为一级信号。
- 语义增强（加分）：轻量音频分类模型（YAMNet/PANNs 或 log-mel + 小 CNN）识别 `尖叫/shout/怒吼/glass break/打斗` 类别。
- 输出音频打斗置信度 `aud_score ∈ [0,1]`。

<!-- APPEND-D -->
### 任务 D4：音视频语义融合 + 时空防抖
- **时间对齐**：音频窗口 `ts` 与最近视频推理结果按 `camera_id` + 时间戳（容差 ±2s）配对。
- **融合判定**：加权分数 `fuse = w_v * vis_score + w_a * aud_score`（默认 `w_v=0.6, w_a=0.4`）。
  - `fuse > FIGHT_FUSE_THRESH`(默认 0.6) 且**视觉、音频均非零**（双模都要有信号，避免单模拉满误触发）→ 冲突候选。
- **持续性防抖**：候选需**持续 ≥ `FIGHT_DURATION`(默认 3s)** 才确认为打架，滤掉击掌/嬉闹瞬时动作。
- **分级**：打架属人身安全事件，`level=2`（高优先，进大屏红闪 + 钉钉，可考虑直接升级）。

### 任务 D5：封装 Detector 插件
```python
class FightPlugin(Detector):
    name = "fight"
    def setup(self):     # 加载姿态/音频模型；订阅音频窗口
        ...
    def detect(self, frame):   # 视觉分 + 融合最近音频分 -> 防抖 -> 产出 AlarmEvent(type="fight")
        ...
```
- 产出 `AlarmEvent(type="fight", level=2)`，`extra` 带：`vis_score`/`aud_score`/`fuse`/持续时长/涉事人员框/摄像头。
- **禁止自建线程池**，注册进 A 的引擎；音频窗口驱动与视频帧驱动的协调在插件内做（引擎共享上下文）。

### 任务 D6：参数入 Config
在 `backend/app/config.py` 增：`FIGHT_FUSE_THRESH`(0.6)、`FIGHT_W_VIS`(0.6)、`FIGHT_W_AUD`(0.4)、`FIGHT_DURATION`(3)、`AUDIO_WINDOW`(1.0s)、`AUDIO_SR`(16000)。

---

## 三、交付物清单

| 编号 | 交付物 | 文件 | 截止 |
| --- | --- | --- | --- |
| D1 | 音轨抽取管线（与 A 协作） | `stream/audio.py` | W2 |
| D2 | 视觉冲突识别 | `detectors/fight.py` | W2 |
| D3 | 音频打斗识别 | `detectors/fight.py` | W2 |
| D4 | 语义融合 + 防抖 | `detectors/fight.py` | W3 |
| D5 | 打架插件 | `detectors/fight.py` | W3（联调） |
| D6 | 配置参数 | `config.py` | W2 |

---

## 四、验收标准（逐条可测）

- [ ] 音轨能从 RTMP/FLV 正常解出并重采样为 16kHz 单声道。
- [ ] 播放"两人打斗"测试视频（有画面有声音）→ 数秒内产出 1 条 `type="fight"` 告警，`level=2`。
- [ ] **仅画面剧烈动作但无打斗声**（如快速运动的运动视频）→ 不告警（双模 AND 生效）。
- [ ] **仅大声喧哗但画面无肢体冲突** → 不告警。
- [ ] 短暂击掌/拥抱（<`FIGHT_DURATION`）不告警（持续性防抖）。
- [ ] 告警 `extra` 含 `vis_score`/`aud_score`/`fuse`/涉事人员框。
- [ ] 打架告警在大屏红闪 + 触发钉钉（走 E 的闭环）。

> 验收备注：本机需安装 `ffmpeg` 才能解音轨（`ffmpeg -version` 可用）。若暂缺测试视频，可先用带音轨的样例视频 + 白噪声/尖叫音效合成验证。

---

## 五、协作接口

| 方向 | 对象 | 约定 |
| --- | --- | --- |
| 依赖 | A | `Detector`/`Frame`、**音轨字节流/解码句柄（D1）**、引擎共享上下文取人员框 |
| 依赖 | B | 复用人员检测框（不重复加载 YOLO） |
| 依赖 | C | `alarm_event` 表落库、DB 会话 |
| 依赖 | E | `AlarmEvent` 结构（新增 `type="fight"`、`extra` 字段） |
| 下游 | E | 产出 fight 告警走抓拍 + 大屏 + 钉钉闭环 |
| 下游 | F | 大屏展示打架告警（高优先红闪） |

> 关键跨人约定：
> 1. D1 音轨来源必须与 A 当面定死（A 给字节流 or D 直接读同一 RTMP 音轨），避免重复解码浪费算力。
> 2. D2 复用 B 的人员框，需与 A 约定引擎如何把 B 的检测结果暴露给 D（共享上下文/结果缓存）。
> 3. `type="fight"` 需 E 在 `AlarmEvent` 与 `alarm_event.type` 枚举中登记（数据库设计已加）。

