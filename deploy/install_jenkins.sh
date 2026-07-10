#!/bin/bash
# ============================================================
# Jenkins 一键部署脚本 — AI-Study-Room CI/CD
# 目标: Linux 云服务器 (2核/2GB/4Mbps)
# 使用: ssh root@49.233.71.82 然后执行此脚本
# ============================================================

set -e

# ---- 配置区域（按实际情况修改） ----
JENKINS_PORT=9092                # Jenkins Web UI 端口
DOCKER_HUB_USER=""              # Docker Hub 用户名（填入）
DOCKER_HUB_PASS=""              # Docker Hub 密码（填入）
DINGTALK_WEBHOOK=""              # 钉钉机器人 Webhook URL（填入）
REPO_URL="https://github.com/sco11-Angus/AI-Study-Room"
BRANCH="main"
JENKINS_HOME="/opt/jenkins_home"

echo "============================================"
echo "  Jenkins CI/CD 一键部署 — AI-Study-Room"
echo "============================================"

# ---- Step 1: 安装 Docker（如已安装则跳过） ----
echo ""
echo "📦 [Step 1] 检查 Docker..."
if command -v docker &> /dev/null; then
    echo "   Docker 已安装: $(docker --version)"
else
    echo "   安装 Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl start docker
    systemctl enable docker
    echo "   Docker 安装完成"
fi

# ---- Step 2: 安装 Docker Compose ----
echo ""
echo "📦 [Step 2] 检查 Docker Compose..."
if docker compose version &> /dev/null; then
    echo "   Docker Compose 已安装: $(docker compose version)"
else
    echo "   安装 Docker Compose Plugin..."
    mkdir -p /usr/local/lib/docker/cli-plugins
    curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
        -o /usr/local/lib/docker/cli-plugins/docker-compose
    chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
    echo "   Docker Compose 安装完成"
fi

# ---- Step 3: 启动 Jenkins 容器 ----
echo ""
echo "🚀 [Step 3] 启动 Jenkins..."
mkdir -p ${JENKINS_HOME}

# 停掉旧容器（如有）
docker rm -f jenkins-server 2>/dev/null || true

docker run -d \
    --name jenkins-server \
    --restart unless-stopped \
    -p ${JENKINS_PORT}:8080 \
    -p 50000:50000 \
    -v ${JENKINS_HOME}:/var/jenkins_home \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v /usr/bin/docker:/usr/bin/docker \
    --group-add $(stat -c '%g' /var/run/docker.sock) \
    jenkins/jenkins:lts

echo "   Jenkins 容器已启动，端口 ${JENKINS_PORT}"

# ---- Step 4: 获取初始管理员密码 ----
echo ""
echo "🔑 [Step 4] 获取初始密码（等待 Jenkins 启动）..."
echo "   等待 Jenkins 初始化（约 30 秒）..."
sleep 30

INITIAL_PASS=$(docker exec jenkins-server cat /var/jenkins_home/secrets/initialAdminPassword 2>/dev/null || echo "获取失败，请手动查看")
echo ""
echo "   ============================================"
echo "   ⚠️  Jenkins 初始管理员密码:"
echo "   ${INITIAL_PASS}"
echo "   ============================================"
echo "   访问 http://49.233.71.82:${JENKINS_PORT} 完成初始化"
echo "   选择: Install suggested plugins"
echo ""

# ---- Step 5: 安装额外插件 ----
echo ""
echo "🔌 [Step 5] 安装 Jenkins 插件（等待初始化完成后执行）..."
echo "   需安装插件:"
echo "     - docker-workflow     (Docker Pipeline 支持)"
echo "     - pipeline-stage-view (流水线可视化)"
echo "     - git                 (Git SCM)"
echo "     - credentials-binding (凭证绑定)"
echo ""
echo "   安装方式: Jenkins UI → Manage Jenkins → Plugins → Available"
echo "   或用 CLI（需先完成 UI 初始化）:"
echo ""
echo "   # 以下命令需在完成 UI 初始化后执行"
echo "   JENKINS_CRUMB=\$(curl -s -u admin:<你的密码> http://localhost:${JENKINS_PORT}/crumbIssuer/api/json | python3 -c \"import sys,json; print(json.load(sys.stdin)['crumb'])\")"
echo "   for plugin in docker-workflow pipeline-stage-view credentials-binding git; do"
echo "     curl -X POST -H \"Jenkins-Crumb: \${JENKINS_CRUMB}\" -u admin:<你的密码> http://localhost:${JENKINS_PORT}/pluginManager/installNecessaryPlugins"
echo "   done"

