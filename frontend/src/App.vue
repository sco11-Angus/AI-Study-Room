<template>
  <div class="app-container">
    <el-container style="height: 100vh">
      <el-aside width="240px" class="sidebar">
        <div class="logo">
          <div class="logo-icon">📚</div>
          <div class="logo-text">智慧自习室</div>
        </div>
        <el-menu
          :default-active="$route.path"
          router
          class="sidebar-menu"
          background-color="transparent"
          text-color="#5d4e37"
          active-text-color="#d4a574"
        >
          <el-menu-item index="/dashboard">
            <span class="menu-icon">📊</span>
            <span>告警监测大屏</span>
          </el-menu-item>
          <el-menu-item index="/regions">
            <span class="menu-icon">🎯</span>
            <span>防区配置</span>
          </el-menu-item>
          <el-menu-item index="/companion">
            <span class="menu-icon">💼</span>
            <span>自习伴侣</span>
          </el-menu-item>
          <el-menu-item index="/stream">
            <span class="menu-icon">📹</span>
            <span>实时视频流</span>
          </el-menu-item>
          <el-menu-item index="/logs">
            <span class="menu-icon">📋</span>
            <span>告警日志</span>
          </el-menu-item>
        </el-menu>
      </el-aside>
      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </div>
</template>

<script setup></script>

<style>
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.app-container {
  background: linear-gradient(135deg, #fef9f3 0%, #f5e6d3 100%);
  min-height: 100vh;
}

.sidebar {
  background: linear-gradient(180deg, #fff9f0 0%, #fff5e6 100%);
  border-right: 1px solid #e8d5c4;
  box-shadow: 2px 0 8px rgba(212, 165, 116, 0.1);
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 24px 20px;
  margin-bottom: 20px;
  border-bottom: 1px solid #e8d5c4;
}

.logo-icon {
  font-size: 32px;
}

.logo-text {
  font-size: 20px;
  font-weight: 600;
  color: #5d4e37;
  letter-spacing: 1px;
}

.sidebar-menu {
  border: none;
}

.sidebar-menu .el-menu-item {
  height: 56px;
  line-height: 56px;
  margin: 8px 12px;
  border-radius: 12px;
  transition: all 0.3s ease;
  display: flex;
  align-items: center;
  gap: 12px;
}

.sidebar-menu .el-menu-item:hover {
  background: linear-gradient(135deg, #ffe8d6 0%, #ffd9c2 100%) !important;
  transform: translateX(4px);
}

.sidebar-menu .el-menu-item.is-active {
  background: linear-gradient(135deg, #d4a574 0%, #c49464 100%) !important;
  color: #fff !important;
  box-shadow: 0 4px 12px rgba(212, 165, 116, 0.3);
}

.menu-icon {
  font-size: 20px;
}

.main-content {
  background: transparent;
  padding: 24px;
}
</style>
