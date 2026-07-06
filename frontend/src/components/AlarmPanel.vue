<template>
  <!-- 告警中心：红色闪烁 + 确认按钮 (§7.3, §7.4) -->
  <div class="alarm-panel">
    <el-table :data="alarms" style="width: 100%">
      <el-table-column prop="type" label="类型" />
      <el-table-column prop="region" label="防区/座位" />
      <el-table-column prop="face_match" label="人脸匹配" />
      <el-table-column prop="created_at" label="时间" />
      <el-table-column label="操作">
        <template #default="{ row }">
          <el-button
            v-if="row.status !== 'confirmed'"
            type="danger"
            @click="$emit('confirm', row.id)"
          >
            确认处理
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </div>
</template>

<script setup>
defineProps({ alarms: { type: Array, default: () => [] } })
defineEmits(['confirm'])
</script>

<style scoped>
/* 未确认告警红色闪烁 */
</style>
