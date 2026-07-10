<template>
  <div class="page">
    <!-- 人脸识别结果 — 顶部醒目横幅 -->
    <div v-if="faceResult" class="face-banner" :class="faceResult.type">
      <span v-if="faceResult.type === 'member'">欢迎你, {{ faceResult.name }}</span>
      <span v-else>陌生人</span>
    </div>

    <div class="dashboard">
      <div class="video-section">
        <div class="section-header">
          <span class="header-icon">📹</span>
          <span class="header-title">实时监控</span>
        </div>
        <div class="video-container">
          <div class="video-overlay-wrapper" ref="videoWrapper">
            <VideoPlayer :stream-url="streamUrl" />
            <canvas ref="overlayCanvas" class="overlay-canvas" />
          </div>
        </div>
      </div>
      
      <div class="alarm-section">
        <div class="section-header">
          <span class="header-icon">🔔</span>
          <span class="header-title">告警记录</span>
        </div>
        <div class="alarm-container">
          <AlarmPanel :alarms="alarms" @confirm="onConfirm" />
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useAlarmStore } from '../store/alarm'
import VideoPlayer from '../components/VideoPlayer.vue'
import AlarmPanel from '../components/AlarmPanel.vue'
import { confirmAlarm, getAlarms, getCameras, getRegions } from '../api'
import { ElMessage } from 'element-plus'

const DEFAULT_STREAM_URL = `http://${location.hostname}:8080/live?app=live&stream=test`
const streamUrl = ref('')
const faceResult = ref(null)
const regions = ref([])
const videoWrapper = ref(null)
const overlayCanvas = ref(null)
const flashOn = ref(true)
let wsAlarms = null
let wsFace = null
let reconnectTimer = null
let flashTimer = null
let beepTimer = null
let audioContext = null
const alarmStore = useAlarmStore()

const alarms = computed(() => alarmStore.alarms)
const activeRegions = computed(() => alarmStore.activeRegions)

function resolveStreamUrl(rawUrl) {
  if (!rawUrl) {
    return DEFAULT_STREAM_URL
  }
  if (rawUrl.startsWith('http://') || rawUrl.startsWith('https://')) {
    return rawUrl
  }
  const match = rawUrl.match(/\/live\/(.+?)(?:\s|$|\?)/)
  if (match) {
    return `http://${location.hostname}:8080/live?app=live&stream=${match[1]}`
  }
  return DEFAULT_STREAM_URL
}

function updateOverlaySize() {
  nextTick(() => {
    const canvas = overlayCanvas.value
    const wrapper = videoWrapper.value
    if (!canvas || !wrapper) return

    const width = wrapper.clientWidth
    const height = wrapper.clientHeight
    if (!width || !height) return

    canvas.width = width
    canvas.height = height
    canvas.style.width = `${width}px`
    canvas.style.height = `${height}px`
    drawOverlay()
  })
}

