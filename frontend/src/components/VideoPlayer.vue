<template>
  <!-- 低延迟播放 HTTP-FLV 流 (§3.3, §11) -->
  <div class="video-player-wrapper">
    <video
      ref="videoEl"
      controls
      autoplay
      muted
      class="video-player"
    />
    <div v-if="!streamUrl" class="video-placeholder">
      <div class="placeholder-icon">📹</div>
      <div class="placeholder-text">等待视频流连接...</div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from 'vue'
import flvjs from 'flv.js'

const props = defineProps({ streamUrl: String })
const videoEl = ref(null)
let player

const load = () => {
  if (!props.streamUrl || !flvjs.isSupported()) return
  player = flvjs.createPlayer({ type: 'flv', isLive: true, url: props.streamUrl })
  player.attachMediaElement(videoEl.value)
  player.load()
}

onMounted(load)
watch(() => props.streamUrl, load)
onUnmounted(() => player && player.destroy())
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
}
</style>
