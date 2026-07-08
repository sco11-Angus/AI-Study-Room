# Task A 与人脸识别功能设计说明

## 1. 功能概述

本文档面向当前仓库实现，梳理两块核心能力：

- Task A：流媒体接入、跳帧调度、统一推理引擎、告警闭环入口。
- 人脸识别：Dlib 128 维特征提取与会员库最近邻匹配，用于告警抓拍后的身份确认。

对应代码主路径：

- `backend/app/stream/scheduler.py`：拉流、环形缓冲、跳帧提交推理。
- `backend/app/stream/engine.py`：检测器注册/启停、统一线程池调度、告警透传。
- `backend/app/detectors/base.py`：`Frame`、`Detector`、`AlarmEvent` 统一接口。
- `backend/app/detectors/face.py`：`FaceMatcher.encode/match`。
- `backend/app/services/alarm.py`：告警去重、抓拍/推送闭环（当前含骨架注释）。

## 2. 功能流程图（Flowchart）

### 图说明

该图仅覆盖 Task A（A1-A4）与人脸识别能力，不展开 Task B 的入侵/疲劳业务细节。阅读时按 5 个功能点理解：

- A4 流媒体：Nginx-RTMP 接收并分发视频流（RTMP/HTTP-FLV）。
- A3 拉流调度：后端从流媒体服务拉取视频帧，维护低延迟缓冲并断流重连。
- A2 统一推理引擎：按采样帧调用已注册检测器，统一算力入口。
- A1 插件接口：所有检测器统一实现 Frame/Detector 协议。
- 人脸识别：仅在告警闭环阶段调用 FaceMatcher 识别会员/陌生人。

图介绍：

该流程图只说明系统每一步具体做什么：视频流先被接入，再被后端拉取、抽帧、检测、告警、抓拍、识别，最后把结果推送出去。每个节点都对应一次明确动作，便于直接对应代码理解。

```mermaid
flowchart TD
  A[1. 摄像头或测试视频开始推流] --> B[2. Nginx-RTMP 接收视频流]
  B --> C[3. 后端按 RTMP 地址拉取视频帧]
  C --> D[4. 把最新帧放入环形缓冲，供页面实时显示]
  D --> E{5. 当前帧是否满足 SKIP_N 采样条件}
  E -- 否 --> F[6. 直接继续读取下一帧，不做推理]
  F --> C
  E -- 是 --> G[6. 把当前帧封装成 Frame 对象]

  G --> H[7. 提交给统一推理引擎异步处理]
  H --> I[8. 在线程池中按顺序调用检测器]
  I --> J{9. 检测器是否返回告警事件}
  J -- 否 --> C
  J -- 是 --> K[10. 把告警交给 AlarmService 处理]

  K --> L{11. 是否通过冷却窗口去重}
  L -- 否 --> M[12. 丢弃重复告警，不继续处理]
  L -- 是 --> N[12. 对触发帧进行抓拍，并裁剪人脸区域]

  N --> O[13. 将人脸图像送入 FaceMatcher 提取特征]
  O --> P[14. 在 member 特征库中查找最近邻]
  P --> Q{15. 距离是否小于 0.6}
  Q -- 是 --> R[16. 识别为 member:id]
  Q -- 否 --> S[16. 识别为 stranger]

  R --> T[17. 记录告警结果并推送到看板/通知端]
  S --> T
  T --> C
```

## 3. 类图（Class Diagram）

### 图说明

该图用于说明模块职责边界。阅读顺序建议：

1. 先看数据对象：`Frame`、`AlarmEvent`。
2. 再看推理核心：`InferenceEngine` 与 `Detector` 抽象。
3. 最后看告警扩展链路：`AlarmService -> FaceMatcher -> Member`。

图介绍：

该类图用于展示模块职责与对象关系。`StreamScheduler` 负责视频帧获取与采样调度，`InferenceEngine` 负责检测器的统一注册与调用，`Detector` 通过统一接口产出 `AlarmEvent`。`AlarmService` 在告警侧负责去重与闭环触发，`FaceMatcher` 提供人脸编码与匹配能力，并面向 `Member` 特征库完成身份判定。图中的基数标识明确了一对一与一对多关系，便于理解系统扩展方式。

