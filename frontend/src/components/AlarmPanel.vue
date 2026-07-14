<template>
  <div class="alarm-panel">
    <el-table
      :data="alarms"
      :row-class-name="rowClassName"
      style="width: 100%"
      :header-cell-style="{ background: 'linear-gradient(135deg, #fff9f0 0%, #fff5e6 100%)', color: '#5d4e37', fontWeight: '600', borderRadius: '8px' }"
      :cell-style="{ borderBottom: '1px solid #e8d5c4' }"
      @row-click="handleRowClick"
    >
      <el-table-column prop="type" label="类型" width="80">
        <template #default="{ row }">
          <span :class="['type-tag', row.type]">{{ getTypeLabel(row.type) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="描述" min-width="150">
        <template #default="{ row }">
          <div class="description-cell">
            <div class="message-text">{{ row.message || getDefaultMessage(row) }}</div>
            <div v-if="row.face_match" class="face-match-text">{{ row.face_match }}</div>
          </div>
        </template>
      </el-table-column>
      <el-table-column label="防区" width="60">
        <template #default="{ row }">
          <span>{{ row.region_id || '-' }}</span>
          <small v-if="row.level === 0" class="weak-tag">弱提醒</small>
        </template>
      </el-table-column>
      <el-table-column label="时间" width="150">
        <template #default="{ row }">
          {{ formatTime(row.created_at) }}
        </template>
      </el-table-column>
      <el-table-column prop="status" label="状态" width="80">
        <template #default="{ row }">
          <span :class="['status-tag', row.status]">{{ getStatusLabel(row.status) }}</span>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160">
        <template #default="{ row }">
          <el-button v-if="row.snapshot_url" type="primary" size="small" @click.stop="previewSnapshot(row)" class="preview-btn">查看截图</el-button>
          <el-button v-if="row.clip_url" type="success" size="small" @click.stop="playClip(row)" class="play-btn">回放</el-button>
          <el-button v-if="row.status !== 'confirmed'" type="danger" size="small" @click.stop="$emit('confirm', row.id)" class="confirm-btn">确认处理</el-button>
          <span v-else class="confirmed-text">已确认</span>
        </template>
      </el-table-column>
    </el-table>
    <div v-if="alarms.length === 0" class="empty-state">
      <div class="empty-icon">✨</div>
      <div class="empty-text">暂无告警记录</div>
    </div>
    <el-dialog v-model="snapshotVisible" title="告警截图" :close-on-click-modal="true" width="500px" class="snapshot-dialog">
      <img v-if="selectedAlarm" :src="selectedAlarm.snapshot_url" class="snapshot-image" />
      <div v-if="selectedAlarm" class="snapshot-info">
        <div><strong>告警ID:</strong> {{ selectedAlarm.id }}</div>
        <div><strong>类型:</strong> {{ getTypeLabel(selectedAlarm.type) }}</div>
        <div><strong>时间:</strong> {{ formatTime(selectedAlarm.created_at) }}</div>
        <div><strong>描述:</strong> {{ selectedAlarm.message || getDefaultMessage(selectedAlarm) }}</div>
      </div>
    </el-dialog>
    <el-dialog v-model="clipVisible" title="违规视频回放" :close-on-click-modal="true" width="600px" class="clip-dialog">
      <div v-if="selectedAlarm" class="clip-container">
        <video v-if="selectedAlarm.clip_url" :src="selectedAlarm.clip_url" controls class="clip-video" />
        <div v-else class="clip-loading">视频生成中...</div>
        <div class="clip-info">
          <div><strong>告警ID:</strong> {{ selectedAlarm.id }}</div>
          <div><strong>类型:</strong> {{ getTypeLabel(selectedAlarm.type) }}</div>
          <div><strong>时间:</strong> {{ formatTime(selectedAlarm.created_at) }}</div>
          <div><strong>描述:</strong> {{ selectedAlarm.message || getDefaultMessage(selectedAlarm) }}</div>
        </div>
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

const TYPE_LABELS = {
  intrusion: '入侵',
  fire_smoke: '烟火',
  occupy: '非预约占座',
  fatigue: '疲劳',
  fight: '打架',
  face_recognition: '人脸识别'
}

const STATUS_LABELS = {
  pending: '待处理',
  notified: '已通知',
  confirmed: '已确认',
  escalated: '已升级'
}

const rowClassName = ({ row }) => {
  return row.level === 0 ? 'alarm-row-weak' : row.status === 'confirmed' ? 'alarm-row-confirmed' : ''
}

const getTypeLabel = (type) => {
  return TYPE_LABELS[type] || type
}

const getStatusLabel = (status) => {
  return STATUS_LABELS[status] || status
}

const formatTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  return date.toLocaleString()
}

const getDefaultMessage = (row) => {
  const messages = {
    fight: '检测到肢体冲突行为',
    intrusion: '检测到人员闯入危险区域',
    fire_smoke: '检测到疑似烟火',
    occupy: '检测到非预约人员占用座位',
    fatigue: '检测到疲劳学习状态',
    face_recognition: '人脸识别结果'
  }
  return messages[row.type] || '告警触发'
}

const previewSnapshot = (row) => {
  selectedAlarm.value = row
  snapshotVisible.value = true
}

const playClip = (row) => {
  selectedAlarm.value = row
  clipVisible.value = true
}

const handleRowClick = (row) => {
  if (row.snapshot_url) {
    previewSnapshot(row)
  }
}
</script>

<style scoped>
.alarm-panel { height: 100%; display: flex; flex-direction: column; }
.alarm-panel :deep(.el-table) { border-radius: 8px; overflow: hidden; }
.alarm-panel :deep(.el-table__header-wrapper) { border-radius: 8px 8px 0 0; }
.alarm-panel :deep(.el-table__row) { cursor: pointer; }
.alarm-panel :deep(.el-table__row:hover) { background: #fef7f0; }
.type-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.type-tag.fight { background: #fff2f0; color: #f56c6c; }
.type-tag.intrusion { background: #fff7e6; color: #e6a23c; }
.type-tag.fire_smoke { background: #f6ffed; color: #67c23a; }
.type-tag.occupy { background: #ecf5ff; color: #409eff; }
.type-tag.fatigue { background: #f5f0ff; color: #909399; }
.type-tag.face_recognition { background: #fff0f6; color: #eb4d4b; }
.status-tag { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
.status-tag.pending { background: #fff2f0; color: #f56c6c; }
.status-tag.notified { background: #fff7e6; color: #e6a23c; }
.status-tag.confirmed { background: #f6ffed; color: #67c23a; }
.status-tag.escalated { background: #fff0f0; color: #f56c6c; font-weight: 600; }
.description-cell { display: flex; flex-direction: column; gap: 4px; }
.message-text { font-size: 13px; color: #303133; line-height: 1.4; }
.face-match-text { font-size: 12px; color: #909399; }
.preview-btn { background: linear-gradient(135deg, #409eff 0%, #3783f5 100%); border: none; border-radius: 6px; font-size: 12px; padding: 4px 8px; }
.play-btn { background: linear-gradient(135deg, #67c23a 0%, #5eb837 100%); border: none; border-radius: 6px; font-size: 12px; padding: 4px 8px; }
.confirm-btn { background: linear-gradient(135deg, #f56c6c 0%, #e65252 100%); border: none; border-radius: 6px; font-size: 12px; padding: 4px 8px; transition: all 0.3s ease; }
.confirm-btn:hover { transform: translateY(-2px); box-shadow: 0 4px 12px rgba(245, 108, 108, 0.3); }
.confirmed-text { color: #909399; font-size: 14px; }
.empty-state { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 16px; padding: 40px; }
.empty-icon { font-size: 48px; opacity: 0.5; }
.empty-text { color: #909399; font-size: 16px; }
.alarm-row-weak { background: #f7f7f7; }
.alarm-row-weak .el-table__cell { color: #909399; }
.alarm-row-confirmed { background: #f0fff4; }
.alarm-row-confirmed .el-table__cell { color: #67c23a; }
.weak-tag { display: inline-block; margin-left: 8px; padding: 2px 8px; border-radius: 10px; background: rgba(144, 147, 153, 0.12); color: #909399; font-size: 12px; }
.snapshot-dialog { padding: 0; }
.snapshot-image { width: 100%; max-height: 400px; object-fit: contain; }
.snapshot-info { padding: 16px; background: #fafafa; border-top: 1px solid #ebeef5; }
.snapshot-info div { margin-bottom: 8px; font-size: 14px; }
.clip-dialog { padding: 0; }
.clip-container { width: 100%; }
.clip-video { width: 100%; max-height: 400px; object-fit: contain; }
.clip-loading { display: flex; align-items: center; justify-content: center; height: 300px; color: #909399; }
.clip-info { padding: 16px; background: #fafafa; border-top: 1px solid #ebeef5; }
.clip-info div { margin-bottom: 8px; font-size: 14px; }
</style>
