<template>
  <div class="cell" :class="{ recognizing: recognize }" @click="$emit('enlarge', cameraId)">
    <div class="cell-header">
      <span class="cell-idx">{{ cameraId }}</span>
      <span class="cell-title">{{ title }}</span>
      <span v-if="recognize" class="cell-tag">AI</span>
    </div>

    <div class="cell-body">
      <canvas ref="canvasEl" class="cell-canvas" />
      <div v-if="statusText" class="cell-status">{{ statusText }}</div>

      <div v-if="recognize && badges.length" class="cell-badges">
        <span v-for="b in badges" :key="b.label" class="badge">{{ b.icon }} {{ b.label }}:{{ b.value }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, computed } from 'vue'

const props = defineProps({
  cameraId: { type: Number, required: true },
  title: { type: String, default: '' },
  recognize: { type: Boolean, default: false },
  // 由父组件按 camera_id 分发的最新街道识别结果 {counts, boxes}
  street: { type: Object, default: null },
})
defineEmits(['enlarge'])

const canvasEl = ref(null)
const statusText = ref('连接视频流...')

let ws = null
let reconnectTimer = null
let lastFrameTime = 0
let currentFrame = null
const RECONNECT_DELAY = 3000
const FRAME_INTERVAL = 1000 / 15

// 车辆合并计数（car+bus+truck+motorcycle），行人单列
const badges = computed(() => {
  const c = props.street?.counts
  if (!c) return []
  const vehicles = (c.car || 0) + (c.bus || 0) + (c.truck || 0) + (c.motorcycle || 0)
  const out = []
  if ((c.person || 0) > 0) out.push({ icon: '👤', label: '人', value: c.person })
  if (vehicles > 0) out.push({ icon: '🚗', label: '车', value: vehicles })
  if ((c.bicycle || 0) > 0) out.push({ icon: '🚲', label: '自行车', value: c.bicycle })
  return out
})

const BOX_COLORS = {
  person: '#67c23a',
  car: '#409eff', bus: '#409eff', truck: '#409eff', motorcycle: '#409eff',
  bicycle: '#e6a23c',
}

// ---- 检测框平滑跟随（rAF 插值） ----
// 每个 track 记录目标位置(tx..)与当前显示位置(x..)，每帧朝目标 lerp，
// 让框在两次检测之间平滑滑向移动的车，而不是硬跳。
let tracks = []          // [{x,y,w,h, tx,ty,tw,th, cls, seen}]
let rafId = null
const LERP = 0.35        // 插值系数：越大越跟手，越小越平滑

const matchAndUpdateTracks = (boxes) => {
  const incoming = (boxes || []).map((b) => ({ ...b, matched: false }))
  // 已有 track 找最近的新框更新目标
  for (const t of tracks) {
    let best = -1, bestD = 0.1
    for (let i = 0; i < incoming.length; i++) {
      const b = incoming[i]
      if (b.matched || b.cls !== t.cls) continue
      const d = Math.hypot(b.x - t.tx, b.y - t.ty)
      if (d < bestD) { best = i; bestD = d }
    }
    if (best >= 0) {
      const b = incoming[best]
      b.matched = true
      t.tx = b.x; t.ty = b.y; t.tw = b.w; t.th = b.h
      t.seen = 0
    } else {
      t.seen++   // 本次没匹配到，累计丢失次数
    }
  }
  // 未匹配的新框 → 新建 track（初始显示位置即目标，避免从 0 飞入）
  for (const b of incoming) {
    if (b.matched) continue
    tracks.push({
      x: b.x, y: b.y, w: b.w, h: b.h,
      tx: b.x, ty: b.y, tw: b.w, th: b.h,
      cls: b.cls, seen: 0,
    })
  }
  // 连续多次丢失的 track 移除
  tracks = tracks.filter((t) => t.seen < 4)
}

const drawBoxes = (ctx, w, h) => {
  if (!props.recognize) return
  ctx.lineWidth = Math.max(2, Math.round(w / 320))
  ctx.font = `bold ${Math.max(12, Math.round(w / 40))}px Arial`
  for (const t of tracks) {
    // 朝目标插值
    t.x += (t.tx - t.x) * LERP
    t.y += (t.ty - t.y) * LERP
    t.w += (t.tw - t.w) * LERP
    t.h += (t.th - t.h) * LERP
    const bw = t.w * w
    const bh = t.h * h
    const x = t.x * w - bw / 2
    const y = t.y * h - bh / 2
    const color = BOX_COLORS[t.cls] || '#f56c6c'
    ctx.strokeStyle = color
    ctx.strokeRect(x, y, bw, bh)
    const label = t.cls
    const tw = ctx.measureText(label).width
    ctx.fillStyle = color
    ctx.fillRect(x, Math.max(0, y - 18), tw + 10, 18)
    ctx.fillStyle = '#fff'
    ctx.fillText(label, x + 5, Math.max(13, y - 4))
  }
}

