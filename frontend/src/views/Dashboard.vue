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
          <VideoPlayer :stream-url="streamUrl" />
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
import { ref, onMounted, onUnmounted } from 'vue'
import VideoPlayer from '../components/VideoPlayer.vue'
import AlarmPanel from '../components/AlarmPanel.vue'
import { confirmAlarm, getCameras } from '../api'

const DEFAULT_STREAM_URL = `http://${location.hostname}:8080/live?app=live&stream=test`
const streamUrl = ref('')
const alarms = ref([])
const faceResult = ref(null)
let wsAlarms, wsFace, reconnectTimer

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

function fetchStreamUrl() {
  getCameras()
    .then((list) => {
      if (Array.isArray(list) && list.length) {
        streamUrl.value = resolveStreamUrl(list[0].stream_url)
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

onMounted(() => {
  fetchStreamUrl()
  wsAlarms = new WebSocket(`ws://${location.host}/ws/alarms`)
  wsAlarms.onmessage = (e) => alarms.value.unshift(JSON.parse(e.data))
  connectFaceWs()
})
onUnmounted(() => {
  wsAlarms && wsAlarms.close()
  wsFace && wsFace.close()
  reconnectTimer && clearTimeout(reconnectTimer)
})

const onConfirm = (id) => confirmAlarm(id)
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
</style>
