import { defineStore } from 'pinia'

export const MAX_ALARMS = 100

// Alarm history and currently occupied regions are intentionally separate.
export const useAlarmStore = defineStore('alarm', {
  state: () => ({
    alarms: [],
    activeRegions: {}, // { regionId: 'green' | 'red' }
    activeTrackKeys: {} // { regionId: { [trackKey]: true } }
  }),
  actions: {
    loadAlarms(alarms) {
      // A historical, unconfirmed alarm does not prove that the person is
      // still in the region. Live state comes from the alarm WebSocket.
      this.alarms = Array.isArray(alarms) ? alarms.slice(0, MAX_ALARMS) : []
    },
    push(alarm) {
      this.alarms.unshift(alarm)
      if (this.alarms.length > MAX_ALARMS) {
        this.alarms.length = MAX_ALARMS
      }
      if (this.isRegionAlarm(alarm) && alarm.level !== 0) {
        this.activateRegionTrack(alarm.region_id, alarm.extra?.track_key || `alarm-${alarm.id}`)
      }
    },
    confirm(id) {
      const alarm = this.alarms.find((x) => x.id === id)
      if (alarm) alarm.status = 'confirmed'
    },
    update(id, updates) {
      const alarm = this.alarms.find((x) => x.id === id)
      if (alarm) Object.assign(alarm, updates)
    },
    isRegionAlarm(alarm) {
      return alarm?.type === 'intrusion' || alarm?.type === 'occupy'
    },
    activateRegionTrack(regionId, trackKey) {
      if (regionId === undefined || regionId === null || !trackKey) return
      const key = String(regionId)
      this.activeTrackKeys[key] ||= {}
      this.activeTrackKeys[key][trackKey] = true
      this.activeRegions[regionId] = 'red'
    },
    clearRegionTrack(regionId, trackKey) {
      const key = String(regionId)
      if (this.activeTrackKeys[key] && trackKey) {
        delete this.activeTrackKeys[key][trackKey]
      }
      if (!this.activeTrackKeys[key] || Object.keys(this.activeTrackKeys[key]).length === 0) {
        delete this.activeTrackKeys[key]
        this.activeRegions[regionId] = 'green'
      }
    },
    replaceActiveRegionTracks(states) {
      this.activeTrackKeys = {}
      Object.keys(this.activeRegions).forEach((regionId) => {
        this.activeRegions[regionId] = 'green'
      })
      ;(Array.isArray(states) ? states : []).forEach((state) => {
        if (state?.alarm_type === 'intrusion' || state?.alarm_type === 'occupy') {
          this.activateRegionTrack(state.region_id, state.track_key)
        }
      })
    },
    initRegions(regionIds) {
      regionIds.forEach((id) => {
        if (!this.activeRegions[id]) this.activeRegions[id] = 'green'
      })
    }
  }
})
