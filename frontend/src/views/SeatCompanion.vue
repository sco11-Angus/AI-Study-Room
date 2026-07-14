<template>
  <div class="seat-companion">
    <section class="page-header">
      <div>
        <h2>自习伴侣</h2>
        <p>为当前座位提供疲劳提醒；疲劳记录会留存并发送钉钉，但不会触发监控大屏红闪。</p>
      </div>
      <el-tag :type="streamOnline ? 'success' : 'danger'">{{ streamOnline ? '视频流在线' : '视频流未就绪' }}</el-tag>
    </section>

    <div class="companion-layout">
      <section class="session-panel">
        <h3>本次自习</h3>
        <el-form label-position="top">
          <div class="form-grid">
            <el-form-item label="摄像头">
              <el-select v-model="cameraId" placeholder="选择摄像头" @change="onCameraChanged">
                <el-option v-for="camera in cameras" :key="camera.id" :label="camera.name || `摄像头 ${camera.id}`" :value="camera.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="座位">
              <el-select v-model="regionId" placeholder="选择座位" @change="onSeatChanged">
                <el-option v-for="seat in seats" :key="seat.id" :label="seat.name || `座位 ${seat.id}`" :value="seat.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="演示用户 ID">
              <el-input-number v-model="userId" :min="1" :controls="false" @change="loadCompanion" />
            </el-form-item>
            <el-form-item label="检测模式">
              <el-radio-group v-model="mode" @change="onModeChanged">
                <el-radio-button value="demo">演示模式</el-radio-button>
                <el-radio-button value="verified">身份核验</el-radio-button>
              </el-radio-group>
            </el-form-item>
          </div>
          <el-form-item v-if="mode === 'verified'" label="已录入人脸的预约成员">
            <el-select v-model="memberId" placeholder="选择预约成员">
              <el-option v-for="member in members" :key="member.member_id" :label="`${member.name || '成员'} (#${member.member_id})`" :value="member.member_id" />
            </el-select>
            <div class="field-hint">{{ reservationHint }}</div>
          </el-form-item>
          <el-form-item label="自习状态">
            <el-radio-group v-model="status">
              <el-radio-button value="idle">空闲</el-radio-button>
              <el-radio-button value="studying">开始自习</el-radio-button>
              <el-radio-button value="resting">休息中</el-radio-button>
            </el-radio-group>
          </el-form-item>
          <el-button type="primary" :loading="saving" :disabled="!regionId" @click="saveSession">更新本次自习</el-button>
        </el-form>
      </section>

      <section class="state-panel">
        <div class="state-heading">
          <h3>检测状态</h3>
          <el-tag :type="runtime.eligible ? 'success' : 'info'">{{ runtime.eligible ? '检测中' : '已暂停' }}</el-tag>
        </div>
        <dl class="state-list">
          <div><dt>当前状态</dt><dd>{{ statusLabel(status) }}</dd></div>
          <div><dt>模式</dt><dd>{{ mode === 'verified' ? '身份核验' : '演示模式' }}</dd></div>
          <div><dt>预约成员</dt><dd>{{ reservation?.member_name || '未绑定' }}</dd></div>
          <div><dt>运行说明</dt><dd>{{ reasonLabel(runtime.reason) }}</dd></div>
          <div v-if="runtime.face_match"><dt>人脸结果</dt><dd>{{ runtime.face_match }}</dd></div>
        </dl>
        <div v-if="!dingtalkConfigured" class="config-warning">钉钉 Webhook 未配置：疲劳提醒仍会显示在这里，但不会外发到钉钉。</div>
      </section>
    </div>

    <section class="reminder-panel">
      <div class="state-heading">
        <h3>最近疲劳提醒</h3>
        <span class="reminder-note">实时提醒仅属于当前选择的自习会话</span>
      </div>
      <div v-if="reminder" class="reminder-card">
        <el-tag type="warning">{{ fatigueKindText(reminder.extra?.kind) }}</el-tag>
        <strong>{{ fatigueMessage(reminder) }}</strong>
        <span>{{ formatTime(reminder.created_at) }}</span>
      </div>
      <el-empty v-else description="当前会话还没有疲劳提醒" :image-size="72" />
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  getCameraStreamStatus, getCameras, getMembers, getRegions, getSeatCompanionStatus,
  getSeatReservations, switchSeatStatus,
} from '../api'

const cameras = ref([])
const seats = ref([])
const members = ref([])
const reservations = ref([])
const cameraId = ref(null)
const regionId = ref(null)
const userId = ref(1001)
const memberId = ref(null)
const mode = ref('demo')
const status = ref('idle')
const runtime = ref({ eligible: false, reason: 'not_studying' })
const reminder = ref(null)
const dingtalkConfigured = ref(false)
const streamOnline = ref(false)
const saving = ref(false)
let companionWs = null
let pollTimer = null

const reservation = computed(() => reservations.value.find((item) => item.region_id === regionId.value) || null)
const reservationHint = computed(() => reservation.value
  ? `此座位预约给 ${reservation.value.member_name} (#${reservation.value.member_id})。身份核验模式必须选择该成员。`
  : '该座位没有有效预约，无法启动身份核验模式。')

const loadSeats = async () => {
  if (cameraId.value === null) return
  const [regionList, reservationList] = await Promise.all([getRegions(cameraId.value), getSeatReservations(cameraId.value)])
  seats.value = (Array.isArray(regionList) ? regionList : []).filter((region) => region.type === 'seat')
  reservations.value = Array.isArray(reservationList) ? reservationList : []
  if (!seats.value.some((seat) => seat.id === regionId.value)) regionId.value = null
}

