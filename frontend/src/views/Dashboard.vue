<template>
  <div class="page">
    <!-- 人脸识别横幅 — 支持活体检测多状态 -->
    <div v-if="faceResult" class="face-banner" :class="[faceResult.type, { 'with-liveness': faceResult.liveness_passed !== undefined }]">
      <!-- member 成功识别 -->
      <div v-if="faceResult.type === 'member'" class="banner-content">
        <span class="banner-icon">✅</span>
        <div class="banner-text">
          <div class="banner-title">欢迎你, {{ faceResult.name }}</div>
          <div v-if="faceResult.liveness_passed" class="banner-meta">活体已验证 • 伪影评分: {{ (faceResult.artifact_score || 0).toFixed(2) }}</div>
        </div>
      </div>
      <!-- 陌生人 -->
      <div v-else-if="faceResult.type === 'stranger'" class="banner-content">
        <span class="banner-icon">⚠️</span>
        <div class="banner-text">
          <div class="banner-title">陌生人</div>
          <div class="banner-meta">无法识别的用户</div>
        </div>
      </div>
      <!-- 伪造/反光/屏幕回放 -->
      <div v-else-if="faceResult.type === 'face_spoof'" class="banner-content">
        <span class="banner-icon">❌</span>
        <div class="banner-text">
          <div class="banner-title">检测到可疑媒体</div>
          <div class="banner-meta">{{ reasonMap[faceResult.reason] || faceResult.reason || '请勿使用虚假媒体' }}</div>
        </div>
      </div>
      <!-- 检测中 -->
      <div v-else-if="faceResult.type === 'detecting'" class="banner-content">
        <span class="banner-icon spinning">🔍</span>
        <div class="banner-text">
          <div class="banner-title">{{ faceResult.message || '检测中' }}</div>
          <div v-if="faceResult.stage" class="banner-meta">阶段: {{ stageMap[faceResult.stage] || faceResult.stage }}</div>
        </div>
      </div>
      <!-- 重试 -->
      <div v-else-if="faceResult.type === 'retry'" class="banner-content">
        <span class="banner-icon spinning">🔄</span>
        <div class="banner-text">
          <div class="banner-title">重新检测中</div>
          <div class="banner-meta">请保持摄像头可见</div>
        </div>
      </div>
    </div>

    <div class="dashboard">
      <div class="video-section">
        <div class="section-header">
          <span class="header-icon">📹</span>
          <span class="header-title">实时监控</span>
        </div>
        <div class="video-container">
          <div class="video-frame" ref="videoWrapper">
            <VideoPlayer ref="playerRef" :stream-url="streamUrl" @dimensions="onVideoDimensions" />
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
import { ref, onMounted, onUnmounted, nextTick, watch } from 'vue'
import VideoPlayer from '../components/VideoPlayer.vue'
import AlarmPanel from '../components/AlarmPanel.vue'
import { confirmAlarm, getAlarms, getCameras, getRegions } from '../api'
import { MAX_ALARMS, useAlarmStore } from '../store/alarm'

const streamUrl = ref('')
const alarms = ref([])
const faceResult = ref(null)
const regions = ref([])
const videoWrapper = ref(null)
const overlayCanvas = ref(null)
const playerRef = ref(null)
const flashOn = ref(true)
let wsAlarms, wsFace, reconnectTimer, beepTimer, audioContext
// ---- 人脸框实时跟踪 ----
let wsFaceBoxes = null       // 人脸框 WebSocket
let faceBoxesReconnect = null
let targetFaces = []         // 后端最新推来的目标框（归一化坐标）
let renderFaces = []         // 当前渲染的框，每帧向 target 插值靠近
let rafId = null             // requestAnimationFrame 句柄
const LERP = 0.25            // 插值系数：越大越跟手，越小越顺滑

const alarmStore = useAlarmStore()

// 伪影原因映射表
const reasonMap = {
  'detected_reflection': '检测到反光/屏幕反射',
  'screen_texture': '检测到屏幕纹理',
  'eye_movement_insufficient': '眼球微动不足（可能是视频回放）',
  'blink_insufficient': '眨眼频率异常',
  'motion_spoof': '检测到异常运动模式'
}

// 检测阶段映射表
const stageMap = {
  'liveness_check': '活体检测中',
  'artifact_check': '媒体伪影检测中',
  'matching': '会员匹配中',
  'extracting': '特征提取中'
}

