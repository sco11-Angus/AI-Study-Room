# 算法后端镜像 (§11)
FROM python:3.11-slim

# OpenCV / dlib 运行依赖
RUN apt-get update && apt-get install -y \
    build-essential cmake libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 5000
# 生产用 gunicorn 多 worker (§11)
CMD ["gunicorn", "-w", "2", "-b", "0.0.0.0:5000", "run:app"]
