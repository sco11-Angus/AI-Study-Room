import { defineStore } from 'pinia'

// 告警全局状态 (§7.3)
export const useAlarmStore = defineStore('alarm', {
  state: () => ({
    alarms: [],
    activeRegions: {} // { regionId: 'green' | 'red' }
  }),
  actions: {
    // 加载历史告警，并为存在未确认的高等级告警设置红色状态
    loadAlarms(alarms) {
      this.alarms = Array.isArray(alarms) ? alarms.slice() : []
      this.alarms.forEach((alarm) => {
        if (alarm.level !== 0 && alarm.status !== 'confirmed') {
          this.activeRegions[alarm.region_id] = 'red'
        }
      })
    },
    // 添加告警，对应格子转红闪烁
    push(alarm) {
      this.alarms.unshift(alarm)
      if (alarm.level !== 0) { // level=0 疲劳弱提醒不红闪
        this.activeRegions[alarm.region_id] = 'red'
      }
    },
    // 确认告警，格子恢复绿色
    confirm(id) {
      const alarm = this.alarms.find((x) => x.id === id)
      if (alarm) {
        alarm.status = 'confirmed'
        this.activeRegions[alarm.region_id] = 'green'
      }
    },
    // 初始化防区颜色（全部绿色）
    initRegions(regionIds) {
      regionIds.forEach(id => {
        this.activeRegions[id] = 'green'
      })
    }
  }
})
