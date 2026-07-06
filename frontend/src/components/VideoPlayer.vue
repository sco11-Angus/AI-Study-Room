<template>
  <!-- 低延迟播放 HTTP-FLV 流 (§3.3, §11) -->
  <video ref="videoEl" controls autoplay muted style="width: 100%; max-width: 960px" />
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
