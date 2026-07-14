# Tasks

## 1. 人员框：YOLO 人体框无条件供给（方案B）
- [x] 1.1 修改 `backend/app/detectors/intrusion.py` `detect()`：把 YOLO 人体检测 + `shared_ctx.set(camera_id, frame_idx, people)` 提到 region/seat 早退判断（`if not regions and not seats: return []`）之前，无条件执行
- [x] 1.2 确认早退分支不再跳过人员框写入；入侵计数/告警逻辑保持不变
- [x] 1.3 确认 `run.py` 中 `FightPlugin(person_provider=SharedContextProvider(engine.shared_ctx))` 装配不变，打架读回的是 YOLO 人体框
- [x] 1.4 补充/更新单测：无防区摄像头也写 `shared_ctx`（参考 `backend/tests/test_fight_integration.py`）

## 2. RTMP 音轨端到端保障与可观测
- [x] 2.1 `backend/app/stream/scheduler.py` `_audio_loop`：启动时记录 ffmpeg 可用性、是否网络流、目标检测器（fight/abnormal）
- [x] 2.2 增加 `feed_audio` 心跳日志：周期性记录最近 `aud_score`，验证音轨持续喂入
- [x] 2.3 确认本机 ffmpeg 可用（`ffmpeg -version`）；缺失则在联调文档标注为前置条件 — 本机 ffmpeg 8.1.2 可用
- [ ] 2.4 确认 `.env` 中 RTMP 流地址含音轨；联调用带音轨的测试视频推流 — ⏳ 需实机推流验证（`STREAM_URLS` 末路 `test1` 为 RTMP，其余为无音轨 RTSP 沙盘流）

## 3. 情绪模块双开
- [x] 3.1 `.env` 设置 `EMOTION_ENABLE=true`（人脸情绪闸门 HSEmotion）
- [x] 3.2 确认 `.env` `EMOTION_ENABLED=true`（声学 SenseVoice）、`YAMNET_ENABLED=true`
- [ ] 3.3 启动后日志确认：`[fight] 打架检测器就绪` 显示 YAMNet/声学情绪/人脸情绪闸门状态 — ⏳ 需实机启动后端观察日志
- [ ] 3.4 确认情绪模型缺失时降级放行、不崩（观察日志无异常堆栈拖垮引擎）— ⏳ 需实机验证（降级逻辑已存在于代码）

## 4. 前端展示打架告警与分数
- [x] 4.1 `frontend/src/components/AlarmPanel.vue`：打架告警展示 `fuse`/`vis_score`/`aud_score`/`emo_gate` 分数 — 截图对话框内加三模态分数 chip
- [x] 4.2 `frontend/src/views/LogViewer.vue`：打架告警日志详情展示分数与 `emotion` 情绪标签 — 表格展开行显示分数+情绪
- [x] 4.3 确认 `fight`（打架告警）类型标签与筛选在前端正常 — 筛选项与类型标签已存在，前端 build 通过

## 5. 全链路联调验证（⏳ 需实机推流 + 运行后端，代码路径已就绪）
- [ ] 5.1 用 `打架测试视频.mp4` / `打架测试2.mp4` 推流到 RTMP `/live/<name>`
- [ ] 5.2 验证 YOLO 人体框有产出（`shared_ctx` 非空、视觉分非零）
- [ ] 5.3 验证音轨解码喂入（ffmpeg 日志、`feed_audio` 心跳、音频分非零）
- [ ] 5.4 验证情绪分参与融合（声学 `emo_risk` / 人脸 `emo_gate` 日志）
- [ ] 5.5 验证触发 `fight` 告警（`[fight] 打架告警 fuse=... vis=... aud=...` 日志 + 入库）
- [ ] 5.6 前端确认：告警面板出现打架告警、日志可筛选、分数可见
- [x] 5.7 回归确认：入侵/人脸/情绪等其他检测器功能未受影响 — 51 项后端测试全过（intrusion/fight/fatigue/face）

## 6. 校验
- [x] 6.1 运行 `openspec validate fight-fullchain-yolo-body --strict` 通过
- [x] 6.2 运行相关后端测试（`backend/tests/test_fight*.py`）通过 — 17 项 fight 测试全过
