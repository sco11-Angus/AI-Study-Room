<template>
  <div class="street-monitor">
    <div class="header">
      <h2>🚦 街道监控大屏</h2>
      <span class="sub">沙盘 12 路 · AI 识别 {{ recognizeIds.length }} 路（行人 / 停车场 / 隧道车辆）</span>
      <span class="ws-state" :class="{ ok: wsConnected }">
        {{ wsConnected ? '● 识别通道已连接' : '○ 识别通道未连接' }}
      </span>
    </div>

    <div class="grid">
      <StreetCameraCell
        v-for="cam in cameras"
        :key="cam.id"
        :camera-id="cam.id"
        :title="cam.title"
        :recognize="recognizeIds.includes(cam.id)"
        :street="streetByCam[cam.id] || null"
        @enlarge="enlarge"
      />
    </div>

    <div v-if="enlargedId !== null" class="modal" @click.self="enlargedId = null">
      <div class="modal-inner">
        <button class="modal-close" @click="enlargedId = null">✕ 返回网格</button>
        <StreetCameraCell
          :camera-id="enlargedId"
          :title="titleOf(enlargedId)"
          :recognize="recognizeIds.includes(enlargedId)"
          :street="streetByCam[enlargedId] || null"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted } from 'vue'
import StreetCameraCell from '../components/StreetCameraCell.vue'

// camera_id 1~12 与 沙盘_rtsp_streams.md 序号对齐
const cameras = [
  { id: 1, title: '桥面' },
  { id: 2, title: '停车场出口' },
  { id: 3, title: '行人检测' },
  { id: 4, title: '消防车识别' },
  { id: 5, title: '桥出口' },
  { id: 6, title: '桥入口' },
  { id: 7, title: '道路2' },
  { id: 8, title: '隧道（事故）' },
  { id: 9, title: '隧道（车辆数量）' },
  { id: 10, title: '道路3' },
  { id: 11, title: '停车场入口' },
  { id: 12, title: '道路1' },
]

// 与后端 StreetDetector.camera_ids 对齐
const recognizeIds = [3, 2, 11, 9]

const titleOf = (id) => cameras.find((c) => c.id === id)?.title || `摄像头${id}`

// camera_id -> 最新 {counts, boxes}
const streetByCam = reactive({})
const enlargedId = ref(null)
const wsConnected = ref(false)

const enlarge = (id) => { enlargedId.value = id }

let ws = null
let reconnectTimer = null

const connectStreetWs = () => {
  if (ws) { ws.close(); ws = null }
  ws = new WebSocket(`ws://${location.host}/ws/street`)

  ws.onopen = () => { wsConnected.value = true }
  ws.onmessage = (e) => {
    if (typeof e.data !== 'string') return
    try {
      const msg = JSON.parse(e.data)
      if (msg.type === 'street' && msg.camera_id != null) {
        streetByCam[msg.camera_id] = { counts: msg.counts, boxes: msg.boxes }
      }
    } catch (_) { /* ignore */ }
  }
  ws.onclose = () => {
    wsConnected.value = false
    if (reconnectTimer) clearTimeout(reconnectTimer)
    reconnectTimer = setTimeout(connectStreetWs, 3000)
  }
  ws.onerror = () => { /* onclose follows */ }
}

onMounted(connectStreetWs)
onUnmounted(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer)
  if (ws) ws.close()
})
</script>

<style scoped>
.street-monitor {
  padding: 8px 4px;
}

.header {
  display: flex;
  align-items: baseline;
  gap: 16px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.header h2 { color: #5d4e37; margin: 0; }
.header .sub { color: #909399; font-size: 14px; }
.header .ws-state { margin-left: auto; font-size: 13px; color: #c0392b; }
.header .ws-state.ok { color: #67c23a; }

/* 4 列网格，每格够大（大屏 ≥480px）；窄屏自适应降列 */
.grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}
@media (max-width: 1680px) {
  .grid { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 1100px) {
  .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}

.modal {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.75);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 2000;
  padding: 40px;
}
.modal-inner {
  width: min(1280px, 90vw);
  position: relative;
}
.modal-close {
  position: absolute;
  top: -40px;
  right: 0;
  background: #d4a574;
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 16px;
  font-size: 14px;
  cursor: pointer;
}
.modal-close:hover { background: #c49464; }
</style>