const loadStream = async () => {
  if (cameraId.value === null) return
  try {
    const data = await getCameraStreamStatus(cameraId.value)
    streamOnline.value = !!data.online && !!data.has_frame
  } catch {
    streamOnline.value = false
  }
}

const loadCompanion = async () => {
  if (!regionId.value || !userId.value) return
  try {
    const data = await getSeatCompanionStatus(userId.value, regionId.value)
    status.value = data.status || 'idle'
    mode.value = data.mode || 'demo'
    memberId.value = data.member_id || null
    runtime.value = data.runtime || { eligible: false, reason: 'not_studying' }
    reminder.value = data.latest_fatigue || null
    dingtalkConfigured.value = !!data.dingtalk_configured
    streamOnline.value = !!data.stream_online
    connectCompanionWs()
  } catch {
    runtime.value = { eligible: false, reason: 'session_unavailable' }
  }
}

const onCameraChanged = async () => {
  regionId.value = null
  await loadSeats()
  await loadStream()
}

const onSeatChanged = async () => {
  const currentReservation = reservation.value
  if (mode.value === 'verified' && currentReservation) memberId.value = currentReservation.member_id
  await loadCompanion()
}

const onModeChanged = (value) => {
  if (value === 'verified' && reservation.value) memberId.value = reservation.value.member_id
}

const saveSession = async () => {
  if (!regionId.value) return
  saving.value = true
  try {
    await switchSeatStatus({ user_id: userId.value, region_id: regionId.value, status: status.value, mode: mode.value, member_id: memberId.value })
    ElMessage.success('自习会话已更新')
    await loadCompanion()
  } finally {
    saving.value = false
  }
}

const connectCompanionWs = () => {
  if (!regionId.value || !userId.value) return
  if (companionWs) companionWs.close()
  const protocol = location.protocol === 'https:' ? 'wss' : 'ws'
  companionWs = new WebSocket(`${protocol}://${location.host}/ws/companion?user_id=${userId.value}&region_id=${regionId.value}`)
  companionWs.onmessage = ({ data }) => {
    const event = JSON.parse(data)
    if (event.type === 'fatigue') {
      reminder.value = event
      ElMessage.warning(fatigueKindText(event.extra?.kind))
    }
  }
}

const statusLabel = (value) => ({ idle: '空闲', studying: '自习中', resting: '休息中' }[value] || '未知')
const reasonLabel = (value) => ({
  detecting: '座位内已确认唯一对象，正在检测', demo_ready: '演示模式已准备', waiting_for_face: '等待座位内人脸',
  no_in_seat_face: '未检测到座位内人脸', ambiguous_face: '座位内存在多人，已暂停',
  identity_verified: '预约成员身份已通过', identity_mismatch: '人脸与预约成员不匹配',
  reservation_mismatch: '会话成员与预约不一致', not_studying: '当前座位未处于自习中',
  engine_unavailable: '推理引擎未就绪', session_unavailable: '无法读取当前会话',
}[value] || '等待状态更新')
const fatigueKindText = (kind) => kind === 'yawn' ? '检测到打哈欠' : kind === 'sleepy' ? '检测到闭眼疲劳' : '疲劳提醒'
const fatigueMessage = (item) => {
  const extra = item?.extra || {}
  const metrics = [`EAR ${extra.ear ?? '-'}`, `MAR ${extra.mar ?? '-'}`]
  if (extra.closed_duration !== undefined) metrics.push(`闭眼 ${extra.closed_duration}s`)
  return `请注意休息，${metrics.join('，')}`
}
const formatTime = (value) => value ? new Date(value).toLocaleString() : '-'

watch([cameraId, regionId, userId], () => loadCompanion())
onMounted(async () => {
  const cameraList = await getCameras()
  cameras.value = Array.isArray(cameraList) ? cameraList : []
  cameraId.value = cameras.value[0]?.id ?? null
  await loadSeats()
  await loadStream()
  await loadCompanion()
  pollTimer = setInterval(() => { loadCompanion(); loadStream() }, 5000)
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
  if (companionWs) companionWs.close()
})
</script>

<style scoped>
.seat-companion { min-height: 100%; color: #303133; }
.page-header, .state-heading { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.page-header { margin-bottom: 20px; }
.page-header h2, h3 { margin: 0; }
.page-header p, .reminder-note, .field-hint { color: #909399; font-size: 13px; }
.companion-layout { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .85fr); gap: 20px; }
.session-panel, .state-panel, .reminder-panel { background: #fff; border: 1px solid #ebeef5; border-radius: 8px; padding: 20px; }
.session-panel h3, .state-panel h3 { margin-bottom: 18px; }
.form-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0 16px; }
.field-hint { margin-top: 8px; line-height: 1.5; }
.state-list { margin: 18px 0 0; }
.state-list > div { display: flex; justify-content: space-between; gap: 16px; padding: 10px 0; border-top: 1px solid #f2f3f5; }
.state-list dt { color: #909399; } .state-list dd { margin: 0; text-align: right; }
.config-warning { margin-top: 16px; padding: 10px 12px; background: #fdf6ec; border: 1px solid #f3d19e; color: #b88230; font-size: 13px; }
.reminder-panel { margin-top: 20px; }
.reminder-card { display: flex; align-items: center; gap: 14px; padding: 16px; margin-top: 14px; background: #fff8ea; border-left: 4px solid #e6a23c; }
.reminder-card span:last-child { margin-left: auto; color: #909399; font-size: 13px; }
@media (max-width: 900px) { .companion-layout, .form-grid { grid-template-columns: 1fr; } .page-header { align-items: flex-start; flex-direction: column; } }
</style>
