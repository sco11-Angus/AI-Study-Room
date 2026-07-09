<template>
  <!-- 低延迟播放 HTTP-FLV 流 (§3.3) -->
  <div class="video-player-wrapper">
    <video
      ref="videoEl"
      controls
      autoplay
      muted
      class="video-player"
    />

    <div v-if="!streamUrl || streamStatus" class="video-placeholder">
      <div class="placeholder-icon">📹</div>
      <div class="placeholder-text">
        {{ streamStatus || '等待视频流连接...' }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import flvjs from 'flv.js'

const props = defineProps({ streamUrl: String })
const videoEl = ref(null)
const streamStatus = ref('')
const videoWidth = ref(0)
const videoHeight = ref(0)
let player = null
let reconnectTimer = null
const RECONNECT_DELAY = 3000

const resetStatus = (message = '') => {
  streamStatus.value = message
}

let onLoadedMetadata = null
let onVideoError = null

const destroyPlayer = () => {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }

  const el = videoEl.value
  if (el) {
    if (onLoadedMetadata) {
      el.removeEventListener('loadedmetadata', onLoadedMetadata)
      onLoadedMetadata = null
    }
    if (onVideoError) {
      el.removeEventListener('error', onVideoError)
      onVideoError = null
    }
  }

  if (!player) {
    return
  }

  try {
    player.unload()
    player.detachMediaElement()
    player.destroy()
  } catch (error) {
    // ignore destroy errors
  }
  player = null
}

const scheduleReconnect = () => {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
  }
  reconnectTimer = setTimeout(() => {
    if (props.streamUrl) {
      loadPlayer()
    }
  }, RECONNECT_DELAY)
}

const updateVideoSize = () => {
  const el = videoEl.value
  if (!el) return
  videoWidth.value = el.videoWidth || 0
  videoHeight.value = el.videoHeight || 0
}

const handlePlayerError = () => {
  resetStatus('视频流异常，3s 后重试...')
  destroyPlayer()
  scheduleReconnect()
}

const loadPlayer = () => {
  destroyPlayer()

  if (!props.streamUrl) {
    resetStatus('等待视频流连接...')
    return
  }

  if (!videoEl.value) {
    resetStatus('等待视频组件挂载...')
    return
  }

  if (!flvjs.isSupported()) {
    resetStatus('当前浏览器不支持 flv.js')
    return
  }

  resetStatus('连接视频流...')

  player = flvjs.createPlayer({
    type: 'flv',
    isLive: true,
    url: props.streamUrl,
  })

  player.attachMediaElement(videoEl.value)
  player.load()

  player.on(flvjs.Events.ERROR, handlePlayerError)

  onLoadedMetadata = updateVideoSize
  onVideoError = handlePlayerError

  videoEl.value.addEventListener('loadedmetadata', onLoadedMetadata)
  videoEl.value.addEventListener('error', onVideoError)
}

const reconnect = () => {
  if (reconnectTimer) {
    clearTimeout(reconnectTimer)
    reconnectTimer = null
  }
  loadPlayer()
}

watch(
  () => props.streamUrl,
  (newUrl, oldUrl) => {
    if (newUrl !== oldUrl) {
      loadPlayer()
    }
  }
)

onMounted(() => {
  if (props.streamUrl) {
    loadPlayer()
  }
})

onUnmounted(() => {
  destroyPlayer()
})

defineExpose({
  videoWidth,
  videoHeight,
  reconnect,
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
