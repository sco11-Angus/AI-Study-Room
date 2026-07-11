<template>
  <!-- 防区配置：视频流上叠加 Canvas 勾勒多边形 (§5.1, §5.2) -->
  <div class="region-config">
    <div class="region-left">
      <CanvasDraw :stream-url="streamUrl" @polygon="onPolygon" />
      <div class="tip-box">双击闭合路径后，当前多边形会记录为归一化坐标。</div>
    </div>

    <div class="region-right">
      <el-form :model="form" label-width="140px">
        <el-form-item label="摄像头">
          <el-select v-model="form.camera_id" placeholder="请选择摄像头">
            <el-option
              v-for="camera in cameras"
              :key="camera.id"
              :label="camera.name"
              :value="camera.id"
            />
          </el-select>
        </el-form-item>
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
        <el-form-item label="归一化多边形">
          <div class="polygon-preview">
            <div v-if="form.polygon.length">{{ form.polygon.length }}个点，坐标已归一化</div>
            <div v-else class="empty-state">请先在视频上画一个多边形并双击闭合</div>
          </div>
        </el-form-item>
        <el-button type="primary" @click="submit">提交并持久化</el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import CanvasDraw from '../components/CanvasDraw.vue'
import { createRegion, getCameras } from '../api'

const DEFAULT_FLV_HOST = '49.233.71.82'
const DEFAULT_STREAM_URL = `http://${DEFAULT_FLV_HOST}:8080/live?app=live&stream=test`
const streamUrl = ref(DEFAULT_STREAM_URL)
const cameras = ref([])
const form = ref({ camera_id: null, name: '', type: 'danger_zone', polygon: [], x_distance: 50, y_stay_time: 10 })

const loadCameras = () => {
  getCameras()
    .then((list) => {
      cameras.value = Array.isArray(list) ? list : []
      if (!form.value.camera_id && cameras.value.length) {
        form.value.camera_id = cameras.value[0].id
      }
    })
    .catch(() => {
      cameras.value = []
    })
}

onMounted(loadCameras)

const onPolygon = (pts) => {
  form.value.polygon = pts
}

const submit = () => {
  if (!form.value.camera_id) {
    ElMessage.warning('请先选择摄像头')
    return
  }
  if (!form.value.name) {
    ElMessage.warning('请填写防区名称')
    return
  }
  if (!form.value.polygon.length) {
    ElMessage.warning('请先绘制一个多边形并双击闭合')
    return
  }

  createRegion(form.value)
    .then(() => {
      ElMessage.success('防区已提交')
      form.value.name = ''
      form.value.polygon = []
      form.value.x_distance = 50
      form.value.y_stay_time = 10
    })
    .catch(() => {
      /* 已由拦截器处理错误消息 */
    })
}
</script>

<style scoped>
.region-config {
  display: grid;
  grid-template-columns: 1.6fr 0.9fr;
  gap: 24px;
  align-items: start;
}

.region-left {
  background: #fff;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 14px 36px rgba(55, 52, 48, 0.08);
}

.region-right {
  background: #fff;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 14px 36px rgba(55, 52, 48, 0.08);
}

.tip-box {
  margin-top: 16px;
  padding: 12px 16px;
  border-radius: 12px;
  background: #f5f7ff;
  color: #3c4d8c;
  font-size: 14px;
}

.polygon-preview {
  min-height: 48px;
  display: flex;
  align-items: center;
  color: #606266;
}

.empty-state {
  color: #909399;
}
</style>
