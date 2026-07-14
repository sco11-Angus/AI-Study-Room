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
      <el-table-column prop="type" label="类型" />
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
      <el-table-column label="操作" width="120">
        <template #default="{ row }">
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
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({ alarms: { type: Array, default: () => [] } })
const emit = defineEmits(['confirm'])

const rowClassName = ({ row }) => {
  return row.level === 0 ? 'alarm-row-weak' : ''
}

const formatTime = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  return date.toLocaleString()
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