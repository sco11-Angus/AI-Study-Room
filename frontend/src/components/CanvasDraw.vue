<template>
  <!-- 视频图层上勾勒多边形 ROI：单击加点，双击闭合 (§5.1) -->
  <div class="canvas-wrap" style="position: relative; display: inline-block">
    <VideoPlayer ref="playerRef" :stream-url="streamUrl" />
    <canvas
      ref="canvasEl"
      class="overlay-canvas"
      @click="addPoint"
      @dblclick="closePolygon"
    />
  </div>
</template>

<script setup>
import { ref, watch, onMounted, nextTick } from 'vue'
import VideoPlayer from './VideoPlayer.vue'

const props = defineProps({ streamUrl: String })
const emit = defineEmits(['polygon'])
const playerRef = ref(null)
const canvasEl = ref(null)
const points = ref([])

const updateCanvasSize = () => {
  const canvas = canvasEl.value
  const player = playerRef.value
  if (!canvas || !player) return

  const width = player.videoWidth || canvas.clientWidth
  const height = player.videoHeight || canvas.clientHeight
  if (!width || !height) return

  canvas.width = width
  canvas.height = height
  canvas.style.width = '100%'
  canvas.style.height = '100%'
  redraw()
}

watch(
  () => [playerRef.value?.videoWidth?.value, playerRef.value?.videoHeight?.value],
  () => updateCanvasSize(),
  { immediate: true }
)

onMounted(() => {
  nextTick(updateCanvasSize)
})

const addPoint = (e) => {
  const canvas = canvasEl.value
  if (!canvas) return

  const rect = canvas.getBoundingClientRect()
  const x = ((e.clientX - rect.left) * canvas.width) / rect.width
  const y = ((e.clientY - rect.top) * canvas.height) / rect.height

  points.value.push([x, y])
  redraw()
}

const closePolygon = () => {
  // TODO: 坐标归一化后映射回原始分辨率 (§5.1)
  emit('polygon', points.value)
  points.value = []
  redraw()
}

const redraw = () => {
  const canvas = canvasEl.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)
  if (!points.value.length) return

  ctx.strokeStyle = '#67c23a'
  ctx.lineWidth = 2
  ctx.beginPath()
  points.value.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
  ctx.closePath()
  ctx.stroke()
}
</script>

<style scoped>
.overlay-canvas {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  pointer-events: all;
}
</style>