function drawOverlay() {
  const canvas = overlayCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  if (!regions.value || !regions.value.length) return

  regions.value.forEach((region) => {
    if (!Array.isArray(region.polygon) || !region.polygon.length) return
    const points = region.polygon.map(([x, y]) => [x * canvas.width, y * canvas.height])
    if (!points.length) return

    const status = alarmStore.activeRegions[region.id] || 'green'
    ctx.save()
    ctx.beginPath()
    points.forEach(([x, y], index) => {
      if (index === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    ctx.closePath()

    if (status === 'red') {
      ctx.strokeStyle = '#f56c6c'
      ctx.fillStyle = flashOn.value ? 'rgba(245, 108, 108, 0.25)' : 'rgba(245, 108, 108, 0.05)'
    } else {
      ctx.strokeStyle = '#67c23a'
      ctx.fillStyle = 'rgba(103, 195, 58, 0.12)'
    }
    ctx.lineWidth = 3
    ctx.fill()
    ctx.stroke()
    ctx.restore()

    const label = region.name || `区域 ${region.id}`
    const [lx, ly] = points[0]
    if (typeof lx === 'number' && typeof ly === 'number') {
      ctx.save()
      ctx.font = '14px sans-serif'
      const textWidth = ctx.measureText(label).width + 12
      const textHeight = 22
      ctx.fillStyle = status === 'red' ? '#fff2f2' : '#f7fff3'
      ctx.strokeStyle = status === 'red' ? '#f56c6c' : '#67c23a'
      ctx.lineWidth = 1.5
      ctx.fillRect(lx, ly - textHeight, textWidth, textHeight)
      ctx.strokeRect(lx, ly - textHeight, textWidth, textHeight)
      ctx.fillStyle = '#303133'
      ctx.fillText(label, lx + 6, ly - 6)
      ctx.restore()
    }
  })
}

function initAudioContext() {
  if (audioContext) return
  try {
    audioContext = new (window.AudioContext || window.webkitAudioContext)()
  } catch {
    audioContext = null
  }
}

function playBeep() {
  if (!audioContext) {
    initAudioContext()
  }
  if (!audioContext) return
  if (audioContext.state === 'suspended') {
    audioContext.resume().catch(() => {})
  }

  const oscillator = audioContext.createOscillator()
  const gainNode = audioContext.createGain()
  oscillator.type = 'sine'
  oscillator.frequency.value = 880
  gainNode.gain.value = 0.16
  oscillator.connect(gainNode)
  gainNode.connect(audioContext.destination)
  oscillator.start()
  oscillator.stop(audioContext.currentTime + 0.16)
}

function startBeepLoop() {
  if (beepTimer) return
  playBeep()
  beepTimer = setInterval(() => {
    if (Object.values(alarmStore.activeRegions).some((status) => status === 'red')) {
      playBeep()
    }
  }, 1200)
}

function stopBeepLoop() {
  if (beepTimer) {
    clearInterval(beepTimer)
    beepTimer = null
  }
}

function fetchRegionsForCamera(cameraId) {
  getRegions(cameraId)
    .then((list) => {
      regions.value = Array.isArray(list) ? list : []
      alarmStore.initRegions(regions.value.map((r) => r.id))
      updateOverlaySize()
    })
    .catch(() => {
      regions.value = []
    })
}

function fetchStreamUrl() {
  getCameras()
    .then((list) => {
      if (Array.isArray(list) && list.length) {
        const camera = list[0]
        streamUrl.value = resolveStreamUrl(camera.stream_url)
        fetchRegionsForCamera(camera.id)
      } else {
        streamUrl.value = DEFAULT_STREAM_URL
      }
    })
    .catch(() => {
      streamUrl.value = DEFAULT_STREAM_URL
    })
}

function connectFaceWs() {
  wsFace = new WebSocket(`ws://${location.host}/ws/face_recognition`)
  wsFace.onmessage = (e) => {
    const data = JSON.parse(e.data)
    if (data?.data) {
      faceResult.value = data.data
    } else {
      faceResult.value = data
    }
  }
  wsFace.onclose = () => {
    reconnectTimer = setTimeout(connectFaceWs, 3000)
  }
}

function connectAlarmWs() {
  wsAlarms = new WebSocket(`ws://${location.host}/ws/alarms`)
  wsAlarms.onmessage = (e) => {
    const alarm = JSON.parse(e.data)
    alarmStore.push(alarm)
  }
  wsAlarms.onclose = () => {
    reconnectTimer = setTimeout(connectAlarmWs, 3000)
  }
}

function onConfirm(id) {
  confirmAlarm(id)
    .then(() => {
      alarmStore.confirm(id)
    })
    .catch((error) => {
      ElMessage.error(error.message || '确认失败')
    })
}

onMounted(() => {
  fetchStreamUrl()
  connectAlarmWs()
  connectFaceWs()
  getAlarms()
    .then((list) => {
      alarmStore.loadAlarms(list)
    })
    .catch(() => {
      // ignore history load failures and rely on live push
    })

  flashTimer = setInterval(() => {
    flashOn.value = !flashOn.value
    drawOverlay()
  }, 500)
  window.addEventListener('resize', updateOverlaySize)
})

onUnmounted(() => {
  if (wsAlarms) wsAlarms.close()
  if (wsFace) wsFace.close()
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (flashTimer) clearInterval(flashTimer)
  stopBeepLoop()
  window.removeEventListener('resize', updateOverlaySize)
})

watch([
  () => regions.value,
  () => alarmStore.activeRegions,
  () => streamUrl.value,
], () => {
  updateOverlaySize()
}, { deep: true })

watch(
  () => Object.values(alarmStore.activeRegions),
  (states) => {
    if (states.some((status) => status === 'red')) {
      startBeepLoop()
    } else {
      stopBeepLoop()
    }
  },
  { deep: true, immediate: true }
)
</script>

<style scoped>
.page {
  min-height: 100%;
}

.face-banner {
  text-align: center;
  padding: 16px 0;
  font-size: 18px;
  font-weight: 600;
  border-radius: 12px;
  margin-bottom: 20px;
  animation: slideDown 0.5s ease;
}

@keyframes slideDown {
  from {
    opacity: 0;
    transform: translateY(-20px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

.face-banner.member {
  background: linear-gradient(135deg, #95d475 0%, #67c23a 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(103, 194, 58, 0.3);
}

.face-banner.stranger {
  background: linear-gradient(135deg, #c0c4cc 0%, #909399 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(144, 147, 153, 0.3);
}

.dashboard {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  height: calc(100vh - 140px);
}

.video-section,
.alarm-section {
  background: #fff;
  border-radius: 16px;
  box-shadow: 0 2px 12px rgba(212, 165, 116, 0.15);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.section-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 20px 24px;
  background: linear-gradient(135deg, #fff9f0 0%, #fff5e6 100%);
  border-bottom: 1px solid #e8d5c4;
}

.header-icon {
  font-size: 24px;
}

.header-title {
  font-size: 18px;
  font-weight: 600;
  color: #5d4e37;
}

.video-container,
.alarm-container {
  flex: 1;
  padding: 20px;
  overflow: auto;
}

.video-container {
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #faf8f5 0%, #f5f0e8 100%);
}

  .video-overlay-wrapper {
    position: relative;
    width: 100%;
    height: 100%;
  }

  .overlay-canvas {
    position: absolute;
    left: 0;
    top: 0;
    width: 100%;
    height: 100%;
    pointer-events: none;
  }</style>