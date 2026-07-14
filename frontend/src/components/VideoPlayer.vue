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

const props = defineProps({ 
  streamUrl: String,
  faceResult: Object 
})
const emit = defineEmits(['dimensions'])
const canvasEl = ref(null)
const streamStatus = ref('连接视频流...')
let ws = null
let reconnectTimer = null
let lastFrameTime = 0
const RECONNECT_DELAY = 3000
const FRAME_INTERVAL = 1000 / 15
let currentFrame = null

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

const drawFaceBox = (ctx, faceData) => {
  if (!faceData || !faceData.box) return
  
  const { box, name, match } = faceData
  const [x, y, width, height] = box
  
  // 绘制人脸框
  ctx.strokeStyle = match ? '#67c23a' : '#f56c6c'
  ctx.lineWidth = 3
  ctx.strokeRect(x, y, width, height)
  
  // 绘制标签背景
  if (name || match) {
    const label = match ? `✓ ${name}` : '陌生人'
    ctx.font = 'bold 16px Arial'
    const textWidth = ctx.measureText(label).width
    const labelHeight = 24
    const labelY = y > labelHeight + 5 ? y - labelHeight - 5 : y + height + 5
    
    ctx.fillStyle = match ? 'rgba(103, 194, 58, 0.9)' : 'rgba(245, 108, 108, 0.9)'
    ctx.fillRect(x, labelY, textWidth + 16, labelHeight)
    
    // 绘制标签文字
    ctx.fillStyle = '#fff'
    ctx.fillText(label, x + 8, labelY + 17)
  }
}

const renderFrame = () => {
  if (!currentFrame || !canvasEl.value) return
  
  const canvas = canvasEl.value
  const ctx = canvas.getContext('2d')
  
  // 绘制视频帧
  ctx.drawImage(currentFrame, 0, 0)
  
  // 绘制人脸框
  if (props.faceResult) {
    drawFaceBox(ctx, props.faceResult)
  }
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

  ws.onmessage = async (event) => {
    if (event.data instanceof Blob) {
      const now = Date.now()
      if (now - lastFrameTime < FRAME_INTERVAL) return
      lastFrameTime = now

      streamStatus.value = ''
      const canvas = canvasEl.value
      if (!canvas) return

      let bitmap
      try {
        bitmap = await createImageBitmap(event.data)
      } catch (e) {
        return
      }
      
      if (!canvasEl.value) {
        bitmap.close()
        return
      }
      
      if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
        canvas.width = bitmap.width
        canvas.height = bitmap.height
        if (bitmap.width && bitmap.height) {
          emit('dimensions', { width: bitmap.width, height: bitmap.height })
        }
      }
      
      currentFrame = bitmap
      renderFrame()
      bitmap.close()
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

watch(
  () => props.faceResult,
  () => {
    renderFrame()
  },
  { deep: true }
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
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  border-radius: 12px;
  overflow: hidden;
  background: #000;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
}

.video-player {
  display: block;
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
