FROM python:3.10-slim

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && \
    apt-get install -y curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_16.x | bash - && \
    apt-get update && \
    apt-get install -y \
    cron \
    nodejs git curl build-essential mariadb-client redis wget \
    supervisor \
    libcairo2-dev libpango1.0-dev libjpeg-dev libgif-dev librsvg2-dev \
    python3-dev libffi-dev libssl-dev \
    && npm install -g yarn@1.22.19 && \
    apt-get clean

# 安裝 frappe bench CLI
RUN pip install frappe-bench

# 建立 frappe 使用者與 bench 資料夾
RUN useradd -ms /bin/bash frappe
USER frappe
WORKDIR /home/frappe

# 初始化 bench 環境
RUN bench init --frappe-branch version-14 frappe-bench
WORKDIR /home/frappe/frappe-bench

# 複製啟動腳本
COPY --chmod=755 entrypoint.sh /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