function fetchStreamUrl() {
  getCameras()
    .then((list) => {
      if (Array.isArray(list) && list.length) {
        const cloudCamera = list.find(c => c.stream_url.includes('49.233.71.82'))
        if (cloudCamera) {
          streamUrl.value = `camera_id=${cloudCamera.id}`
          fetchRegionsForCamera(cloudCamera.id)
        } else {
          streamUrl.value = `camera_id=${list[0].id}`
          fetchRegionsForCamera(list[0].id)
        }
      } else {
        streamUrl.value = ''
      }
    })
    .catch(() => {
      streamUrl.value = ''
    })
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

// 收到视频真实尺寸后设置框的宽高比，让框完全贴合视频比例
function onVideoDimensions({ width, height }) {
  const frame = videoWrapper.value
  if (frame && width && height) {
    frame.style.setProperty('--video-aspect', `${width} / ${height}`)
  }
  updateOverlaySize()
}

function updateOverlaySize() {
  nextTick(() => {
    const canvas = overlayCanvas.value
    const frame = videoWrapper.value
    if (!canvas || !frame) return

    // overlay 通过 CSS inset:0 已与 .video-frame 完全重合，
    // 这里只需让画布分辨率匹配框的渲染尺寸
    const width = frame.clientWidth
    const height = frame.clientHeight
    if (!width || !height) return

    canvas.width = width
    canvas.height = height
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
      ctx.fillStyle = flashOn.value ? 'rgba(245, 108, 108, 0.18)' : 'rgba(245, 108, 108, 0.04)'
    } else {
      ctx.strokeStyle = 'rgba(103, 195, 58, 0.9)'
      ctx.fillStyle = 'rgba(103, 195, 58, 0.06)'
    }
    ctx.lineWidth = 1.5
    ctx.fill()
    ctx.stroke()
    ctx.restore()

    const label = region.name || `区域 ${region.id}`
    const [lx, ly] = points[0]
    if (typeof lx === 'number' && typeof ly === 'number') {
      ctx.save()
      ctx.font = '600 11px system-ui, sans-serif'
      const padX = 5
      const textW = ctx.measureText(label).width
      const boxW = textW + padX * 2
      const boxH = 16
      // 标签置于多边形第一个点上方，贴住边框
      const bx = lx
      const by = Math.max(0, ly - boxH)
      // 半透明圆角底色 + 无边框，轻量美观
      ctx.fillStyle = status === 'red' ? 'rgba(245,108,108,0.92)' : 'rgba(103,195,58,0.92)'
      const r = 3
      ctx.beginPath()
      ctx.moveTo(bx + r, by)
      ctx.arcTo(bx + boxW, by, bx + boxW, by + boxH, r)
      ctx.arcTo(bx + boxW, by + boxH, bx, by + boxH, r)
      ctx.arcTo(bx, by + boxH, bx, by, r)
      ctx.arcTo(bx, by, bx + boxW, by, r)
      ctx.closePath()
      ctx.fill()
      ctx.fillStyle = '#fff'
      ctx.textBaseline = 'middle'
      ctx.fillText(label, bx + padX, by + boxH / 2 + 0.5)
      ctx.restore()
    }
  })

  drawFaceBoxes(ctx, canvas)
}

