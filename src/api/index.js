import axios from 'axios'
import { ElMessage } from 'element-plus'

const http = axios.create({ baseURL: '/api', timeout: 8000 })

// 响应拦截器：统一解包 {code, message, data}
http.interceptors.response.use(
  (response) => {
    const { code, message, data } = response.data
    if (code !== 0) {
      ElMessage.error(message || '请求失败')
      return Promise.reject(new Error(message))
    }
    return data
  },
  (error) => {
    ElMessage.error(error.message || '网络错误')
    return Promise.reject(error)
  }
)

// §9 接口封装
export const getCameras = () => http.get('/cameras')
export const getRegions = (cameraId) => http.get('/regions', { params: { camera_id: cameraId } })
export const createRegion = (data) => http.post('/regions', data)
export const updateRegion = (id, data) => http.put(`/regions/${id}`, data)
export const deleteRegion = (id) => http.delete(`/regions/${id}`)
export const switchSeatStatus = (data) => http.post('/seat-status', data)
export const getAlarms = (status) => http.get('/alarms', { params: { status } })
export const confirmAlarm = (id) => http.post(`/alarms/${id}/confirm`)

export default http
