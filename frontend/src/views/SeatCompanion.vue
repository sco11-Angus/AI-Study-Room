<template>
  <!-- 自习伴侣：状态宣告与私有弱提醒展示 (§4) -->
  <div class="seat-companion">
    <div class="panel-card">
      <div class="panel-header">
        <div>
          <h2>自习伴侣</h2>
          <p>切换状态后，前端会拉取当前用户的疲劳弱提醒并以私有样式展示。</p>
        </div>
        <el-radio-group v-model="status" @change="onChange">
          <el-radio-button value="studying">自习中</el-radio-button>
          <el-radio-button value="resting">休息中</el-radio-button>
        </el-radio-group>
      </div>

      <div class="status-card" :class="status">
        <div class="status-title">{{ status === 'studying' ? '疲劳监测已开启' : '休息中，监测已暂停' }}</div>
        <div class="status-hint">{{ tip || '当前暂无状态提示。' }}</div>
      </div>

      <div v-if="weakReminder" class="weak-reminder-card">
        <div class="weak-badge">{{ weakReminder.level >= 1 ? '钉钉提醒' : '私有提醒' }}</div>
        <div class="weak-title">{{ fatigueKindText(weakReminder.extra?.kind) }}</div>
        <div class="weak-message">{{ fatigueMessage(weakReminder) }}</div>
        <div class="weak-meta">{{ formatTime(weakReminder.created_at) }}</div>
      </div>
      <div v-else class="empty-state">当前没有需要你单独查看的疲劳弱提醒。</div>
      <div v-if="!dingtalkConfigured" class="config-warning">钉钉 Webhook 未配置，疲劳告警只会本地记录，不会外发到钉钉。</div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getAlarms, getCameras, getRegions, getSeatCompanionStatus, switchSeatStatus } from '../api'

const status = ref('studying')
const tip = ref('已进入自习模式，疲劳弱提醒将以私有方式展示。')
const weakReminder = ref(null)
const seatRegionId = ref(null)
const dingtalkConfigured = ref(true)
let pollTimer = null

// 动态解析一个 seat 类型防区，避免硬编码不存在的 region_id 导致 404
const resolveSeatRegion = () => {
  getCameras()
    .then((cameras) => {
      const list = Array.isArray(cameras) ? cameras : []
      if (!list.length) return
      return getRegions(list[0].id).then((regions) => {
        const seats = (Array.isArray(regions) ? regions : []).filter((r) => r.type === 'seat')
        if (seats.length) {
          seatRegionId.value = seats[0].id
        }
      })
    })
    .catch(() => {
      seatRegionId.value = null
    })
}

const loadWeakReminders = () => {
  if (!seatRegionId.value) return
  getSeatCompanionStatus(1001, seatRegionId.value)
    .then((data) => {
      status.value = data.status === 'resting' ? 'resting' : 'studying'
      dingtalkConfigured.value = !!data.dingtalk_configured
      weakReminder.value = data.latest_fatigue || null
    })
    .catch(() => {
      getAlarms()
        .then((list) => {
          const reminders = Array.isArray(list) ? list : []
          weakReminder.value = reminders
            .filter((item) => item.type === 'fatigue')
            .sort((a, b) => new Date(b.created_at || 0) - new Date(a.created_at || 0))[0] || null
        })
        .catch(() => {
          weakReminder.value = null
        })
    })
}

const onChange = (val) => {
  if (!seatRegionId.value) {
    ElMessage.error('未找到可用座位防区，请先在防区配置中创建 seat 类型防区')
    return
  }
  switchSeatStatus({ user_id: 1001, region_id: seatRegionId.value, status: val })
    .then(() => {
      tip.value = val === 'studying'
        ? '已切换为自习中，疲劳弱提醒将继续私有展示。'
        : '已切换为休息中，疲劳提醒已暂停。'
      loadWeakReminders()
    })
    .catch(() => {
      ElMessage.error('状态切换失败')
    })
}

const formatTime = (value) => {
  if (!value) return '-'
  return new Date(value).toLocaleString()
}

const fatigueKindText = (kind) => {
  if (kind === 'yawn') return '检测到打哈欠'
  if (kind === 'sleepy') return '检测到闭眼疲劳'
  return '疲劳提醒'
}

const fatigueMessage = (item) => {
  const extra = item?.extra || {}
  const metrics = []
  if (extra.ear !== undefined) metrics.push(`EAR ${extra.ear}`)
  if (extra.mar !== undefined) metrics.push(`MAR ${extra.mar}`)
  if (extra.closed_duration !== undefined) metrics.push(`闭眼 ${extra.closed_duration}s`)
  return metrics.length ? `请注意休息。${metrics.join('，')}` : '请注意休息，避免过度疲劳。'
}

onMounted(() => {
  resolveSeatRegion()
  setTimeout(loadWeakReminders, 300)
  pollTimer = setInterval(loadWeakReminders, 5000)
})

onUnmounted(() => {
  if (pollTimer) {
    clearInterval(pollTimer)
  }
})
</script>

<style scoped>
.seat-companion {
  min-height: 100%;
  padding: 24px;
}

.panel-card {
  background: #fff;
  border-radius: 16px;
  padding: 24px;
  box-shadow: 0 14px 36px rgba(55, 52, 48, 0.08);
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.panel-header h2 {
  margin: 0 0 6px;
  color: #303133;
}

.panel-header p {
  margin: 0;
  color: #909399;
}

.status-card {
  border-radius: 12px;
  padding: 16px 18px;
  margin-bottom: 16px;
  color: #fff;
}

.status-card.studying {
  background: linear-gradient(135deg, #67c23a 0%, #95d475 100%);
}

.status-card.resting {
  background: linear-gradient(135deg, #e6a23c 0%, #f3c96e 100%);
}

.status-title {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 4px;
}

.status-hint {
  font-size: 14px;
  opacity: 0.95;
}

.weak-reminder-card {
  border: 1px solid #f6d49f;
  border-radius: 12px;
  padding: 16px;
  background: #fff8ea;
  color: #a15a00;
}

.weak-badge {
  display: inline-block;
  padding: 4px 10px;
  border-radius: 999px;
  background: #fef0d0;
  font-size: 12px;
  font-weight: 600;
  margin-bottom: 8px;
}

.weak-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 6px;
}

.weak-message {
  margin-bottom: 6px;
}

.weak-meta {
  font-size: 12px;
  color: #9b6b20;
}

.empty-state {
  padding: 18px;
  border-radius: 12px;
  background: #f5f7fa;
  color: #909399;
}

.config-warning {
  margin-top: 12px;
  padding: 12px 14px;
  border: 1px solid #f3d19e;
  border-radius: 8px;
  background: #fdf6ec;
  color: #b88230;
  font-size: 13px;
}
</style>
