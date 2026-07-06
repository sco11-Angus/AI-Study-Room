<template>
  <div class="video-stream-viewer">
    <h2>实时视频流</h2>

    <div class="controls">
      <label>流名称：</label>
      <input
        v-model="selectedStream"
        type="text"
        placeholder="输入推流名称，如 test"
        class="stream-input"
      />
      <button @click="refreshStream" class="btn-refresh">刷新</button>
      <span class="hint" v-if="selectedStream">当前播放：{{ selectedStream }}</span>
    </div>

    <div class="video-container">
      <img
        :src="videoFeedUrl"
        alt="Video Stream"
        class="video-feed"
        @error="handleImageError"
      />
      <div v-if="error" class="error-overlay">
        {{ error }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, nextTick } from "vue";

const selectedStream = ref("test");
const error = ref("");

const videoFeedBaseUrl = "http://localhost:5000/video_feed/";
const streamKey = ref(0); // 每次刷新改变 key，强制 <img> 重新加载

const videoFeedUrl = computed(() => {
  return `${videoFeedBaseUrl}${selectedStream.value}?t=${streamKey.value}`;
});

const refreshStream = () => {
  error.value = "";
  streamKey.value++;
};

const handleImageError = () => {
  error.value = `流 "${selectedStream.value}" 暂不可用，请确认 RTMP 推流已启动。`;
};
</script>

<style scoped>
.video-stream-viewer {
  padding: 20px;
  max-width: 960px;
  margin: 0 auto;
}

h2 {
  margin-bottom: 16px;
  color: #303133;
}

.controls {
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 12px;
}

.controls label {
  font-weight: bold;
  color: #606266;
}

.controls input {
  padding: 6px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-size: 14px;
  width: 160px;
}

.controls select {
  padding: 6px 12px;
  border: 1px solid #dcdfe6;
  border-radius: 4px;
  font-size: 14px;
}

.btn-refresh {
  padding: 6px 16px;
  background: #409eff;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}
.btn-refresh:hover {
  background: #337ecc;
}

.hint {
  color: #909399;
  font-size: 13px;
}

.video-container {
  position: relative;
  border: 2px solid #e4e7ed;
  border-radius: 8px;
  overflow: hidden;
  background: #000;
  min-height: 360px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.video-feed {
  width: 100%;
  max-width: 960px;
  display: block;
}

.error-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  color: #f56c6c;
  background: rgba(0, 0, 0, 0.7);
  padding: 12px 24px;
  border-radius: 6px;
  font-size: 14px;
}
</style>
