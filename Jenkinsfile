pipeline {
    agent any

    options {
        timeout(time: 20, unit: 'MINUTES')
        timestamps()
        disableConcurrentBuilds()
    }

    environment {
        BACKEND_IMAGE = 'ai-study-room-backend-env:dev'
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
