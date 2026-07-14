<template>
  <div class="page">
    <div class="header">
      <div class="header-left">
        <span class="header-icon">📋</span>
        <span class="header-title">告警日志</span>
      </div>
      <div class="header-right">
        <el-date-picker
          v-model="filterDate"
          type="date"
          placeholder="选择日期"
          value-format="YYYY-MM-DD"
          @change="onFilterChange"
        />
        <el-select v-model="filterType" placeholder="告警类型" @change="onFilterChange">
          <el-option label="全部" value="" />
          <el-option label="入侵告警" value="intrusion" />
          <el-option label="烟火告警" value="fire_smoke" />
          <el-option label="占座告警" value="occupy" />
          <el-option label="疲劳提醒" value="fatigue" />
          <el-option label="打架告警" value="fight" />
          <el-option label="争吵打闹" value="quarrel" />
          <el-option label="欺骗攻击" value="face_spoof" />
        </el-select>
        <el-select v-model="filterLevel" placeholder="告警级别" @change="onFilterChange">
          <el-option label="全部" :value="null" />
          <el-option label="弱提醒(0)" :value="0" />
          <el-option label="普通告警(1)" :value="1" />
          <el-option label="高优先(2+)" :value="2" />
        </el-select>
        <el-button @click="refreshLogs" type="primary" size="small">刷新</el-button>
      </div>
    </div>

    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-value">{{ stats.total_count || 0 }}</div>
        <div class="stat-label">告警总数</div>
      </div>
      <div class="stat-card">
        <div class="stat-value type-intrusion">{{ stats.type_stats?.intrusion || 0 }}</div>
        <div class="stat-label">入侵告警</div>
      </div>
      <div class="stat-card">
        <div class="stat-value type-fire">{{ stats.type_stats?.fire_smoke || 0 }}</div>
        <div class="stat-label">烟火告警</div>
      </div>
      <div class="stat-card">
        <div class="stat-value type-face">{{ stats.type_stats?.face_spoof || 0 }}</div>
        <div class="stat-label">欺骗攻击</div>
      </div>
    </div>

    <div class="table-container">
      <el-table :data="logEntries" border stripe :loading="loading">
        <el-table-column prop="timestamp" label="时间" width="180" />
        <el-table-column prop="type" label="类型" width="100">
          <template #default="scope">
            <span class="type-tag" :class="scope.row.type">{{ getTypeLabel(scope.row.type) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="level" label="级别" width="80">
          <template #default="scope">
            <span class="level-tag" :class="getLevelClass(scope.row.level)">{{ getLevelLabel(scope.row.level) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="region" label="防区" width="80" />
        <el-table-column prop="camera" label="摄像头" width="80" />
        <el-table-column prop="face_match" label="人脸匹配" width="120" />
        <el-table-column prop="message" label="告警信息" min-width="200" />
        <el-table-column prop="actor" label="行为者" width="100" />
        <el-table-column label="操作" width="240">
          <template #default="scope">
            <el-button
              v-if="scope.row.snapshot_url"
              type="primary"
              size="small"
              @click="viewSnapshot(scope.row.snapshot_url)"
            >截图</el-button>
            <el-button
              v-if="scope.row.clip_url"
              type="success"
              size="small"
              @click="viewClip(scope.row.clip_url)"
            >回放</el-button>
            <el-button
              type="danger"
              size="small"
              @click="deleteLog(scope.row)"
            >删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination">
        <el-pagination
          v-model:current-page="currentPage"
          :page-size="pageSize"
          :total="total"
          layout="total, prev, pager, next, jumper"
          @current-change="fetchLogs"
        />
      </div>
    </div>

    <el-dialog v-model="showSnapshot" title="告警截图" width="600px">
      <img v-if="snapshotUrl" :src="getFullUrl(snapshotUrl)" class="snapshot-image" />
      <div v-else class="empty-snapshot">暂无截图</div>
    </el-dialog>

    <el-dialog v-model="showClip" title="违规视频回放" width="640px">
      <video v-if="clipUrl" :src="getFullUrl(clipUrl)" controls autoplay class="snapshot-image" />
      <div v-else class="empty-snapshot">暂无回放</div>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted, reactive } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'

const filterDate = ref('')
const filterType = ref('')
const filterLevel = ref(null)
const currentPage = ref(1)
const pageSize = ref(50)
const logEntries = ref([])
const stats = reactive({})
const loading = ref(false)
const showSnapshot = ref(false)
const snapshotUrl = ref('')
const showClip = ref(false)
const clipUrl = ref('')
const total = ref(0)

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

function getTypeLabel(type) {
  return typeLabels[type] || type || '未知'
}

function getLevelLabel(level) {
  if (level === 0) return '弱提醒'
  if (level === 1) return '普通'
  if (level >= 2) return '高优先'
  return '-'
}

function getLevelClass(level) {
  if (level === 0) return 'level-0'
  if (level === 1) return 'level-1'
  if (level >= 2) return 'level-2'
  return ''
}

function onFilterChange() {
  currentPage.value = 1
  fetchLogs()
}

function refreshLogs() {
  currentPage.value = 1
  fetchLogs()
}

function fetchLogs() {
  loading.value = true
  const params = new URLSearchParams()
  if (filterDate.value) params.append('date', filterDate.value)
  if (filterType.value) params.append('type', filterType.value)
  if (filterLevel.value !== null) params.append('level', filterLevel.value)
  params.append('page', currentPage.value)
  params.append('limit', pageSize.value)

  fetch(`/api/logs?${params}`)
    .then((res) => res.json())
    .then((data) => {
      if (data.code === 0) {
        logEntries.value = data.data?.entries || []
        total.value = data.data?.total || 0
      }
    })
    .catch(() => {
      logEntries.value = []
      total.value = 0
    })
    .finally(() => {
      loading.value = false
    })
}

function fetchStats() {
  const params = new URLSearchParams()
  if (filterDate.value) params.append('date', filterDate.value)

  fetch(`/api/logs/stats?${params}`)
    .then((res) => res.json())
    .then((data) => {
      if (data.code === 0) {
        Object.assign(stats, data.data)
      }
    })
    .catch(() => {})
}

function viewSnapshot(url) {
  snapshotUrl.value = url
  showSnapshot.value = true
}

function viewClip(url) {
  clipUrl.value = url
  showClip.value = true
}

function deleteLog(row) {
  ElMessageBox.confirm(
    '删除后将同时从数据库移除该告警记录及其截图/回放文件，且不可恢复。确认删除？',
    '删除告警日志',
    { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
  )
    .then(() => fetch(`/api/logs/${row.id}`, { method: 'DELETE' }).then((res) => res.json()))
    .then((data) => {
      if (data && data.code === 0) {
        ElMessage.success('已删除')
        fetchLogs()
        fetchStats()
      } else if (data) {
        ElMessage.error(data.message || '删除失败')
      }
    })
    .catch((e) => {
      if (e !== 'cancel') ElMessage.error('删除失败')
    })
}

function getFullUrl(url) {
  if (url.startsWith('http')) return url
  return `${window.location.origin}${url}`
}

onMounted(() => {
  fetchLogs()
  fetchStats()
})
</script>

<style scoped>
.page {
  min-height: 100%;
  display: flex;
  flex-direction: column;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px 0;
  margin-bottom: 20px;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.header-icon {
  font-size: 32px;
}

.header-title {
  font-size: 24px;
  font-weight: 600;
  color: #5d4e37;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.stats-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
  margin-bottom: 24px;
}

.stat-card {
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  text-align: center;
  box-shadow: 0 2px 8px rgba(212, 165, 116, 0.1);
}

.stat-value {
  font-size: 28px;
  font-weight: 700;
  color: #5d4e37;
  margin-bottom: 8px;
}

.stat-value.type-intrusion {
  color: #f56c6c;
}

.stat-value.type-fire {
  color: #e6a23c;
}

.stat-value.type-face {
  color: #909399;
}

.stat-label {
  font-size: 14px;
  color: #909399;
}

.table-container {
  flex: 1;
  background: #fff;
  border-radius: 12px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(212, 165, 116, 0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.el-table {
  flex: 1;
  min-height: 0;
}

.type-tag {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.type-tag.intrusion {
  background: #fef0f0;
  color: #f56c6c;
}

.type-tag.fire_smoke {
  background: #fff7e6;
  color: #e6a23c;
}

.type-tag.occupy {
  background: #f0f5ff;
  color: #409eff;
}

.type-tag.fatigue {
  background: #f0f9eb;
  color: #67c23a;
}

.type-tag.fight {
  background: #fef0f0;
  color: #f56c6c;
}

.type-tag.quarrel {
  background: #fff7e6;
  color: #e6a23c;
}

.type-tag.face_spoof {
  background: #f4f4f5;
  color: #909399;
}

.level-tag {
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.level-tag.level-0 {
  background: #f0f9eb;
  color: #67c23a;
}

.level-tag.level-1 {
  background: #fff7e6;
  color: #e6a23c;
}

.level-tag.level-2 {
  background: #fef0f0;
  color: #f56c6c;
}

.pagination {
  display: flex;
  justify-content: center;
  padding-top: 20px;
  border-top: 1px solid #ebeef5;
}

.snapshot-image {
  width: 100%;
  border-radius: 8px;
}

.empty-snapshot {
  text-align: center;
  padding: 40px;
  color: #909399;
}
</style>
