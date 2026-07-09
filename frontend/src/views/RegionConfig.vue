<template>
  <!-- 防区配置：视频流上叠加 Canvas 勾勒多边形 (§5.1, §5.2) -->
  <div class="region-config">
    <CanvasDraw :stream-url="streamUrl" @polygon="onPolygon" />
    <el-form :model="form" label-width="140px">
      <el-form-item label="防区名称">
        <el-input v-model="form.name" />
      </el-form-item>
      <el-form-item label="类型">
        <el-select v-model="form.type">
          <el-option label="危险防区" value="danger_zone" />
          <el-option label="独立座位" value="seat" />
        </el-select>
      </el-form-item>
      <el-form-item label="安全距离(px) X_distance">
        <el-input-number v-model="form.x_distance" :min="0" />
      </el-form-item>
      <el-form-item label="停留时间(s) Y_stay_time">
        <el-input-number v-model="form.y_stay_time" :min="0" />
      </el-form-item>
      <el-button type="primary" @click="submit">提交并持久化</el-button>
    </el-form>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import CanvasDraw from '../components/CanvasDraw.vue'
import { createRegion } from '../api'

const DEFAULT_STREAM_URL = `http://${location.hostname}:8080/live?app=live&stream=test`
const streamUrl = ref(DEFAULT_STREAM_URL)
const form = ref({ name: '', type: 'danger_zone', polygon: [], x_distance: 50, y_stay_time: 10 })

const onPolygon = (pts) => (form.value.polygon = pts) // 双击闭合的多边形顶点
const submit = () => createRegion(form.value)
</script>
