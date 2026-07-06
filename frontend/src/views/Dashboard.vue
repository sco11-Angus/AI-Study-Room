<template>
  <!-- 告警监测大屏：格子 绿->红闪烁 + 蜂鸣 (§7.3) -->
  <div class="dashboard">
    <VideoPlayer :stream-url="streamUrl" />
    <AlarmPanel :alarms="alarms" @confirm="onConfirm" />
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import VideoPlayer from '../components/VideoPlayer.vue'
import AlarmPanel from '../components/AlarmPanel.vue'
import { confirmAlarm } from '../api'

const streamUrl = ref('')
const alarms = ref([])
let ws

onMounted(() => {
  // 订阅实时告警推送 (§7.3)
  ws = new WebSocket(`ws://${location.host}/ws/alarms`)
  ws.onmessage = (e) => alarms.value.unshift(JSON.parse(e.data))
})
onUnmounted(() => ws && ws.close())

const onConfirm = (id) => confirmAlarm(id)
</script>