# ---- Step 6: 配置 Credentials ----
echo ""
echo "🔑 [Step 6] 配置 Credentials（需在 Jenkins UI 操作）..."
echo "   进入: Manage Jenkins → Credentials → System → Global credentials"
echo ""
echo "   1. docker-hub-creds (Username with password)"
echo "      Username: ${DOCKER_HUB_USER:-<填入Docker Hub用户名>}"
echo "      Password: ${DOCKER_HUB_PASS:-<填入Docker Hub密码>}"
echo ""
echo "   2. dingtalk-webhook (Secret text)"
echo "      Secret:   ${DINGTALK_WEBHOOK:-<填入钉钉Webhook URL>}"

# ---- Step 7: 创建 Pipeline 项目 ----
echo ""
echo "📋 [Step 7] 创建 Pipeline 项目（需在 Jenkins UI 操作）..."
echo "   1. New Item → 名称: ai-study-room → 类型: Pipeline"
echo "   2. Definition: Pipeline script from SCM"
echo "   3. SCM: Git"
echo "      Repository URL: ${REPO_URL}"
echo "      Branch: ${BRANCH}"
echo "   4. Script Path: Jenkinsfile (默认)"
echo "   5. Save"

# ---- Step 8: 配置 GitHub Webhook ----
echo ""
echo "🔗 [Step 8] 配置自动触发..."
echo "   方案 A: GitHub Webhook（推荐）"
echo "     GitHub → Settings → Webhooks → Add webhook"
echo "     Payload URL: http://49.233.71.82:${JENKINS_PORT}/github-webhook/"
echo "     Content type: application/json"
echo "     Jenkins 项目勾选: GitHub hook trigger for GITScm polling"
echo ""
echo "   方案 B: Poll SCM（已写在 Jenkinsfile，每5分钟轮询）"
echo "     无需额外配置，Jenkinsfile 中已包含 pollSCM('H/5 * * * *')"

# ---- Step 9: 安装运行依赖 ----
echo ""
echo "🛠️  [Step 9] 确保服务器运行环境..."
echo "   Jenkins 容器内需安装 Node.js + Python3（用于跑流水线）"
echo "   安装方式: 进入 Jenkins 容器手动安装"
echo ""
echo "   docker exec -it jenkins-server bash"
echo "   # 在容器内执行:"
echo "   apt-get update && apt-get install -y python3 python3-venv nodejs npm curl"
echo ""

# ---- 完成 ----
echo ""
echo "============================================"
echo "  ✅ Jenkins 部署完成！"
echo "============================================"
echo ""
echo "  🌐 Jenkins UI: http://49.233.71.82:${JENKINS_PORT}"
echo "  🔑 初始密码: ${INITIAL_PASS}"
echo ""
echo "  接下来的手动步骤:"
echo "  1. 打开 Jenkins UI → 用初始密码登录 → 安装推荐插件"
echo "  2. 安装额外插件（docker-workflow 等）"
echo "  3. 在容器内安装 Python3 + Node.js"
echo "  4. 配置 Credentials（docker-hub-creds + dingtalk-webhook）"
echo "  5. 创建 Pipeline 项目（指向 AI-Study-Room 仓库）"
echo "  6. 配置 GitHub Webhook 或依赖 Poll SCM 自动触发"
echo ""
echo "  完成后，组员 push 代码即可自动触发 CI/CD 流水线 🎉"
echo ""
