<template>
  <!-- 视频图层上勾勒多边形 ROI：单击加点，双击闭合 (§5.1) -->
  <div class="canvas-wrap">
    <VideoPlayer ref="playerRef" :stream-url="streamUrl" />
    <canvas
      ref="canvasEl"
      class="overlay-canvas"
      @click="addPoint"
      @dblclick="closePolygon"
    />
    <div class="polygon-toolbar">
      <div>已绘{{ polygons.length }}个多边形，双击闭合当前路径。</div>
      <div class="polygon-actions">
        <button type="button" @click="undoLastPoint" :disabled="!currentPolygon.length">撤销最后一点</button>
        <button type="button" @click="clearCurrentPolygon" :disabled="!currentPolygon.length">清除当前路径</button>
      </div>
    </div>
    <div class="polygon-list" v-if="polygons.length">
      <div class="polygon-item" v-for="(polygon, index) in polygons" :key="index">
        <span>多边形 {{ index + 1 }} （{{ polygon.points.length }} 点）</span>
        <button type="button" @click="deletePolygon(index)">删除</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, nextTick } from 'vue'
import VideoPlayer from './VideoPlayer.vue'

const props = defineProps({ streamUrl: String, previewPolygon: Array })
const emit = defineEmits(['polygon'])
const playerRef = ref(null)
const canvasEl = ref(null)
const currentPolygon = ref([])
const polygons = ref([])
const previewPolygons = ref([])
const canvasWidth = ref(0)
const canvasHeight = ref(0)

const getPixelPoints = (normalized) => {
  if (!normalized || !normalized.length || !canvasWidth.value || !canvasHeight.value) {
    return []
  }
  return normalized.map(([x, y]) => [x * canvasWidth.value, y * canvasHeight.value])
}

const updatePreviewPolygons = () => {
  previewPolygons.value = props.previewPolygon ? [getPixelPoints(props.previewPolygon)] : []
}

const redraw = () => {
  const canvas = canvasEl.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.clearRect(0, 0, canvas.width, canvas.height)

  const drawPath = (points, options = {}) => {
    if (!points || !points.length) return
    ctx.save()
    ctx.strokeStyle = options.strokeStyle || '#67c23a'
    ctx.fillStyle = options.fillStyle || 'rgba(103, 195, 58, 0.15)'
    ctx.lineWidth = options.lineWidth || 2
    ctx.setLineDash(options.lineDash || [])
    ctx.beginPath()
    points.forEach(([x, y], index) => {
      if (index === 0) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    })
    if (options.closed) {
      ctx.closePath()
      ctx.fill()
    }
    ctx.stroke()
    ctx.restore()
  }

  previewPolygons.value.forEach((polygon) => drawPath(polygon, { strokeStyle: '#f56c6c', fillStyle: 'rgba(245, 108, 108, 0.18)', lineWidth: 2, closed: true }))
  polygons.value.forEach((polygon) => drawPath(polygon.points, { closed: true }))
  drawPath(currentPolygon.value, { strokeStyle: '#409eff', lineDash: [6, 4] })
}

const updateCanvasSize = () => {
  const canvas = canvasEl.value
  const player = playerRef.value
  if (!canvas || !player) return

  const width = player.videoWidth?.value || canvas.clientWidth
  const height = player.videoHeight?.value || canvas.clientHeight
  if (!width || !height) return

  canvas.width = width
  canvas.height = height
  canvas.style.width = '100%'
  canvas.style.height = '100%'
  canvasWidth.value = width
  canvasHeight.value = height
  updatePreviewPolygons()
  redraw()
}

watch(
  () => [playerRef.value?.videoWidth?.value, playerRef.value?.videoHeight?.value],
  updateCanvasSize,
  { immediate: true }
)

watch(
  () => props.previewPolygon,
  () => {
    updatePreviewPolygons()
    redraw()
  },
  { deep: true, immediate: true }
)

onMounted(() => {
  nextTick(updateCanvasSize)
})

const pointFromEvent = (e) => {
  const canvas = canvasEl.value
  if (!canvas) return null
  const rect = canvas.getBoundingClientRect()
  const x = ((e.clientX - rect.left) * canvas.width) / rect.width
  const y = ((e.clientY - rect.top) * canvas.height) / rect.height
  return [x, y]
}

const addPoint = (e) => {
  const point = pointFromEvent(e)
  if (!point) return
  currentPolygon.value.push(point)
  redraw()
}

const closePolygon = () => {
  if (currentPolygon.value.length < 3) {
    return
  }

  const normalized = currentPolygon.value.map(([x, y]) => [x / canvasWidth.value, y / canvasHeight.value])
  polygons.value.push({ points: [...currentPolygon.value], normalized })
  emit('polygon', normalized)
  currentPolygon.value = []
  redraw()
}

const deletePolygon = (index) => {
  polygons.value.splice(index, 1)
  redraw()
}

const undoLastPoint = () => {
  currentPolygon.value.pop()
  redraw()
}

const clearCurrentPolygon = () => {
  currentPolygon.value = []
  redraw()
}
</script>

<style scoped>
.canvas-wrap {
  position: relative;
  display: inline-block;
  width: 100%;
  min-height: 360px;
}

.overlay-canvas {
  position: absolute;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  cursor: crosshair;
  pointer-events: all;
}

.polygon-toolbar {
  position: absolute;
  left: 16px;
  bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px 14px;
  background: rgba(255, 255, 255, 0.88);
  border-radius: 12px;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.12);
  font-size: 14px;
  color: #333;
}

.polygon-actions {
  display: flex;
  gap: 8px;
}

.polygon-actions button,
.polygon-list button {
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  background: #fff;
  padding: 4px 10px;
  cursor: pointer;
}

.polygon-list {
  position: absolute;
  right: 16px;
  top: 16px;
  min-width: 220px;
  background: rgba(255, 255, 255, 0.92);
  border-radius: 12px;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.12);
  padding: 12px;
}

.polygon-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
  font-size: 13px;
}

.polygon-item:last-child {
  margin-bottom: 0;
}
</style>
