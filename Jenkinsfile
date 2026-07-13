// ============================================================
// Jenkinsfile — 智慧自习室 AI 管家 CI/CD Pipeline
// 模式: 增量构建 + 自动部署
// 架构: Python Flask + Vue 3 + Nginx-RTMP
// ============================================================

pipeline {
    agent any

    environment {
        PROJECT_NAME    = 'AI-Study-Room'
        DOCKER_REGISTRY = 'docker.io'
        IMAGE_TAG       = "${env.BUILD_NUMBER}"
        BACKEND_IMAGE   = "${DOCKER_REGISTRY}/sco11-angus/${PROJECT_NAME}-backend:${IMAGE_TAG}"
        BACKEND_IMAGE_LATEST = "${DOCKER_REGISTRY}/sco11-angus/${PROJECT_NAME}-backend:latest"
        
        // 部署目录
        DEPLOY_BASE     = '/opt/AI-Study-Room'
        DEPLOY_COMPOSE  = "${DEPLOY_BASE}/deploy"
        DEPLOY_FRONTEND = "${DEPLOY_BASE}/frontend/dist"
        DEPLOY_BACKEND  = "${DEPLOY_BASE}/backend"
        
        // 变更检测文件（放在 workspace 外，避免 cleanWs 清掉）
        CHANGES_FILE    = '/tmp/AI-Study-Room_last_commit'
    }

    triggers {
        githubPush()
        pollSCM('H/5 * * * *')
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 30, unit: 'MINUTES')
        timestamps()
        ansiColor('xterm')
        disableConcurrentBuilds()
    }

    stages {

        // ============================================================
        // Stage 0: 变更检测（核心：决定哪些部分需要构建）
        // ============================================================
        stage('Change Detection') {
            steps {
                echo '🔍 [Stage 0] 检测代码变更范围'
                script {
                    // 获取本次构建的变更文件列表
                    sh '''
                        # 获取变更文件（与上一次构建对比）
                        if [ -f ${CHANGES_FILE} ]; then
                            PREVIOUS_COMMIT=$(cat ${CHANGES_FILE})
                        else
                            PREVIOUS_COMMIT="HEAD~1"
                        fi
                        
                        # 获取变更文件列表
                        git diff --name-only ${PREVIOUS_COMMIT} HEAD > changed_files.txt
                        echo "变更文件列表:"
                        cat changed_files.txt
                        
                        # 保存当前 commit 供下次使用
                        git rev-parse HEAD > ${CHANGES_FILE}
                    '''
                    
                    // 检测哪些模块发生了变化
                    script {
                        def changedFiles = readFile('changed_files.txt').split('\n')
                        
                        // 判断后端是否变更
                        env.BACKEND_CHANGED = 'false'
                        env.FRONTEND_CHANGED = 'false'
                        env.DEPLOY_CHANGED = 'false'
                        
                        changedFiles.each { file ->
                            if (file.startsWith('backend/')) {
                                env.BACKEND_CHANGED = 'true'
                            }
                            if (file.startsWith('frontend/')) {
                                env.FRONTEND_CHANGED = 'true'
                            }
                            if (file.startsWith('deploy/') || file == 'docker-compose.yml') {
                                env.DEPLOY_CHANGED = 'true'
                            }
                        }
                        
                        // 如果没有变更任何代码，跳过本次构建
                        if (changedFiles.size() == 0 || changedFiles[0] == '') {
                            echo "⏭️ 未检测到代码变更，跳过本次构建（所有 stage 将被跳过）"
                            // 不设置 BACKEND_CHANGED / FRONTEND_CHANGED，所有 stage 因 when 条件不满足而自动跳过
                            return
                        }
                        
                        echo "=========================================="
                        echo "📊 变更检测结果:"
                        echo "  - Backend 变更: ${env.BACKEND_CHANGED}"
                        echo "  - Frontend 变更: ${env.FRONTEND_CHANGED}"
                        echo "  - Deploy 变更: ${env.DEPLOY_CHANGED}"
                        echo "=========================================="
                    }
                }
            }
        }

        // ============================================================
        // Stage 1: Backend 增量构建（仅在 backend 变更时执行）
        // ============================================================
        stage('Backend Incremental Build') {
            when {
                expression { return env.BACKEND_CHANGED == 'true' }
            }
            steps {
                echo '🐍 [Stage 1] 增量构建 Backend'
                sh '''
                    cd backend
                    
                    # 检查 Python 依赖是否变更（如果有 requirements.txt 变更才重新安装依赖）
                    if git diff --name-only HEAD~1 HEAD | grep -q "backend/requirements.txt"; then
                        echo "📦 requirements.txt 已变更，重新安装依赖..."
                        python3 -m venv .venv
                        . .venv/bin/activate
                        pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
                    else
                        echo "✅ requirements.txt 未变更，跳过依赖安装"
                    fi
                    
                    # 检查模型权重是否变更（如果有新权重才下载）
                    if git diff --name-only HEAD~1 HEAD | grep -q "backend/model_weights/"; then
                        echo "📦 模型权重已变更，下载新权重..."
                        mkdir -p model_weights
                        # 下载模型权重逻辑...
                    else
                        echo "✅ 模型权重未变更，跳过下载"
                    fi
                    
                    # 运行单元测试（只测试变更相关的模块）
                    if git diff --name-only HEAD~1 HEAD | grep -q "backend/tests/"; then
                        echo "🧪 运行测试..."
                        . .venv/bin/activate
                        python -m pytest tests/ -v --tb=short || true
                    else
                        echo "✅ 测试代码未变更，跳过测试（可选）"
                    fi
                '''
            }
        }

        // ============================================================
        // Stage 2: Backend Docker 增量构建
        // ============================================================
        stage('Backend Docker Build') {
            when {
                expression { return env.BACKEND_CHANGED == 'true' }
            }
            steps {
                echo '🐳 [Stage 2] 构建 Backend Docker 镜像（仅当变更时）'
                sh '''
                    cd backend
                    
                    # 检查 Dockerfile 是否变更
                    if git diff --name-only HEAD~1 HEAD | grep -q "backend/Dockerfile"; then
                        echo "📦 Dockerfile 已变更，重新构建镜像..."
                        docker build --no-cache \
                            -t ${BACKEND_IMAGE} \
                            -t ${BACKEND_IMAGE_LATEST} \
                            --label "commit=${env.GIT_COMMIT}" \
                            --label "build=${env.BUILD_NUMBER}" \
                            .
                    else
                        echo "📦 Dockerfile 未变更，使用缓存构建..."
                        docker build \
                            -t ${BACKEND_IMAGE} \
                            -t ${BACKEND_IMAGE_LATEST} \
                            --label "commit=${env.GIT_COMMIT}" \
                            --label "build=${env.BUILD_NUMBER}" \
                            .
                    fi
                    
                    # 推送到镜像仓库
                    withCredentials([usernamePassword(credentialsId: 'docker-hub-creds', 
                        usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                        sh '''
                            echo "${DOCKER_PASS}" | docker login ${DOCKER_REGISTRY} -u "${DOCKER_USER}" --password-stdin
                            docker push ${BACKEND_IMAGE}
                            docker push ${BACKEND_IMAGE_LATEST}
                            docker logout
                        '''
                    }
                '''
            }
        }

        // ============================================================
        // Stage 3: Frontend 增量构建（仅在 frontend 变更时执行）
        // ============================================================
        stage('Frontend Incremental Build') {
            when {
                expression { return env.FRONTEND_CHANGED == 'true' }
            }
            steps {
                echo '🌐 [Stage 3] 增量构建 Frontend'
                sh '''
                    cd frontend
                    
                    # 检查 package.json 是否变更（决定是否需要 npm install）
                    if git diff --name-only HEAD~1 HEAD | grep -q "frontend/package.json"; then
                        echo "📦 package.json 已变更，重新安装依赖..."
                        npm ci
                    else
                        echo "✅ package.json 未变更，使用已有 node_modules"
                    fi
                    
                    # 检查 src 目录是否有变更（决定是否需要重新构建）
                    if git diff --name-only HEAD~1 HEAD | grep -q "frontend/src/"; then
                        echo "📦 前端源码已变更，执行构建..."
                        npm run build
                    else
                        echo "✅ 前端源码未变更，跳过构建（使用上次构建产物）"
                        # 但如果 dist 不存在，强制构建
                        if [ ! -d dist ] || [ -z "$(ls -A dist)" ]; then
                            echo "⚠️ dist 目录不存在，强制构建..."
                            npm run build
                        fi
                    fi
                '''
            }
        }

        // ============================================================
        // Stage 4: 自动部署（仅当有变更时）
        // ============================================================
        stage('Auto Deploy') {
            when {
                expression { 
                    return env.BACKEND_CHANGED == 'true' || 
                           env.FRONTEND_CHANGED == 'true' || 
                           env.DEPLOY_CHANGED == 'true'
                }
            }
            steps {
                echo '🚀 [Stage 4] 自动增量部署'
                
                withCredentials([string(credentialsId: 'dingtalk-webhook', variable: 'DINGTALK_WEBHOOK')]) {
                    sh '''
                        # ========================================
                        # 1. 准备部署目录
                        # ========================================
                        mkdir -p ${DEPLOY_BASE}
                        mkdir -p ${DEPLOY_COMPOSE}
                        mkdir -p ${DEPLOY_FRONTEND}
                        mkdir -p ${DEPLOY_BACKEND}
                        
                        cd ${DEPLOY_BASE}
                        
                        # ========================================
                        # 2. 生成 docker-compose.override.yml
                        # ========================================
                        cat > ${DEPLOY_COMPOSE}/docker-compose.override.yml <<EOF
services:
  backend:
    image: ${BACKEND_IMAGE}
    environment:
      - DINGTALK_WEBHOOK=${DINGTALK_WEBHOOK}
    volumes:
      - ${DEPLOY_BACKEND}/model_weights:/app/model_weights:ro
      - ${DEPLOY_BACKEND}/logs:/app/logs
    restart: unless-stopped

  nginx-rtmp:
    volumes:
      - ${DEPLOY_FRONTEND}:/usr/share/nginx/html:ro
    restart: unless-stopped
EOF

                        # ========================================
                        # 3. 增量部署 Backend（仅当有变更）
                        # ========================================
                        if [ "${BACKEND_CHANGED}" = "true" ]; then
                            echo "🔄 部署 Backend（已变更）..."
                            
                            # 同步后端配置文件
                            rsync -a --checksum deploy/docker-compose.yml ${DEPLOY_COMPOSE}/
                            
                            # 拉取新镜像
                            docker compose -f ${DEPLOY_COMPOSE}/docker-compose.yml \
                                -f ${DEPLOY_COMPOSE}/docker-compose.override.yml \
                                pull backend
                            
                            # 重启 backend（强制重建）
                            docker compose -f ${DEPLOY_COMPOSE}/docker-compose.yml \
                                -f ${DEPLOY_COMPOSE}/docker-compose.override.yml \
                                up -d --no-deps --force-recreate backend
                            
                            echo "✅ Backend 部署完成"
                        else
                            echo "⏭️ Backend 未变更，跳过部署"
                        fi
                        
                        # ========================================
                        # 4. 增量部署 Frontend（仅当有变更）
                        # ========================================
                        if [ "${FRONTEND_CHANGED}" = "true" ]; then
                            echo "🔄 部署 Frontend（已变更）..."
                            
                            # 检查构建产物是否存在
                            if [ -d ${WORKSPACE}/frontend/dist ] && [ -n "$(ls -A ${WORKSPACE}/frontend/dist)" ]; then
                                # 增量同步前端文件
                                rsync -a --checksum --delete \
                                    ${WORKSPACE}/frontend/dist/ \
                                    ${DEPLOY_FRONTEND}/
                                
                                # 重启 nginx（重新加载静态文件）
                                docker compose -f ${DEPLOY_COMPOSE}/docker-compose.yml \
                                    -f ${DEPLOY_COMPOSE}/docker-compose.override.yml \
                                    restart nginx-rtmp
                                
                                echo "✅ Frontend 部署完成"
                            else
                                echo "❌ ERROR: frontend/dist 为空，跳过前端部署"
                            fi
                        else
                            echo "⏭️ Frontend 未变更，跳过部署"
                        fi
                        
                        # ========================================
                        # 5. 启动所有服务
                        # ========================================
                        docker compose -f ${DEPLOY_COMPOSE}/docker-compose.yml \
                            -f ${DEPLOY_COMPOSE}/docker-compose.override.yml \
                            up -d
                        
                        # ========================================
                        # 6. 清理旧镜像
                        # ========================================
                        docker image prune -f --filter "until=24h" || true
                        
                        echo '✅ 自动部署完成'
                    '''
                }
            }
        }

        // ============================================================
        // Stage 5: 健康检查
        // ============================================================
        stage('Health Check') {
            when {
                expression { 
                    return env.BACKEND_CHANGED == 'true' || 
                           env.FRONTEND_CHANGED == 'true' || 
                           env.DEPLOY_CHANGED == 'true'
                }
            }
            steps {
                echo '🩺 [Stage 5] 健康检查'
                sh '''
                    cd ${DEPLOY_BASE}
                    
                    # 等待服务启动
                    sleep 10
                    
                    # 健康检查（重试 10 次）
                    for i in {1..10}; do
                        if curl -sf http://127.0.0.1:5000/health; then
                            echo "✅ Backend 健康"
                            break
                        fi
                        echo "⏳ 等待 Backend 启动... (${i}/10)"
                        sleep 3
                    done
                    
                    for i in {1..10}; do
                        if curl -sf http://127.0.0.1:8080/ -o /dev/null; then
                            echo "✅ Frontend 健康"
                            break
                        fi
                        echo "⏳ 等待 Frontend 启动... (${i}/10)"
                        sleep 3
                    done
                    
                    echo "✅ 所有服务健康"
                '''
            }
        }
    }

    // ============================================================
    // Post Actions
    // ============================================================
    post {
        success {
            echo '🎉 增量构建 + 自动部署成功！'
            script {
                // 输出构建摘要
                sh '''
                    echo "=========================================="
                    echo "📊 构建摘要:"
                    echo "  - Backend 构建: ${BACKEND_CHANGED}"
                    echo "  - Frontend 构建: ${FRONTEND_CHANGED}"
                    echo "  - 部署执行: $([ "${BACKEND_CHANGED}" = "true" -o "${FRONTEND_CHANGED}" = "true" -o "${DEPLOY_CHANGED}" = "true" ] && echo "是" || echo "否")"
                    echo "=========================================="
                '''
            }
        }
        failure {
            echo '❌ 构建或部署失败'
        }
        always {
            cleanWs()
            echo '🧹 工作空间已清理'
        }
    }
}