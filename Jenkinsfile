pipeline {
    agent any

    // ---- 触发条件 ----
    triggers {
        // GitHub Webhook 推送触发（推荐）
        githubPush()
        // 每 5 分钟轮询 SCM 变化（Webhook 失效时兜底）
        pollSCM('H/5 * * * *')
    }

    // ---- 选项 ----
    options {
        timeout(time: 20, unit: 'MINUTES')
        timestamps()
        disableConcurrentBuilds()
    }

    // ---- 全局环境变量 ----
    environment {
        PROJECT_NAME    = 'AI-Study-Room'
        DOCKER_REGISTRY = 'docker.io'          // 改为私有镜像仓库地址即可
        IMAGE_TAG       = "${env.BUILD_NUMBER}"
        VENV_DIR        = 'backend/.venv'
        // 模型权重下载地址（按实际 OSS/S3 调整；占位符时下载自动跳过，不影响流水线）
        YOLO_WEIGHTS_URL = 'https://your-oss.com/model_weights/yolov8n.pt'
        DLIB_WEIGHTS_URL = 'https://your-oss.com/model_weights/shape_predictor_68_face_landmarks.dat'
        PROD_HOST        = '127.0.0.1'
        DEPLOY_DIR       = '/var/www/html'     // 新增：前端部署目录
        // 本地开发用镜像 tag（Docker Image stage 走本地 docker build）
        BACKEND_IMAGE   = 'ai-study-room-backend-env:dev'
    }

    parameters {
        booleanParam(name: 'BUILD_DOCKER_IMAGE', defaultValue: false, description: 'Build backend Docker image when the Jenkins agent has Docker daemon access.')
    }

    stages {
        stage('Checkout') {
            steps {
                echo 'Checking out source from configured SCM...'
                checkout scm
                script {
                    if (isUnix()) {
                        sh 'git --no-pager log --oneline -1'
                    } else {
                        bat 'git --no-pager log --oneline -1'
                    }
                }
            }
        }

        stage('Smoke Test') {
            steps {
                echo 'Running repository smoke test...'
                script {
                    if (isUnix()) {
                        sh 'sh ./init.sh'
                    } else {
                        bat 'init.cmd'
                    }
                }
            }
        }

        stage('Frontend Build') {
            steps {
                echo 'Installing frontend dependencies and running Vite build...'
                dir('frontend') {
                    script {
                        if (isUnix()) {
                            timeout(time: 8, unit: 'MINUTES') {
                                sh 'npm ci'
                                sh 'npm run build'
                            }
                        } else {
                            timeout(time: 8, unit: 'MINUTES') {
                                bat 'npm ci'
                                bat 'npm run build'
                            }
                        }
                    }
                }
            }
        }

        stage('Backend Syntax Check') {
            steps {
                echo 'Compiling backend Python sources...'
                dir('backend') {
                    script {
                        if (isUnix()) {
                            sh 'PYTHONPYCACHEPREFIX=.pycache-ci python -m compileall app run.py'
                        } else {
                            bat 'set PYTHONPYCACHEPREFIX=.pycache-ci&& python -m compileall app run.py'
                        }
                    }
                }
            }
        }

        stage('Docker Image') {
            when {
                expression {
                    return params.BUILD_DOCKER_IMAGE && fileExists('backend/Dockerfile')
                }
            }
            steps {
                echo 'Building backend Docker image...'
                script {
                    if (isUnix()) {
                        sh 'docker build -t "$BACKEND_IMAGE" backend'
                    } else {
                        bat 'docker build -t %BACKEND_IMAGE% backend'
                    }
                }
            }
        }

        // ============================
        // Stage 8: Deploy Frontend to Nginx (新增)
        // ============================
        stage('Deploy Frontend to Nginx') {
            steps {
                echo '🌐 [Stage 8] 部署前端到 Nginx'
                sh '''
                    sudo mkdir -p ${DEPLOY_DIR}
                    sudo rm -rf ${DEPLOY_DIR}/*
                    sudo cp -r frontend/dist/* ${DEPLOY_DIR}/
                    sudo chown -R www-data:www-data ${DEPLOY_DIR}
                    sudo systemctl reload nginx || sudo systemctl restart nginx
                    echo "✅ 前端已部署到 ${DEPLOY_DIR}"
                '''
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'frontend/dist/**', allowEmptyArchive: true
        }
        success {
            echo 'CI pipeline completed successfully.'
        }
        failure {
            echo 'CI pipeline failed. Open Console Output and check the first failed stage above.'
        }
    }
}