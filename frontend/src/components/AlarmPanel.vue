<template>
  <!-- 告警中心：红色闪烁 + 确认按钮 (§7.3, §7.4) -->
  <div class="alarm-panel">
    <el-table
      :data="alarms"
      :row-class-name="rowClassName"
      style="width: 100%"
      :header-cell-style="{
        background: 'linear-gradient(135deg, #fff9f0 0%, #fff5e6 100%)',
        color: '#5d4e37',
        fontWeight: '600',
        borderRadius: '8px'
      }"
      :cell-style="{ borderBottom: '1px solid #e8d5c4' }"
    >
      <el-table-column label="类型" width="100">
        <template #default="{ row }">
          <span class="type-tag" :class="row.type">{{ getTypeLabel(row.type) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="防区/座位">
        <template #default="{ row }">
          <span>{{ row.region_id || '-' }}</span>
          <small v-if="row.level === 0" class="weak-tag">弱提醒</small>
        </template>
      </el-table-column>
      <el-table-column label="等级">
        <template #default="{ row }">
          <span>{{ row.level === 0 ? '弱提醒' : '告警' }}</span>
        </template>
      </el-table-column>
      <el-table-column prop="face_match" label="人脸匹配" />
      <el-table-column label="时间">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" />
      <el-table-column label="操作" width="220">
        <template #default="{ row }">
          <el-button
            v-if="row.snapshot_url"
            type="primary"
            size="small"
            @click="previewSnapshot(row)"
            class="preview-btn"
          >
            查看截图
          </el-button>
          <el-button
            v-if="row.clip_url"
            type="success"
            size="small"
            @click="playClip(row)"
            class="play-btn"
          >
            回放
          </el-button>
          <el-button
            v-if="row.status !== 'confirmed'"
            type="danger"
            size="small"
            @click="$emit('confirm', row.id)"
            class="confirm-btn"
          >
            确认处理
          </el-button>
          <span v-else class="confirmed-text">已确认</span>
        </template>
      </el-table-column>
    </el-table>

    <div v-if="alarms.length === 0" class="empty-state">
      <div class="empty-icon">✨</div>
      <div class="empty-text">暂无告警记录</div>
    </div>

    <!-- 截图预览 -->
    <el-dialog v-model="snapshotVisible" title="告警截图" width="560px" class="media-dialog">
      <img v-if="selectedAlarm" :src="selectedAlarm.snapshot_url" class="snapshot-image" alt="告警截图" />
      <div v-if="selectedAlarm" class="media-info">
        <div><strong>类型:</strong> {{ selectedAlarm.type }}</div>
        <div><strong>时间:</strong> {{ formatTime(selectedAlarm.created_at) }}</div>
        <div v-if="selectedAlarm.message"><strong>描述:</strong> {{ selectedAlarm.message }}</div>
      </div>
    </el-dialog>

    <!-- 视频回放 -->
    <el-dialog v-model="clipVisible" title="违规视频回放" width="640px" class="media-dialog">
      <video v-if="selectedAlarm && selectedAlarm.clip_url" :src="selectedAlarm.clip_url" controls autoplay class="clip-video" />
      <div v-else class="clip-loading">视频生成中或不可用...</div>
      <div v-if="selectedAlarm" class="media-info">
        <div><strong>类型:</strong> {{ selectedAlarm.type }}</div>
        <div><strong>时间:</strong> {{ formatTime(selectedAlarm.created_at) }}</div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({ alarms: { type: Array, default: () => [] } })
const emit = defineEmits(['confirm'])

const snapshotVisible = ref(false)
const clipVisible = ref(false)
const selectedAlarm = ref(null)

// 与告警日志页 (LogViewer) 一致的类型中文标签
const typeLabels = {
  intrusion: '入侵告警',
  fire_smoke: '烟火告警',
  occupy: '占座告警',
  fatigue: '疲劳提醒',
  fight: '打架告警',
  quarrel: '争吵打闹',
  face_spoof: '欺骗攻击',
  face_recognition: '人脸识别',
  abnormal_sound: '异常声音',
}

const getTypeLabel = (type) => typeLabels[type] || type || '未知'

const rowClassName = ({ row }) => {
  return row.level === 0 ? 'alarm-row-weak' : ''
}

const formatTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  return date.toLocaleString()
}

const previewSnapshot = (row) => {
  selectedAlarm.value = row
  snapshotVisible.value = true
}

const playClip = (row) => {
  selectedAlarm.value = row
  clipVisible.value = true
}
</script>

<style scoped>
.alarm-panel {
  height: 100%;
  display: flex;
  flex-direction: column;
}

.alarm-panel :deep(.el-table) {
  border-radius: 8px;
  overflow: hidden;
}

.alarm-panel :deep(.el-table__header-wrapper) {
  border-radius: 8px 8px 0 0;
}

.type-tag {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  background: #f4f4f5;
  color: #909399;
}
.type-tag.intrusion { background: #fef0f0; color: #f56c6c; }
.type-tag.fire_smoke { background: #fff7e6; color: #e6a23c; }
.type-tag.occupy { background: #f0f5ff; color: #409eff; }
.type-tag.fatigue { background: #f0f9eb; color: #67c23a; }
.type-tag.fight { background: #fef0f0; color: #f56c6c; }
.type-tag.quarrel { background: #fff7e6; color: #e6a23c; }
.type-tag.face_spoof { background: #f4f4f5; color: #909399; }
.type-tag.abnormal_sound { background: #fdf6ec; color: #e6a23c; }

.preview-btn {
  background: linear-gradient(135deg, #409eff 0%, #3783f5 100%);
  border: none;
  border-radius: 8px;
}

.play-btn {
  background: linear-gradient(135deg, #67c23a 0%, #5eb837 100%);
  border: none;
  border-radius: 8px;
}

.snapshot-image {
  width: 100%;
  max-height: 420px;
  object-fit: contain;
  border-radius: 8px;
}

.clip-video {
  width: 100%;
  max-height: 420px;
  border-radius: 8px;
  background: #000;
}

.clip-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 240px;
  color: #909399;
}

.media-info {
  padding: 12px 4px 0;
  font-size: 14px;
  color: #303133;
}

.media-info div {
  margin-bottom: 6px;
}

.confirm-btn {
  background: linear-gradient(135deg, #f56c6c 0%, #e65252 100%);
  border: none;
  border-radius: 8px;
  transition: all 0.3s ease;
}

.confirm-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 12px rgba(245, 108, 108, 0.3);
}

.confirmed-text {
  color: #909399;
  font-size: 14px;
}

.empty-state {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
  padding: 40px;
}

.empty-icon {
  font-size: 48px;
  opacity: 0.5;
}

.empty-text {
  color: #909399;
  font-size: 16px;
}

.alarm-row-weak {
  background: #f7f7f7;
}

.alarm-row-weak .el-table__cell {
  color: #909399;
}

.weak-tag {
  display: inline-block;
  margin-left: 8px;
  padding: 2px 8px;
  border-radius: 10px;
  background: rgba(144, 147, 153, 0.12);
  color: #909399;
  font-size: 12px;
}</style>