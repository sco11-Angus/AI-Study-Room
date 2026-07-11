<template>
  <div class="video-player-wrapper">
    <canvas ref="canvasEl" class="video-player" />

    <div v-if="streamStatus" class="video-placeholder">
      <div class="placeholder-icon">📹</div>
      <div class="placeholder-text">{{ streamStatus }}</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'

const props = defineProps({ streamUrl: String })
const canvasEl = ref(null)
const streamStatus = ref('连接视频流...')
let ws = null
let reconnectTimer = null
let lastFrameTime = 0
const RECONNECT_DELAY = 3000
const FRAME_INTERVAL = 1000 / 15

const destroyWs = () => {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  if (ws) {
    ws.close()
    ws = null
  }
}

const scheduleReconnect = () => {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
  }
  reconnectTimer = setTimeout(() => {
    connectWs()
  }, RECONNECT_DELAY)
}

const connectWs = () => {
  destroyWs()

  if (!props.streamUrl) {
    streamStatus.value = '等待视频流连接...'
    return
  }

  const cameraId = props.streamUrl.match(/camera_id=(\d+)/)?.[1]
  if (!cameraId) {
    streamStatus.value = '等待摄像头信息...'
    return
  }
  const wsUrl = `ws://${location.host}/ws/video_feed/${cameraId}`

  streamStatus.value = '连接视频流...'

  ws = new WebSocket(wsUrl)
  ws.binaryType = 'blob'

  ws.onmessage = (event) => {
    if (event.data instanceof Blob) {
      const now = Date.now()
      if (now - lastFrameTime < FRAME_INTERVAL) return
      lastFrameTime = now

      streamStatus.value = ''
      const canvas = canvasEl.value
      if (!canvas) return

      const img = new Image()
      img.onload = () => {
        // 让 canvas 绘图缓冲区匹配视频帧真实尺寸，否则默认 300x150 会导致裁剪+变形
        if (canvas.width !== img.naturalWidth || canvas.height !== img.naturalHeight) {
          canvas.width = img.naturalWidth
          canvas.height = img.naturalHeight
        }
        const ctx = canvas.getContext('2d')
        ctx.drawImage(img, 0, 0)
        URL.revokeObjectURL(img.src)
      }
      img.src = URL.createObjectURL(event.data)
    } else {
      try {
        const data = JSON.parse(event.data)
        if (data.status === 'offline') {
          streamStatus.value = '摄像头离线'
        } else if (data.status === 'no_camera') {
          streamStatus.value = '摄像头不存在'
        } else if (data.status === 'no_scheduler') {
          streamStatus.value = '调度器未启动'
        }
      } catch (e) {
        // ignore
      }
    }
  }

  ws.onclose = () => {
    streamStatus.value = '视频流断开，3s 后重试...'
    scheduleReconnect()
  }

  ws.onerror = () => {
    streamStatus.value = '视频流异常，3s 后重试...'
    scheduleReconnect()
  }
}

watch(
  () => props.streamUrl,
  () => {
    connectWs()
  }
)

onMounted(() => {
  connectWs()
})

onUnmounted(() => {
  destroyWs()
})

defineExpose({
  streamStatus,
})
</script>

<style scoped>
.video-player-wrapper {
  position: relative;
  width: 100%;
  height: 100%;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
}

.video-player {
  width: 100%;
  height: 100%;
  object-fit: contain;
  border-radius: 12px;
}

.video-placeholder {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  background: linear-gradient(135deg, #faf8f5 0%, #f5f0e8 100%);
  border-radius: 12px;
}

.placeholder-icon {
  font-size: 64px;
  opacity: 0.5;
}

.placeholder-text {
  color: #909399;
  font-size: 16px;
  text-align: center;
  max-width: 220px;
}
</style>
