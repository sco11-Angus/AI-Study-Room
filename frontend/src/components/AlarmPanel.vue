<template>
  <!-- 告警中心：红色闪烁 + 确认按钮 (§7.3, §7.4) -->
  <div class="alarm-panel">
    <el-table
      :data="alarms"
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
      <el-table-column prop="region" label="防区/座位" />
      <el-table-column prop="face_match" label="人脸匹配" />
      <el-table-column prop="created_at" label="时间" />
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
defineProps({ alarms: { type: Array, default: () => [] } })
defineEmits(['confirm'])
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
</style>
