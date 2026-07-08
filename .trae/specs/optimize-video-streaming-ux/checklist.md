# Checklist

- [x] 重连后 `cs.online` 在 `cap.isOpened()` 为 True 时立即设置（不等下一帧 read）
- [x] 短暂解码卡顿（<2s）不发送 "waiting"，前端不显示"缓冲中"
- [x] 持续无帧 >2s 仍触发 "waiting" 和"缓冲中"提示
- [x] Dashboard 不再使用 `/api/face_result` HTTP 轮询
- [x] Dashboard 使用 `/ws/face_recognition` WebSocket 实时接收人脸结果
- [x] 前端 Canvas 渲染使用 `createImageBitmap`（或回退方案）
- [x] 高频帧到达时旧帧被跳过（已移除：async 解码期间 renderId 冲刷导致全部丢帧，改回逐帧渲染）
- [x] 现有功能不受影响：推流、拉流、人脸识别均正常工作
