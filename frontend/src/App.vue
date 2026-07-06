<template>
  <el-container style="height: 100vh">
    <el-aside width="200px">
      <el-menu :default-active="$route.path" router>
        <el-menu-item index="/dashboard">告警监测大屏</el-menu-item>
        <el-menu-item index="/regions">防区配置</el-menu-item>
        <el-menu-item index="/companion">自习伴侣</el-menu-item>
        <el-menu-item index="/stream">实时视频流</el-menu-item>
      </el-menu>
    </el-aside>
    <el-main><router-view /></el-main>
  </el-container>
</template>

<script setup></script>
