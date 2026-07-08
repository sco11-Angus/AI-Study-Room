<template>
  <div class="page">
    <!-- 人脸识别结果 — 顶部醒目横幅 -->
    <div v-if="faceResult" class="face-banner" :class="faceResult.type">
      <span v-if="faceResult.type === 'member'">欢迎你, {{ faceResult.name }}</span>
      <span v-else>陌生人</span>
    </div>

    <div class="dashboard">
      <VideoPlayer :stream-url="streamUrl" />
      <AlarmPanel :alarms="alarms" @confirm="onConfirm" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import VideoPlayer from '../components/VideoPlayer.vue'
import AlarmPanel from '../components/AlarmPanel.vue'
import { confirmAlarm } from '../api'

const streamUrl = ref('')
const alarms = ref([])
const faceResult = ref(null)
let wsAlarms, wsFace, reconnectTimer

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
.page { background: #1a1a2e; min-height: 100vh; }
.face-banner {
  text-align: center;
  padding: 12px 0;
  font-size: 20px;
  font-weight: 700;
}
.face-banner.member {
  background: #67c23a;
  color: #fff;
}
.face-banner.stranger {
  background: #909399;
  color: #fff;
}
</style>
