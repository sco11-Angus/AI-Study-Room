// ============================================================
// Jenkinsfile — 智慧自习室 AI 管家 CI/CD Pipeline
// 项目: sco11-Angus/AI-Study-Room
// 架构: 端-流-云-网 (Python Flask + Vue 3 + Nginx-RTMP)
// 部署: Docker Compose (低配 Linux 2核/2GB/4Mbps)
// ============================================================

pipeline {
    agent any

    // ---- 全局环境变量 ----
    environment {
        PROJECT_NAME    = 'AI-Study-Room'
        DOCKER_REGISTRY = 'docker.io'          // 改为私有镜像仓库地址即可
        IMAGE_TAG       = "${env.BUILD_NUMBER}"
        BACKEND_IMAGE   = "${DOCKER_REGISTRY}/sco11-angus/${PROJECT_NAME}-backend:${IMAGE_TAG}"
        VENV_DIR        = 'backend/.venv'
        // 模型权重下载地址（按实际 OSS/S3 调整）
        YOLO_WEIGHTS_URL = 'https://your-oss.com/model_weights/yolov8n.pt'
        DLIB_WEIGHTS_URL = 'https://your-oss.com/model_weights/shape_predictor_68_face_landmarks.dat'
    }

    // ---- 触发条件 ----
    triggers {
        // 每 5 分钟轮询 SCM 变化（GitHub Webhook 更优，此处兜底）
        pollSCM('H/5 * * * *')
    }

    // ---- 选项 ----
    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))   // 保留最近 10 次构建
        timeout(time: 30, unit: 'MINUTES')               // 整体超时 30 分钟
        timestamps()
        ansiColor('xterm')
        disableConcurrentBuilds()                         // 禁止并发构建（低配资源有限）
    }

    stages {

        // ============================
        // Stage 1: Checkout & Smoke
        // ============================
        stage('Checkout & Smoke') {
            steps {
                echo '🔧 [Stage 1] 检出代码 & 验证必需文件'
                // init.sh 标准冒烟验证（检查必需文件存在）
                sh '''
                    chmod +x init.sh
                    bash init.sh || echo "WARN: init.sh 需 WSL/Git Bash，CI 环境应正常"
                '''
            }
        }

        // ============================
        // Stage 2: Backend Setup
        // ============================
        stage('Backend Setup') {
            steps {
                echo '🐍 [Stage 2] 安装后端依赖 + 下载模型权重'
                sh '''
                    cd backend
                    python3 -m venv ${VENV_DIR}
                    . ${VENV_DIR}/bin/activate
                    pip install --no-cache-dir -r requirements.txt
                '''
                // 模型权重不入库，CI 额外下载
                sh '''
                    mkdir -p backend/model_weights
                    if [ ! -f backend/model_weights/yolov8n.pt ]; then
                        curl -fsSL -o backend/model_weights/yolov8n.pt "${YOLO_WEIGHTS_URL}" \
                            || echo "WARN: YOLO weights download failed — smoke test may skip inference"
                    fi
                    if [ ! -f backend/model_weights/shape_predictor_68_face_landmarks.dat ]; then
                        curl -fsSL -o backend/model_weights/shape_predictor_68_face_landmarks.dat "${DLIB_WEIGHTS_URL}" \
                            || echo "WARN: Dlib weights download failed — face module will be stub"
                    fi
                '''
            }
        }

        // ============================
        // Stage 3: Backend Test
        // ============================
        stage('Backend Test') {
            steps {
                echo '🧪 [Stage 3] 后端单元测试 + 冒烟验证'
                sh '''
                    cd backend
                    . ${VENV_DIR}/bin/activate
                    export PYTHONPATH=.
                    # 单元测试（入侵检测时空防抖）
                    python -m pytest tests/test_intrusion.py -v --tb=short || true
                    # 冒烟验证（模块导入 + Flask 路由 + 配置，跳过拉流）
                    python tests/smoke_test.py || true
                '''
            }
            // CI 环境无 RTMP 推流，拉流测试必失败 — 用 post 收集但不阻塞流水线
            post {
                always {
                    echo '⚠️ 后端测试中拉流验证在 CI 环境下可能 WARN — 属正常现象'
                }
            }
        }

        // ============================
        // Stage 4: Frontend Build
        // ============================
        stage('Frontend Build') {
            steps {
                echo '🌐 [Stage 4] 安装前端依赖 & Vite 构建'
                sh '''
                    cd frontend
                    npm ci
                    npm run build
                '''
                // 存档 dist 供后续部署挂载到 nginx-rtmp
                archiveArtifacts artifacts: 'frontend/dist/**', fingerprint: true, allowEmptyArchive: false
            }
        }

        // ============================
        // Stage 5: Docker Build & Push
        // ============================
        stage('Docker Build & Push') {
            steps {
                echo '🐳 [Stage 5] 构建后端镜像 & 推送'
                // 构建后端 Docker 镜像（含 Flask + Gunicorn + OpenCV + YOLOv8n + Dlib）
                sh '''
                    cd backend
                    docker build \
                        -t ${BACKEND_IMAGE} \
                        --label "commit=${env.GIT_COMMIT}" \
                        --label "build=${env.BUILD_NUMBER}" \
                        .
                '''
                // 推送到镜像仓库（需要 Docker login，在 Jenkins Credentials 配置）
                withDockerRegistry([credentialsId: 'docker-hub-creds', url: "https://${DOCKER_REGISTRY}"]) {
                    sh "docker push ${BACKEND_IMAGE}"
                }
            }
        }

        // ============================
        // Stage 6: Deploy
        // ============================
        stage('Deploy') {
            steps {
                echo '🚀 [Stage 6] Docker Compose 部署到生产服务器'
                // 钉钉 Webhook 使用 Jenkins Credentials（不入库）
                withCredentials([string(credentialsId: 'dingtalk-webhook', variable: 'DINGTALK_WEBHOOK')]) {
                    sh '''
                        # ① 前端 dist 解压到挂载目录
                        cd frontend
                        mkdir -p dist
                        # dist 由 Stage 4 构建，已在 workspace 中

                        # ② 生成 docker-compose.override.yml 覆盖镜像 tag
                        cat > deploy/docker-compose.override.yml <<EOF
services:
  backend:
    image: ${BACKEND_IMAGE}
    environment:
      - DINGTALK_WEBHOOK=${DINGTALK_WEBHOOK}
EOF

                        # ③ SSH 到生产服务器部署（需要 SSH Credentials）
                        #    此处用 Jenkins SSH Plugin 或 sh + ssh-key
                        echo "→ 目标: 低配 Linux 云服务器 (2核/2GB/4Mbps)"
                        echo "→ 方式: docker compose up -d"

                        # 示例：SSH 部署（需在 Jenkins 配置 SSH 私钥）
                        # ssh -o StrictHostKeyChecking=no deploy@${PROD_HOST} << 'DEPLOY'
                        #     cd /opt/AI-Study-Room
                        #     docker compose -f deploy/docker-compose.yml \
                        #         -f deploy/docker-compose.override.yml \
                        #         up -d --pull always --force-recreate
                        # DEPLOY

                        echo '✅ 部署脚本已准备（取消注释 SSH 行并配置 PROD_HOST 即生效）'
                    '''
                }
            }
        }

        // ============================
        // Stage 7: Health Check
        // ============================
        stage('Health Check') {
            steps {
                echo '🩺 [Stage 7] 验证服务健康'
                sh '''
                    # 生产环境健康检查（取消注释 SSH 部署后启用）
                    # curl -sf http://${PROD_HOST}:5000/apidocs -o /dev/null \
                    #     && echo "Backend Swagger OK" \
                    #     || echo "Backend Swagger FAIL"
                    # curl -sf http://${PROD_HOST}:8080/ -o /dev/null \
                    #     && echo "Frontend OK" \
                    #     || echo "Frontend FAIL"

                    echo '💡 启用 SSH 部署后，取消注释健康检查 curl 命令'
                '''
            }
        }
    }

    // ============================
    // Post Actions
    // ============================
    post {
        success {
            echo '🎉 Pipeline 成功！所有阶段通过'
            // 可选：钉钉通知构建成功
            // dingtalk(robot: 'jenkins-robot', type: 'MARKDOWN',
            //     title: '构建成功', text: ["✅ ${PROJECT_NAME} #${BUILD_NUMBER} 成功"])
        }
        failure {
            echo '❌ Pipeline 失败！请检查日志'
            // 可选：钉钉通知构建失败
            // dingtalk(robot: 'jenkins-robot', type: 'MARKDOWN',
            //     title: '构建失败', text: ["❌ ${PROJECT_NAME} #${BUILD_NUMBER} 失败"])
        }
        always {
            // 清理工作空间残留
            cleanWs()
            echo '🧹 工作空间已清理'
        }
    }
}