```mermaid
classDiagram
    class Frame {
      +image: np.ndarray
      +ts: float
      +camera_id: int
      +frame_idx: int
    }

    class AlarmEvent {
      +region_id: int
      +type: str
      +confidence: float
      +snapshot: np.ndarray
      +face_crop: np.ndarray
      +extra: dict
    }

    class Detector {
      <<abstract>>
      +name: str
      +enabled: bool
      +setup()
      +detect(frame: Frame) list~AlarmEvent~
      +on_config_changed(cfg)
    }

    class InferenceEngine {
      -_detectors: dict
      -_pool: ThreadPoolExecutor
      +register(detector: Detector)
      +unregister(name: str)
      +set_enabled(name: str, enabled: bool)
      +setup_all()
      +dispatch(frame: Frame) list~AlarmEvent~
      +dispatch_async(frame: Frame)
      +on_config_changed(name: str, cfg: dict)
      +shutdown()
    }

    class StreamScheduler {
      -_engine: InferenceEngine
      -_cameras: dict~int, CameraStream~
      +add_camera(camera_id: int, stream_name: str)
      +remove_camera(camera_id: int)
      +start_all()
      +stop_all()
      +status: dict~int,bool~
    }

    class CameraStream {
      +camera_id: int
      +stream_name: str
      +stream_url: str
      +ring_buffer: deque
      +online: bool
      +latest_frame()
    }

    class FaceMatcher {
      -threshold: float
      -_detector
      -_shape_predictor
      -_face_encoder
      +encode(face_img) np.ndarray
      +match(feature) str
    }

    class AlarmService {
      +cooldown: int
      -_last_fired: dict
      +raise_alarm(region_id: int, type_: str, frame)
    }

    class Member {
      +member_id: int
      +name: str
      +feature: Text
    }

    Detector <|.. IntrusionPlugin
    Detector <|.. FatiguePlugin
    Detector <|.. FireSmokePlugin

    StreamScheduler "1" --> "1" InferenceEngine : dispatch_async(Frame)
    StreamScheduler "1" *-- "0..*" CameraStream : 管理
    InferenceEngine "1" --> "0..*" Detector : 注册/调度
    Detector "1" --> "0..*" AlarmEvent : 产出
    InferenceEngine "1" --> "1" AlarmService : raise_alarm()
    AlarmService "1" --> "1" FaceMatcher : encode/match
    FaceMatcher "1" --> "0..*" Member : 查询特征库
```

## 4. 时序图（Sequence Diagram）

### 图说明

该图与第 2 节保持同一口径，仅展示 Task A（A1-A4）与人脸识别闭环。关键点：

- 视频流先经过流媒体服务，再由调度器拉取并按 SKIP_N 采样。
- 统一引擎异步调度检测器，保障解码线程连续输出画面。
- 仅当有告警且通过去重时，才进入人脸特征提取与会员匹配。

图介绍：

该时序图强调运行阶段的先后约束与调用边界。视频流由流媒体服务转发给调度器后，系统按帧循环执行“读取-采样-调度”流程；采样帧通过异步方式进入统一推理引擎，避免阻塞视频读取。仅当告警事件出现且通过去重校验后，系统才进入人脸识别链路，执行特征提取、特征库匹配和结果推送。该图用于说明系统在实时性与识别准确性之间的执行策略。

```mermaid
sequenceDiagram
    autonumber
  participant Src as 视频源(摄像头/测试视频)
  participant Nginx as Nginx-RTMP(A4)
    participant Sch as StreamScheduler
    participant Eng as InferenceEngine
    participant Pool as 线程池Worker
  participant Det as Detector(A1插件)
    participant Alarm as AlarmService
    participant Face as FaceMatcher
  participant DB as Member特征库
  participant Board as 看板/通知端

  Src->>Nginx: 推送RTMP视频流
  Nginx->>Sch: 提供RTMP拉流地址
    loop 每帧
    Sch->>Sch: 读取视频帧并写入环形缓冲
        alt 命中跳帧条件 SKIP_N
            Sch->>Eng: dispatch_async(Frame)
            Eng->>Pool: submit(_dispatch_and_raise)
            Pool->>Eng: dispatch(Frame)
            Eng->>Det: detect(frame)
            Det-->>Eng: [AlarmEvent...]
            alt 有告警事件
                Eng->>Alarm: raise_alarm(region_id, type, frame)
                Alarm->>Alarm: 冷却去重
                alt 通过去重
          Alarm->>Face: encode(face_crop or frame)
          Face->>DB: 查询 member 特征向量
                    DB-->>Face: 特征集合
                    Face-->>Alarm: member:id / stranger
          Alarm-->>Board: 推送告警与识别结果
                else 被去重
                    Alarm-->>Eng: 忽略本次
                end
            else 无告警
                Eng-->>Sch: 本帧结束
            end
        else 非推理帧
      Sch->>Sch: 仅用于实时画面输出
        end
    end
```

## 5. 功能模块总结

Task A 与人脸识别模块共同构成了“视频处理到告警闭环”的核心主链路。

- 在接入层，系统通过 Nginx-RTMP 完成视频流接入与分发，保障前后端流链路统一。
- 在调度层，`StreamScheduler` 采用环形缓冲和 `SKIP_N` 采样策略，兼顾实时显示与计算开销。
- 在推理层，`InferenceEngine` 提供统一的检测器调用入口，避免多模型并发造成资源争抢。
- 在识别层，`FaceMatcher` 仅在有效告警后执行人脸匹配，提高识别调用的有效性。
- 在闭环层，`AlarmService` 负责告警去重与结果推送，使告警信息具备可追踪、可处置的业务价值。

整体上，该模块设计将实时视频处理、统一推理调度与身份识别能力解耦，并通过清晰的调用边界实现可扩展、可维护的工程结构。
