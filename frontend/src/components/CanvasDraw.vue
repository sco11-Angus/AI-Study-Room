<template>
  <!-- 视频图层上勾勒多边形 ROI：单击加点，双击闭合 (§5.1) -->
  <div class="canvas-wrap" style="position: relative; display: inline-block">
    <VideoPlayer :stream-url="streamUrl" />
    <canvas
      ref="canvasEl"
      style="position: absolute; top: 0; left: 0"
      @click="addPoint"
      @dblclick="closePolygon"
    />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import VideoPlayer from './VideoPlayer.vue'

const props = defineProps({ streamUrl: String })
const emit = defineEmits(['polygon'])
const canvasEl = ref(null)
const points = ref([])

const addPoint = (e) => {
  points.value.push([e.offsetX, e.offsetY])
  redraw()
}

const closePolygon = () => {
  // TODO: 坐标归一化后映射回原始分辨率 (§5.1)
  emit('polygon', points.value)
  points.value = []
}

const redraw = () => {
  const ctx = canvasEl.value.getContext('2d')
  ctx.clearRect(0, 0, canvasEl.value.width, canvasEl.value.height)
  ctx.strokeStyle = '#67c23a'
  ctx.beginPath()
  points.value.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)))
  ctx.stroke()
}
</script>
