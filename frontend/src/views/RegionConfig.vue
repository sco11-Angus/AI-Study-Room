<template>
  <!-- 防区配置：视频流上叠加 Canvas 勾勒多边形 (§5.1, §5.2) -->
  <div class="region-config">
    <div class="region-left">
      <CanvasDraw :stream-url="streamUrl" :preview-polygon="selectedPolygon" @polygon="onPolygon" />
      <div class="tip-box">双击闭合路径后，当前多边形会记录为归一化坐标，点击表格“回显”可加载已有防区。</div>
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
        <el-form-item label="安全距离(px)">
          <el-input-number v-model="form.x_distance" :min="0" />
        </el-form-item>
        <el-form-item label="停留时间(s)">
          <el-input-number v-model="form.y_stay_time" :min="0" />
        </el-form-item>
        <el-form-item label="归一化多边形">
          <div class="polygon-preview">
            <div v-if="form.polygon.length">{{ form.polygon.length }} 个点，已归一化到 [0,1]</div>
            <div v-else class="empty-state">请先在视频上画一个多边形并双击闭合</div>
          </div>
        </el-form-item>
        <el-form-item v-if="selectedRegionId && form.type === 'seat'" label="预约成员">
          <div class="reservation-control">
            <el-select v-model="selectedReservationMemberId" placeholder="选择已录入人脸的成员" clearable>
              <el-option
                v-for="member in members"
                :key="member.member_id"
                :label="`${member.name} (#${member.member_id})`"
                :value="member.member_id"
              />
            </el-select>
            <el-button type="primary" :disabled="!selectedReservationMemberId" @click="bindReservation">绑定</el-button>
            <el-button v-if="selectedReservation" type="danger" @click="unbindReservation">解绑</el-button>
          </div>
          <div v-if="selectedReservation" class="reservation-hint">
            当前绑定：{{ selectedReservation.member_name }} (#{{ selectedReservation.member_id }})
          </div>
          <div v-else class="reservation-hint">未绑定预约成员，不进行座位身份核验。</div>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" @click="submit">{{ selectedRegionId ? '更新防区' : '提交并持久化' }}</el-button>
          <el-button type="default" @click="clearSelection" v-if="selectedRegionId">取消回显</el-button>
        </el-form-item>
      </el-form>

      <div class="region-list-section">
        <div class="region-list-header">
          <span>已保存防区</span>
          <span v-if="regions.length">共 {{ regions.length }} 条</span>
          <span v-else>当前摄像头暂无防区</span>
        </div>
        <el-table v-if="regions.length" :data="regions" stripe style="width: 100%">
          <el-table-column prop="name" label="名称" />
          <el-table-column prop="type" label="类型" />
          <el-table-column prop="x_distance" label="X_distance" width="110" />
          <el-table-column prop="y_stay_time" label="Y_stay_time" width="110" />
          <el-table-column label="预约成员" min-width="150">
            <template #default="{ row }">
              <template v-if="row.type === 'seat'">
                {{ reservationLabel(row.id) }}
              </template>
              <template v-else>-</template>
            </template>
          </el-table-column>
          <el-table-column label="操作" width="230">
            <template #default="{ row }">
              <el-button type="text" size="small" @click="selectRegion(row)">回显</el-button>
              <el-button v-if="row.type === 'seat'" type="text" size="small" @click="selectRegion(row)">配置预约</el-button>
              <el-button type="text" size="small" @click="removeRegion(row.id)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref, onMounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import CanvasDraw from '../components/CanvasDraw.vue'
import {
  createRegion,
  deleteRegion,
  deleteSeatReservation,
  getCameras,
  getMembers,
  getRegions,
  getSeatReservations,
  updateRegion,
  upsertSeatReservation,
} from '../api'
import { ensureSelectedCamera, getSelectedCameraId, setSelectedCameraId } from '../utils/camera'

const DEFAULT_STREAM_URL = ''
const streamUrl = ref(DEFAULT_STREAM_URL)
const cameras = ref([])
const regions = ref([])
const selectedPolygon = ref([])
const selectedRegionId = ref(null)
const members = ref([])
const reservations = ref({})
const selectedReservationMemberId = ref(null)
const form = ref({ camera_id: getSelectedCameraId(), name: '', type: 'danger_zone', polygon: [], x_distance: 50, y_stay_time: 10 })

const selectedReservation = computed(() => reservations.value[selectedRegionId.value] || null)

// 与监测大屏一致：走后端 /ws/video_feed WebSocket 拿实时帧（VideoPlayer 解析 camera_id=）
const resolveStreamUrl = (cameraId) => {
  if (!cameraId && cameraId !== 0) return DEFAULT_STREAM_URL
  return `camera_id=${cameraId}`
}

const loadCameras = () => {
  getCameras()
    .then((list) => {
      cameras.value = ensureSelectedCamera(list)
      streamUrl.value = resolveStreamUrl(form.value.camera_id)
      fetchRegions(form.value.camera_id)
    })
    .catch(() => {
      cameras.value = []
    })
}

const loadReservations = (cameraId) => getSeatReservations(cameraId)
  .then((reservationList) => {
    reservations.value = (Array.isArray(reservationList) ? reservationList : []).reduce((byRegion, item) => {
      byRegion[item.region_id] = item
      return byRegion
    }, {})
  })

const fetchRegions = (cameraId, preferredRegionId = selectedRegionId.value) => {
  if (cameraId === null || cameraId === undefined) {
    regions.value = []
    return Promise.resolve([])
  }
  return Promise.all([getRegions(cameraId), loadReservations(cameraId)])
    .then(([list]) => {
      regions.value = Array.isArray(list) ? list : []
      const preferred = regions.value.find((region) => region.id === preferredRegionId)
      const onlySeat = regions.value.filter((region) => region.type === 'seat')
      const regionToSelect = preferred || (onlySeat.length === 1 ? onlySeat[0] : null)

      if (regionToSelect) {
        selectRegion(regionToSelect)
      } else {
        selectedRegionId.value = null
        selectedPolygon.value = []
        selectedReservationMemberId.value = null
      }
      return regions.value
    })
    .catch(() => {
      regions.value = []
      reservations.value = {}
    })
}

watch(
  () => form.value.camera_id,
  (cameraId) => {
    if (cameraId === null || cameraId === undefined) return
    setSelectedCameraId(cameraId)
    streamUrl.value = resolveStreamUrl(cameraId)
    fetchRegions(cameraId)
    clearSelection()
  }
)

onMounted(() => {
  loadCameras()
  getMembers().then((list) => {
    members.value = Array.isArray(list) ? list : []
  }).catch(() => {
    members.value = []
  })
})

const onPolygon = (pts) => {
  form.value.polygon = pts
  selectedPolygon.value = pts
}

const selectRegion = (region) => {
  selectedRegionId.value = region.id
  form.value = {
    camera_id: region.camera_id,
    name: region.name,
    type: region.type,
    polygon: region.polygon,
    x_distance: region.x_distance || 0,
    y_stay_time: region.y_stay_time || 0,
  }
  selectedPolygon.value = region.polygon
  selectedReservationMemberId.value = reservations.value[region.id]?.member_id || null
}

const reservationLabel = (regionId) => {
  const reservation = reservations.value[regionId]
  return reservation ? `${reservation.member_name} (#${reservation.member_id})` : '未绑定，点击配置预约'
}

const clearSelection = () => {
  selectedRegionId.value = null
  selectedPolygon.value = []
  selectedReservationMemberId.value = null
  form.value.polygon = []
}

const submit = () => {
  if (form.value.camera_id === null || form.value.camera_id === undefined) {
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

  const action = selectedRegionId.value
    ? updateRegion(selectedRegionId.value, form.value)
    : createRegion(form.value)

  action
    .then((savedRegion) => {
      ElMessage.success(selectedRegionId.value ? '防区已更新' : '防区已提交')
      const savedSeatId = savedRegion?.type === 'seat' ? savedRegion.id : null
      return fetchRegions(form.value.camera_id, savedSeatId || selectedRegionId.value)
        .then(() => savedSeatId)
    })
    .then((savedSeatId) => {
      if (!savedSeatId && !selectedRegionId.value) {
        form.value.name = ''
        form.value.type = 'danger_zone'
        form.value.polygon = []
        form.value.x_distance = 50
        form.value.y_stay_time = 10
        selectedPolygon.value = []
      }
    })
    .catch(() => {
      /* 错误消息由拦截器处理 */
    })
}

const removeRegion = (regionId) => {
  deleteRegion(regionId)
    .then(() => {
      ElMessage.success('防区已删除')
      fetchRegions(form.value.camera_id)
    })
    .catch(() => {})
}

const bindReservation = () => {
  if (!selectedRegionId.value || !selectedReservationMemberId.value) return
  upsertSeatReservation(selectedRegionId.value, selectedReservationMemberId.value)
    .then(() => {
      ElMessage.success('预约成员已绑定，身份核验已热更新')
      return loadReservations(form.value.camera_id)
    })
    .catch(() => {})
}

const unbindReservation = () => {
  if (!selectedRegionId.value) return
  deleteSeatReservation(selectedRegionId.value)
    .then(() => {
      ElMessage.success('预约成员已解绑，座位身份核验已停止')
      return loadReservations(form.value.camera_id).then(() => {
        selectedReservationMemberId.value = null
      })
    })
    .catch(() => {})
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

.reservation-control {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.reservation-control :deep(.el-select) {
  min-width: 220px;
}

.reservation-hint {
  width: 100%;
  margin-top: 8px;
  color: #606266;
  font-size: 13px;
}
</style>
