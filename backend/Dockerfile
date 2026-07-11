# Backend runtime image. The dependency layer is intentionally stable:
# daily development mounts source code and model_weights at runtime.
FROM python:3.11-slim AS backend-env

ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

# OpenCV / dlib build and runtime dependencies.
RUN set -eux; \
    if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i "s|http://deb.debian.org/debian|${APT_MIRROR}|g; s|http://deb.debian.org/debian-security|${APT_MIRROR}-security|g; s|http://security.debian.org/debian-security|${APT_MIRROR}-security|g" /etc/apt/sources.list.d/debian.sources; \
    fi; \
    if [ -f /etc/apt/sources.list ]; then \
        sed -i "s|http://deb.debian.org/debian|${APT_MIRROR}|g; s|http://deb.debian.org/debian-security|${APT_MIRROR}-security|g; s|http://security.debian.org/debian-security|${APT_MIRROR}-security|g" /etc/apt/sources.list; \
    fi; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        build-essential \
        cmake \
        ffmpeg \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1; \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python -m pip config set global.index-url "${PIP_INDEX_URL}" \
    && python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

FROM backend-env AS dev
EXPOSE 5000
CMD ["gunicorn", "-w", "1", "--timeout", "180", "-b", "0.0.0.0:5000", "run:app"]

FROM backend-env AS prod
COPY . .
EXPOSE 5000
CMD ["gunicorn", "-w", "1", "--timeout", "180", "-b", "0.0.0.0:5000", "run:app"]
