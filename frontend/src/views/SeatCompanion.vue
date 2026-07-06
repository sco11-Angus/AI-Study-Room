<template>
  <!-- 自习伴侣：状态宣告，激活/挂起疲劳算法 (§4) -->
  <div class="seat-companion">
    <el-radio-group v-model="status" @change="onChange">
      <el-radio-button value="studying">自习中</el-radio-button>
      <el-radio-button value="resting">休息中</el-radio-button>
    </el-radio-group>
    <p v-if="tip" class="weak-tip">{{ tip }}</p>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { switchSeatStatus } from '../api'

const status = ref('studying')
const tip = ref('') // 疲劳弱提醒（私有，不拉公用警报 §4.3）

const onChange = (val) => switchSeatStatus({ user_id: 1001, region_id: 5, status: val })
</script>

<style scoped>
.weak-tip { color: #e6a23c; }
</style>
