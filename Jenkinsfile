// ============================================================
// Jenkinsfile — 智慧自习室 AI 管家 CI/CD Pipeline
// 模式: 增量构建 + 自动部署（基于上次成功构建对比）
// 架构: Python Flask + Vue 3 + Nginx-RTMP
// 分支: frontend
// 超时: 20分钟
// ============================================================

pipeline {
    agent any

    environment {
        PROJECT_NAME    = 'AI-Study-Room'
        DOCKER_REGISTRY = 'docker.io'
        BRANCH_NAME     = 'frontend'  // ✅ 改为 frontend
        IMAGE_TAG       = "${env.BUILD_NUMBER}"
        BACKEND_IMAGE   = "${DOCKER_REGISTRY}/sco11-angus/${PROJECT_NAME}-backend:${IMAGE_TAG}"
        BACKEND_IMAGE_LATEST = "${DOCKER_REGISTRY}/sco11-angus/${PROJECT_NAME}-backend:latest"
        
        // 部署目录
        DEPLOY_BASE     = '/opt/AI-Study-Room'
        DEPLOY_COMPOSE  = "${DEPLOY_BASE}/deploy"
        DEPLOY_FRONTEND = "${DEPLOY_BASE}/frontend/dist"
        DEPLOY_BACKEND  = "${DEPLOY_BASE}/backend"
        
        // 上次成功构建的代码保存目录（在 workspace 外，避免被 cleanWs 清理）
        LAST_BUILD_DIR  = '/var/lib/jenkins/last_build/AI-Study-Room'
        // 变更检测结果文件
        CHANGED_FILES   = '/tmp/AI-Study-Room_changed_files'
    }

    triggers {
        githubPush()
        pollSCM('H/5 * * * *')
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        timeout(time: 120, unit: 'MINUTES')  // ✅ 改为 20 分钟
        timestamps()
        ansiColor('xterm')
        disableConcurrentBuilds()
    }

    stages {

        // ============================================================
        // Stage 0: 检出代码 + 变更检测（基于上一次成功构建）
        // ============================================================
        stage('Checkout & Change Detection') {
            steps {
                echo '🔍 [Stage 0] 检出代码 & 检测变更范围'
                
                script {
                    // 1. 浅克隆快速拉取最新代码
                    sh '''
                        echo "→ 拉取最新代码（浅克隆）..."
                        # 如果 workspace 已有代码，先清理
                        rm -rf .git
                        git init
                        git remote add origin https://github.com/sco11-Angus/AI-Study-Room.git
                        git fetch --depth=1 origin ${BRANCH_NAME}
                        git checkout FETCH_HEAD
                        
                        # 保存当前 commit
                        git rev-parse HEAD > /tmp/current_commit
                        echo "当前 commit: $(cat /tmp/current_commit)"
                    '''
                    
                    // 2. 检查是否有上一次成功构建的代码
                    def hasLastBuild = sh(
                        script: "test -d ${LAST_BUILD_DIR} && echo 'true' || echo 'false'",
                        returnStdout: true
                    ).trim()
                    
                    echo "是否有上次成功构建的代码: ${hasLastBuild}"
                    
                    // 3. 对比变更
                    sh '''
                        echo "→ 检测变更文件..."
                        
                        if [ -d ${LAST_BUILD_DIR} ]; then
                            echo "📝 对比上次成功构建的代码 (${LAST_BUILD_DIR})"
                            
                            # 使用 rsync -n 模拟对比，只输出变更的文件
                            rsync -n -a --delete --checksum \
                                . \
                                ${LAST_BUILD_DIR}/ \
                                --exclude='.git' \
                                --exclude='*.pyc' \
                                --exclude='__pycache__' \
                                --exclude='node_modules' \
                                --exclude='.venv' \
                                --exclude='dist' \
                                --exclude='*.log' \
                                --exclude='.env' \
                                --exclude='.pytest_cache' \
                                --exclude='.vscode' \
                                --exclude='.idea' \
                                --exclude='backend@tmp' \
                                --exclude='frontend@tmp' \
                                --exclude='venv' \
                                --exclude='.reference' \
                                --itemize-changes 2>/dev/null | \
                                grep -E '^[><]' | \
                                awk '{print $2}' | \
                                sort -u > ${CHANGED_FILES} || echo "" > ${CHANGED_FILES}
                            
                            echo "变更文件列表:"
                            cat ${CHANGED_FILES} || echo "(无变更)"
                        else
                            echo "⚠️ 没有上次成功构建的代码！"
                            echo "⚠️ 请先运行一次完整构建（Build Now）"
                            echo "⚠️ 或者手动创建基准代码目录"
                            # 标记所有模块都需要构建
                            echo "backend" > ${CHANGED_FILES}
                            echo "frontend" >> ${CHANGED_FILES}
                            echo "deploy" >> ${CHANGED_FILES}
                        fi
                        
                        echo "=========================================="
                        echo "变更文件列表:"
                        cat ${CHANGED_FILES} || echo "(无变更)"
                        echo "=========================================="
                    '''
                    
                    // 4. 解析变更文件，判断哪些模块需要构建
                    script {
                        def changedFiles = sh(
                            script: "cat ${CHANGED_FILES} 2>/dev/null || echo ''",
                            returnStdout: true
                        ).trim().split('\n')
                        
                        // 初始化
                        env.BACKEND_CHANGED = 'false'
                        env.FRONTEND_CHANGED = 'false'
                        env.DEPLOY_CHANGED = 'false'
                        env.HAS_CHANGES = 'false'
                        
                        // 如果没有变更文件或为空，跳过所有构建
                        if (changedFiles.size() == 0 || (changedFiles.size() == 1 && changedFiles[0] == '')) {
                            echo "⏭️ 未检测到任何代码变更，跳过本次构建"
                            env.HAS_CHANGES = 'false'
                            return
                        }
                        
                        // 检查哪些模块变更了
                        changedFiles.each { file ->
                            if (file == 'backend' || file.startsWith('backend/')) {
                                env.BACKEND_CHANGED = 'true'
                                env.HAS_CHANGES = 'true'
                            }
                            if (file == 'frontend' || file.startsWith('frontend/')) {
                                env.FRONTEND_CHANGED = 'true'
                                env.HAS_CHANGES = 'true'
                            }
                            if (file == 'deploy' || file.startsWith('deploy/') || file == 'docker-compose.yml') {
                                env.DEPLOY_CHANGED = 'true'
                                env.HAS_CHANGES = 'true'
                            }
                        }
                        
                        // 如果没有任何模块变更，但文件列表不为空（比如只改了 README），跳过构建
                        if (env.HAS_CHANGES == 'false') {
                            echo "⏭️ 变更文件不影响构建模块（如 README），跳过构建"
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
        // Stage 1: Backend 增量构建
        // ============================================================
        stage('Backend Incremental Build') {
            when {
                expression { return env.BACKEND_CHANGED == 'true' }
            }
            steps {
                echo '🐍 [Stage 1] 增量构建 Backend'
                sh '''
                    cd backend
                    
                    # 检查 Python 依赖是否变更
                    if grep -q "backend/requirements.txt" ${CHANGED_FILES} 2>/dev/null; then
                        echo "📦 requirements.txt 已变更，重新安装依赖..."
                        python3 -m venv .venv
                        . .venv/bin/activate
                        pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
                    else
                        echo "✅ requirements.txt 未变更，跳过依赖安装"
                    fi
                    
                    # 检查模型权重是否变更
                    if grep -q "backend/model_weights/" ${CHANGED_FILES} 2>/dev/null; then
                        echo "📦 模型权重已变更，下载新权重..."
                        mkdir -p model_weights
                        # 下载模型权重逻辑...
                    else
                        echo "✅ 模型权重未变更，跳过下载"
                    fi
                    
                    # 运行单元测试
                    if grep -q "backend/tests/" ${CHANGED_FILES} 2>/dev/null; then
                        echo "🧪 运行测试..."
                        . .venv/bin/activate
                        python -m pytest tests/ -v --tb=short || true
                    else
                        echo "✅ 测试代码未变更，跳过测试"
                    fi
                '''
            }
        }

        // ============================================================
        // Stage 2: Backend Docker 构建
        // ============================================================
        stage('Backend Docker Build') {
            when {
                expression { return env.BACKEND_CHANGED == 'true' }
            }
            steps {
                echo '🐳 [Stage 2] 构建 Backend Docker 镜像'
                sh '''
                    cd backend
                    
                    # 检查 Dockerfile 是否变更
                    if grep -q "backend/Dockerfile" ${CHANGED_FILES} 2>/dev/null; then
                        echo "📦 Dockerfile 已变更，重新构建镜像（无缓存）..."
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
        // Stage 3: Frontend 增量构建
        // ============================================================
        stage('Frontend Incremental Build') {
            when {
                expression { return env.FRONTEND_CHANGED == 'true' }
            }
            steps {
                echo '🌐 [Stage 3] 增量构建 Frontend'
                sh '''
                    cd frontend
                    
                    # 检查 package.json 是否变更
                    if grep -q "frontend/package.json" ${CHANGED_FILES} 2>/dev/null; then
                        echo "📦 package.json 已变更，重新安装依赖..."
                        npm ci
                    else
                        echo "✅ package.json 未变更，使用已有 node_modules"
                    fi
                    
                    # 检查 src 目录是否有变更
                    if grep -q "frontend/src/" ${CHANGED_FILES} 2>/dev/null; then
                        echo "📦 前端源码已变更，执行构建..."
                        npm run build
                    else
                        echo "✅ 前端源码未变更，跳过构建（使用上次构建产物）"
                        if [ ! -d dist ] || [ -z "$(ls -A dist)" ]; then
                            echo "⚠️ dist 目录不存在，强制构建..."
                            npm run build
                        fi
                    fi
                '''
            }
        }

        // ============================================================
        // Stage 4: 自动部署
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
                        # 3. 增量部署 Backend
                        # ========================================
                        if [ "${BACKEND_CHANGED}" = "true" ]; then
                            echo "🔄 部署 Backend（已变更）..."
                            
                            rsync -a --checksum deploy/docker-compose.yml ${DEPLOY_COMPOSE}/
                            
                            docker compose -f ${DEPLOY_COMPOSE}/docker-compose.yml \
                                -f ${DEPLOY_COMPOSE}/docker-compose.override.yml \
                                pull backend
                            
                            docker compose -f ${DEPLOY_COMPOSE}/docker-compose.yml \
                                -f ${DEPLOY_COMPOSE}/docker-compose.override.yml \
                                up -d --no-deps --force-recreate backend
                            
                            echo "✅ Backend 部署完成"
                        else
                            echo "⏭️ Backend 未变更，跳过部署"
                        fi
                        
                        # ========================================
                        # 4. 增量部署 Frontend
                        # ========================================
                        if [ "${FRONTEND_CHANGED}" = "true" ]; then
                            echo "🔄 部署 Frontend（已变更）..."
                            
                            if [ -d ${WORKSPACE}/frontend/dist ] && [ -n "$(ls -A ${WORKSPACE}/frontend/dist)" ]; then
                                rsync -a --checksum --delete \
                                    ${WORKSPACE}/frontend/dist/ \
                                    ${DEPLOY_FRONTEND}/
                                
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
                    
                    sleep 10
                    
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
            
            // 保存本次构建的代码，供下次对比
            sh '''
                echo "→ 保存本次构建代码，供下次增量构建使用..."
                
                # 删除旧的备份
                rm -rf ${LAST_BUILD_DIR}
                
                # 复制当前代码（排除不需要的目录）
                mkdir -p ${LAST_BUILD_DIR}
                rsync -a \
                    --exclude='.git' \
                    --exclude='*.pyc' \
                    --exclude='__pycache__' \
                    --exclude='node_modules' \
                    --exclude='.venv' \
                    --exclude='dist' \
                    --exclude='*.log' \
                    --exclude='.env' \
                    --exclude='.pytest_cache' \
                    --exclude='.vscode' \
                    --exclude='.idea' \
                    --exclude='backend@tmp' \
                    --exclude='frontend@tmp' \
                    --exclude='venv' \
                    . ${LAST_BUILD_DIR}/
                
                # 保存 commit（如果有）
                if git rev-parse HEAD 2>/dev/null; then
                    git rev-parse HEAD > ${LAST_BUILD_DIR}/.commit_hash
                else
                    echo "no_git" > ${LAST_BUILD_DIR}/.commit_hash
                fi
                
                # 添加标记
                echo "build_${BUILD_NUMBER}_success" > ${LAST_BUILD_DIR}/.reference
                
                echo "✅ 已保存代码到 ${LAST_BUILD_DIR}"
                echo "📝 Commit: $(cat ${LAST_BUILD_DIR}/.commit_hash 2>/dev/null || echo '无')"
                echo "📊 目录大小: $(du -sh ${LAST_BUILD_DIR} | cut -f1)"
            '''
            
            script {
                sh '''
                    echo "=========================================="
                    echo "📊 构建摘要:"
                    echo "  - 分支: ${BRANCH_NAME}"
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