const renderFrame = () => {
  const canvas = canvasEl.value
  if (!canvas || !currentFrame) return
  const ctx = canvas.getContext('2d')
  ctx.drawImage(currentFrame, 0, 0, canvas.width, canvas.height)
  drawBoxes(ctx, canvas.width, canvas.height)
}

// rAF 持续重绘：即使没有新视频帧/检测，也让框平滑滑向目标
const animate = () => {
  renderFrame()
  rafId = requestAnimationFrame(animate)
}

const destroyWs = () => {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (ws) { ws.close(); ws = null }
}

const scheduleReconnect = () => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  reconnectTimer = setTimeout(connectWs, RECONNECT_DELAY)
}

const connectWs = () => {
  destroyWs()
  const wsUrl = `ws://${location.host}/ws/video_feed/${props.cameraId}`
  statusText.value = '连接视频流...'
  ws = new WebSocket(wsUrl)
  ws.binaryType = 'blob'

  ws.onmessage = async (event) => {
    if (event.data instanceof Blob) {
      const now = Date.now()
      if (now - lastFrameTime < FRAME_INTERVAL) return
      lastFrameTime = now
      let bitmap
      try {
        bitmap = await createImageBitmap(event.data)
      } catch (e) { return }
      const canvas = canvasEl.value
      if (!canvas) { bitmap.close(); return }
      if (canvas.width !== bitmap.width || canvas.height !== bitmap.height) {
        canvas.width = bitmap.width
        canvas.height = bitmap.height
      }
      statusText.value = ''
      // 用最新帧替换旧帧（rAF 循环负责重绘，不在此处 close，否则下一帧无图可画）
      const prev = currentFrame
      currentFrame = bitmap
      if (prev) prev.close?.()
    } else {
      try {
        const data = JSON.parse(event.data)
        if (data.status === 'offline') statusText.value = '摄像头离线'
        else if (data.status === 'no_camera') statusText.value = '摄像头不存在'
        else if (data.status === 'no_scheduler') statusText.value = '调度器未启动'
        else if (data.status === 'waiting') statusText.value = '缓冲中...'
      } catch (e) { /* ignore */ }
    }
  }

  ws.onclose = () => { statusText.value = '断开，3s 后重连...'; scheduleReconnect() }
  ws.onerror = () => { /* onclose follows */ }
}

// 街道识别结果更新时：只更新 track 目标，实际重绘交给 rAF 平滑插值
watch(() => props.street, (s) => matchAndUpdateTracks(s?.boxes), { deep: true })

onMounted(() => {
  connectWs()
  animate()
})
onUnmounted(() => {
  destroyWs()
  if (rafId) { cancelAnimationFrame(rafId); rafId = null }
  if (currentFrame) { currentFrame.close?.(); currentFrame = null }
})
</script>

<style scoped>
.cell {
  display: flex;
  flex-direction: column;
  background: #1c1c22;
  border-radius: 10px;
  overflow: hidden;
  cursor: pointer;
  border: 1px solid #2c2c35;
  transition: box-shadow 0.2s, transform 0.2s;
}
.cell:hover { transform: translateY(-2px); box-shadow: 0 6px 18px rgba(0, 0, 0, 0.35); }
.cell.recognizing { border-color: #d4a574; }

.cell-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: linear-gradient(90deg, #2a2a33 0%, #1f1f26 100%);
  color: #f0e6d6;
  font-size: 13px;
}
.cell-idx {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px; height: 20px;
  border-radius: 50%;
  background: #d4a574;
  color: #fff;
  font-size: 12px;
  font-weight: 700;
  flex: none;
}
.cell-title { flex: 1; }
.cell-tag {
  font-size: 11px;
  padding: 1px 6px;
  border-radius: 6px;
  background: #d4a574;
  color: #fff;
}

.cell-body {
  position: relative;
  width: 100%;
  aspect-ratio: 16 / 9;
  background: #000;
}
.cell-canvas { width: 100%; height: 100%; object-fit: contain; display: block; }

.cell-status {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 14px;
  background: rgba(0, 0, 0, 0.4);
}

.cell-badges {
  position: absolute;
  left: 8px;
  bottom: 8px;
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.badge {
  background: rgba(0, 0, 0, 0.65);
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  padding: 3px 8px;
  border-radius: 6px;
}

</style>
