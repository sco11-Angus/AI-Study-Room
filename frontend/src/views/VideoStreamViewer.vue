<template>
  <div class="video-stream-viewer">
    <h2>实时视频流</h2>

    <div class="controls">
      <label>摄像头 ID：</label>
      <input
        v-model.number="cameraId"
        type="number"
        min="0"
        placeholder="摄像头 ID，如 0"
        class="stream-input"
      />
      <button @click="reconnect" class="btn-refresh">重连</button>
      <span class="hint" v-if="statusText">{{ statusText }}</span>
    </div>

    <div class="video-container">
      <img ref="imageEl" class="video-image" alt="实时视频流" />
      <div v-if="!streaming" class="overlay">
        <p>等待推流...</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch } from "vue";
import { getSelectedCameraId, setSelectedCameraId } from "../utils/camera";

const cameraId = ref(getSelectedCameraId());
const imageEl = ref(null);
const statusText = ref("");
const streaming = ref(false);

let ws = null;
let reconnectTimer = null;
let lastFrameTime = 0;
let rendering = false;
let currentFrameUrl = null;

const FRAME_INTERVAL = 1000 / 15;

const connect = () => {
  if (ws) {
    ws.close();
    ws = null;
  }

  const url = `ws://${location.host}/ws/video_feed/${cameraId.value}`;
  statusText.value = "连接中...";
  streaming.value = false;

  try {
    ws = new WebSocket(url);
    ws.binaryType = "blob";
  } catch (e) {
    statusText.value = "WebSocket 不支持";
    return;
  }

  ws.onopen = () => {
    statusText.value = "已连接";
  };

  ws.onmessage = (e) => {
    // JSON 状态消息
    if (typeof e.data === "string") {
      try {
        const msg = JSON.parse(e.data);
        if (msg.status === "offline") {
          statusText.value = "等待推流...";
          streaming.value = false;
        } else if (msg.status === "waiting") {
          statusText.value = "缓冲中...";
        } else if (msg.status === "no_camera" || msg.status === "no_scheduler") {
          statusText.value = "摄像头未就绪";
        }
      } catch (_) {}
      return;
    }

    // 二进制 JPEG 帧 → 渲染到 canvas
    if (e.data instanceof Blob) {
      const now = Date.now();
      if (rendering || now - lastFrameTime < FRAME_INTERVAL) return;
      lastFrameTime = now;
      rendering = true;
      renderFrame(e.data).finally(() => {
        rendering = false;
      });
    }
  };

  ws.onclose = () => {
    statusText.value = "已断开，3s 后重连...";
    streaming.value = false;
    scheduleReconnect();
  };

  ws.onerror = () => {
    // onclose 会紧随其后触发
  };
};

const renderFrame = async (blob) => {
  const image = imageEl.value;
  if (!image) return;
  const nextUrl = URL.createObjectURL(blob);
  await new Promise((resolve) => {
    image.onload = () => {
      if (currentFrameUrl) URL.revokeObjectURL(currentFrameUrl);
      currentFrameUrl = nextUrl;
      streaming.value = true;
      statusText.value = "";
      resolve();
    };
    image.onerror = () => {
      URL.revokeObjectURL(nextUrl);
      resolve();
    };
    image.src = nextUrl;
  });
};

const scheduleReconnect = () => {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, 3000);
};

const reconnect = () => {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  connect();
};

watch(cameraId, (selectedCameraId) => {
  setSelectedCameraId(selectedCameraId);
  reconnect();
});

onMounted(connect);

onUnmounted(() => {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  if (ws) ws.close();
  if (currentFrameUrl) URL.revokeObjectURL(currentFrameUrl);
});
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
  width: 80px;
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

.video-image {
  width: 100%;
  max-height: 70vh;
  object-fit: contain;
  display: block;
}

.overlay {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(0, 0, 0, 0.6);
  color: #ccc;
  font-size: 18px;
}
</style>
