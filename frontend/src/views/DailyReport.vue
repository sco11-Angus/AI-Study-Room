<template>
  <div class="daily-report">
    <div class="report-toolbar">
      <div class="toolbar-left">
        <h1>📊 AI 监控日报</h1>
      </div>
      <div class="toolbar-right">
        <el-date-picker v-model="selectedDate" type="date" placeholder="选择日期" />
        <el-button type="primary" @click="generateReport">生成日报</el-button>
        <el-button @click="exportMarkdown">导出 Markdown</el-button>
      </div>
    </div>

    <div v-if="loading" class="loading">
      <el-spinner />
      <p>正在生成日报...</p>
    </div>

    <div v-else-if="markdownContent" class="report-content">
      <div class="markdown-body" v-html="renderedMarkdown"></div>
    </div>

    <div v-else class="empty-state">
      <div class="empty-icon">📝</div>
      <p>点击「生成日报」按钮生成今日监控报告</p>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { marked } from 'marked'
import { ElMessage } from 'element-plus'

const selectedDate = ref(null)
const markdownContent = ref('')
const loading = ref(false)

marked.setOptions({
  breaks: true,
  gfm: true
})

const renderedMarkdown = computed(() => {
  if (!markdownContent.value) return ''
  return marked(markdownContent.value)
})

const generateReport = async () => {
  loading.value = true
  try {
    const date = selectedDate.value ? selectedDate.value.toISOString().split('T')[0] : ''
    const response = await fetch(`/api/alarms/daily-report?format=markdown${date ? '&date=' + date : ''}`)
    markdownContent.value = await response.text()
    ElMessage.success('日报生成成功')
  } catch (error) {
    ElMessage.error('生成日报失败：' + error.message)
  } finally {
    loading.value = false
  }
}

const exportMarkdown = async () => {
  if (!markdownContent.value) {
    ElMessage.warning('请先生成日报')
    return
  }
  const date = selectedDate.value ? selectedDate.value.toISOString().split('T')[0] : new Date().toISOString().split('T')[0]
  const blob = new Blob([markdownContent.value], { type: 'text/markdown' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `report_${date}.md`
  a.click()
  URL.revokeObjectURL(url)
  ElMessage.success('日报导出成功')
}
</script>

<style scoped>
.daily-report {
  max-width: 900px;
  margin: 0 auto;
  padding: 24px;
  background: #fff;
  min-height: 100vh;
}

.report-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 24px;
  padding-bottom: 16px;
  border-bottom: 2px solid #e8d5c4;
}

.toolbar-left h1 {
  margin: 0;
  font-size: 24px;
  color: #5d4e37;
}

.toolbar-right {
  display: flex;
  gap: 12px;
  align-items: center;
}

.loading {
  text-align: center;
  padding: 80px 0;
}

.loading p {
  margin-top: 16px;
  color: #8b7b68;
}

.empty-state {
  text-align: center;
  padding: 100px 0;
  color: #909399;
}

.empty-icon {
  font-size: 64px;
  margin-bottom: 16px;
}

.report-content {
  background: #fff;
}

.markdown-body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'Noto Sans', Helvetica, Arial, sans-serif;
  font-size: 15px;
  line-height: 1.6;
  color: #24292f;
  word-wrap: break-word;
}

.markdown-body h1 {
  font-size: 2em;
  padding-bottom: 0.3em;
  border-bottom: 1px solid #d0d7de;
  margin-top: 0;
  margin-bottom: 24px;
  font-weight: 600;
}

.markdown-body h2 {
  font-size: 1.5em;
  padding-bottom: 0.3em;
  border-bottom: 1px solid #d0d7de;
  margin-top: 24px;
  margin-bottom: 16px;
  font-weight: 600;
}

.markdown-body h3 {
  font-size: 1.25em;
  margin-top: 24px;
  margin-bottom: 16px;
  font-weight: 600;
}

.markdown-body p {
  margin-top: 0;
  margin-bottom: 16px;
}

.markdown-body ul,
.markdown-body ol {
  padding-left: 2em;
  margin-top: 0;
  margin-bottom: 16px;
}

.markdown-body li {
  margin-top: 0.25em;
}

.markdown-body li > p {
  margin-top: 16px;
}

.markdown-body li + li {
  margin-top: 0.25em;
}

.markdown-body blockquote {
  padding: 0 1em;
  color: #57606a;
  border-left: 0.25em solid #d0d7de;
  margin: 0 0 16px 0;
}

.markdown-body blockquote > :first-child {
  margin-top: 0;
}

.markdown-body blockquote > :last-child {
  margin-bottom: 0;
}

.markdown-body table {
  border-spacing: 0;
  border-collapse: collapse;
  margin-bottom: 16px;
  width: 100%;
}

.markdown-body table th {
  font-weight: 600;
}

.markdown-body table th,
.markdown-body table td {
  padding: 6px 13px;
  border: 1px solid #d0d7de;
}

.markdown-body table tr:nth-child(2n) {
  background-color: #f6f8fa;
}

.markdown-body code {
  padding: 0.2em 0.4em;
  font-size: 85%;
  background-color: rgba(175, 184, 193, 0.2);
  border-radius: 6px;
  font-family: ui-monospace, SFMono-Regular, SF Mono, Menlo, Consolas, Liberation Mono, monospace;
}

.markdown-body pre {
  padding: 16px;
  overflow: auto;
  font-size: 85%;
  line-height: 1.45;
  background-color: #f6f8fa;
  border-radius: 6px;
  margin-bottom: 16px;
}

.markdown-body pre code {
  padding: 0;
  background-color: transparent;
  border-radius: 0;
}

.markdown-body hr {
  height: 0.25em;
  padding: 0;
  margin: 24px 0;
  background-color: #d0d7de;
  border: 0;
}

.markdown-body strong {
  font-weight: 600;
}

.markdown-body em {
  font-style: italic;
}

.el-date-picker {
  width: 180px;
}
</style>
