pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
    }

    environment {
        BACKEND_IMAGE = 'ai-study-room-backend-env:dev'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Smoke Test') {
            steps {
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
                dir('frontend') {
                    script {
                        if (isUnix()) {
                            sh 'npm ci'
                            sh 'npm run build'
                        } else {
                            bat 'npm ci'
                            bat 'npm run build'
                        }
                    }
                }
            }
        }

        stage('Backend Syntax Check') {
            steps {
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
                    return fileExists('backend/Dockerfile')
                }
            }
            steps {
                script {
                    if (isUnix()) {
                        sh 'docker build -t "$BACKEND_IMAGE" backend'
                    } else {
                        bat 'docker build -t %BACKEND_IMAGE% backend'
                    }
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: 'frontend/dist/**', allowEmptyArchive: true
        }
    }
}
