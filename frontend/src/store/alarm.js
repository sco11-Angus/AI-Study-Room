import { defineStore } from 'pinia'

// 告警全局状态 (§7.3)
export const useAlarmStore = defineStore('alarm', {
  state: () => ({ alarms: [], activeRegions: {} }),
  actions: {
    push(alarm) {
      this.alarms.unshift(alarm)
      this.activeRegions[alarm.region_id] = 'red' // 格子转红闪烁
    },
    confirm(id) {
      const a = this.alarms.find((x) => x.id === id)
      if (a) a.status = 'confirmed'
    }
  }
})
