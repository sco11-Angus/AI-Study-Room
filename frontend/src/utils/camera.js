const STORAGE_KEY = 'ai-study-room:selected-camera-id'

export const DEFAULT_CAMERA_ID = 6

export function getSelectedCameraId() {
  const saved = Number.parseInt(window.localStorage.getItem(STORAGE_KEY), 10)
  return Number.isInteger(saved) && saved >= 0 ? saved : DEFAULT_CAMERA_ID
}

export function setSelectedCameraId(cameraId) {
  const value = Number(cameraId)
  if (Number.isInteger(value) && value >= 0) {
    window.localStorage.setItem(STORAGE_KEY, String(value))
  }
}

export function ensureSelectedCamera(cameras = []) {
  const selectedCameraId = getSelectedCameraId()
  const list = Array.isArray(cameras) ? [...cameras] : []
  if (!list.some((camera) => Number(camera.id) === selectedCameraId)) {
    list.unshift({ id: selectedCameraId, name: `摄像头 ${selectedCameraId}` })
  }
  return list
}