// 画人脸框 + 身份标签（会员绿框姓名 / 陌生人红框 / 识别中橙框）
function drawFaceBoxes(ctx, canvas) {
  if (!renderFaces.length) return
  renderFaces.forEach((f) => {
    const [nx1, ny1, nx2, ny2] = f.box
    const x = nx1 * canvas.width
    const y = ny1 * canvas.height
    const bw = (nx2 - nx1) * canvas.width
    const bh = (ny2 - ny1) * canvas.height

    const isMember = f.type === 'member'
    const color = isMember ? '#67c23a' : f.type === 'stranger' ? '#f56c6c' : '#e6a23c'

    ctx.save()
    ctx.strokeStyle = color
    ctx.lineWidth = 2
    ctx.strokeRect(x, y, bw, bh)

    const label = isMember ? f.name || '会员' : f.type === 'stranger' ? '陌生人' : '识别中…'
    ctx.font = '600 13px system-ui, sans-serif'
    const padX = 6
    const boxH = 20
    const textW = ctx.measureText(label).width
    const by = Math.max(0, y - boxH)
    ctx.fillStyle = color
    ctx.fillRect(x, by, textW + padX * 2, boxH)
    ctx.fillStyle = '#fff'
    ctx.textBaseline = 'middle'
    ctx.fillText(label, x + padX, by + boxH / 2 + 0.5)
    ctx.restore()
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

let flashTimer = null

function startFlash() {
  if (flashTimer) return
  flashTimer = setInterval(() => {
    flashOn.value = !flashOn.value
  }, 500)
}

function stopFlash() {
  if (flashTimer) {
    clearInterval(flashTimer)
    flashTimer = null
  }
  flashOn.value = true
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

// ---- 人脸框：订阅后端推送的归一化坐标 ----
function connectFaceBoxesWs() {
  wsFaceBoxes = new WebSocket(`ws://${location.host}/ws/face_boxes`)
  wsFaceBoxes.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      if (data.type === 'faces') {
        targetFaces = Array.isArray(data.faces) ? data.faces : []
        syncRenderFaces()
      }
    } catch (err) {
      // ignore
    }
  }
  wsFaceBoxes.onclose = () => {
    faceBoxesReconnect = setTimeout(connectFaceBoxesWs, 3000)
  }
  wsFaceBoxes.onerror = () => {
    try { wsFaceBoxes.close() } catch (e) { /* noop */ }
  }
}

// 按 track_id 对齐目标框：命中则更新目标、未命中的旧框移除、新框直接出现
function syncRenderFaces() {
  const map = new Map(renderFaces.map((f) => [f.track_id, f]))
  const next = []
  for (const t of targetFaces) {
    const cur = map.get(t.track_id)
    if (cur) {
      cur.target = t.box
      cur.type = t.type
      cur.name = t.name
      next.push(cur)
    } else {
      next.push({
        track_id: t.track_id,
        box: [...t.box],
        target: [...t.box],
        type: t.type,
        name: t.name,
      })
    }
  }
  renderFaces = next
}

// rAF 循环：每帧把框位置向目标插值，实现平滑跟随
function animateFaces() {
  if (renderFaces.length) {
    for (const f of renderFaces) {
      for (let i = 0; i < 4; i++) {
        f.box[i] += (f.target[i] - f.box[i]) * LERP
      }
    }
    drawOverlay()
  }
  rafId = requestAnimationFrame(animateFaces)
}

watch(
  () => alarmStore.activeRegions,
  () => {
    drawOverlay()
    const hasRed = Object.values(alarmStore.activeRegions).some((status) => status === 'red')
    if (hasRed) {
      startBeepLoop()
      startFlash()
    } else {
      stopBeepLoop()
      stopFlash()
    }
  },
  { deep: true }
)

watch(flashOn, () => {
  drawOverlay()
})

onMounted(() => {
  fetchStreamUrl()
  getAlarms().then((list) => {
    alarms.value = Array.isArray(list) ? list.slice(0, MAX_ALARMS) : []
    alarmStore.loadAlarms(alarms.value)
  })
  wsAlarms = new WebSocket(`ws://${location.host}/ws/alarms`)
  wsAlarms.onmessage = (e) => {
    const data = JSON.parse(e.data)
    if (data.type === 'update') {
      const idx = alarms.value.findIndex(a => a.id === data.id)
      if (idx !== -1) {
        alarms.value[idx] = { ...alarms.value[idx], ...data }
        alarmStore.update(data.id, data)
      }
    } else {
      alarms.value.unshift(data)
      if (alarms.value.length > MAX_ALARMS) {
        alarms.value.length = MAX_ALARMS
      }
      alarmStore.push(data)
    }
  }
  connectFaceWs()
  connectFaceBoxesWs()
  rafId = requestAnimationFrame(animateFaces)
  window.addEventListener('resize', updateOverlaySize)
})

onUnmounted(() => {
  wsAlarms && wsAlarms.close()
  wsFace && wsFace.close()
  wsFaceBoxes && wsFaceBoxes.close()
  reconnectTimer && clearTimeout(reconnectTimer)
  faceBoxesReconnect && clearTimeout(faceBoxesReconnect)
  rafId && cancelAnimationFrame(rafId)
  stopBeepLoop()
  stopFlash()
  window.removeEventListener('resize', updateOverlaySize)
  if (audioContext) {
    audioContext.close()
  }
})

const onConfirm = (id) => {
  confirmAlarm(id)
  alarmStore.confirm(id)
}
</script>

<style scoped>
.page {
  min-height: 100%;
}

.face-banner {
  padding: 16px 20px;
  border-radius: 12px;
  margin-bottom: 20px;
  animation: slideDown 0.5s ease;
}

.banner-content {
  display: flex;
  align-items: center;
  gap: 16px;
}

.banner-icon {
  font-size: 32px;
  display: inline-block;
  flex-shrink: 0;
}

.banner-icon.spinning {
  animation: spin 2s linear infinite;
}

@keyframes spin {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
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

.banner-text {
  text-align: left;
  flex: 1;
}

.banner-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 4px;
}

.banner-meta {
  font-size: 12px;
  opacity: 0.85;
  font-weight: 400;
}

.face-banner.member {
  background: linear-gradient(135deg, #95d475 0%, #67c23a 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(103, 194, 58, 0.3);
}

.face-banner.stranger {
  background: linear-gradient(135deg, #e6a23c 0%, #f3c96e 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(230, 162, 60, 0.3);
}

.face-banner.detecting {
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
}

.face-banner.retry {
  background: linear-gradient(135deg, #409eff 0%, #66b1ff 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(64, 158, 255, 0.3);
}

.face-banner.face_spoof {
  background: linear-gradient(135deg, #f56c6c 0%, #ff6b6b 100%);
  color: #fff;
  box-shadow: 0 4px 12px rgba(245, 108, 108, 0.3);
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
  position: relative;
}

/* 按视频真实比例的框：宽度撑满容器，高度由 aspect-ratio 推导 */
.video-frame {
  position: relative;
  width: 100%;
  aspect-ratio: var(--video-aspect, 4 / 3);
  max-height: 100%;
}

.overlay-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
}
</style>