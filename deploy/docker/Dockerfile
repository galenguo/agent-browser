FROM python:3.11-slim

# 使用中科大 Debian 镜像源（国内网络加速）
RUN sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.ustc.edu.cn|g' /etc/apt/sources.list 2>/dev/null || true

# 使用清华 PyPI 镜像源（加速 pip 下载）
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple

# 系统基础依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    xvfb \
    x11vnc \
    novnc \
    websockify \
    libnss3 \
    libxss1 \
    libx11-xcb1 \
    libatk-bridge2.0-0 \
    libgtk-3-0 \
    libdrm2 \
    libgbm1 \
    libxshmfence1 \
    libxrandr2 \
    libpangocairo-1.0-0 \
    libxcomposite1 \
    libxdamage1 \
    libxfixes3 \
    libxkbcommon0 \
    libasound2-dev \
    fonts-wqy-zenhei \
    fonts-liberation \
    fonts-dejavu-core \
    fonts-freefont-ttf \
    curl \
    wget \
    procps \
    gcc \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 中文字体（单独层，体积较大）
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 升级 pip 并安装 Python 依赖
COPY requirements.txt .
RUN pip install --upgrade pip setuptools wheel && \
    pip install --no-cache-dir --timeout 120 --retries 5 -r requirements.txt

# 只下载 CloakBrowser 二进制（跳过 patchright 的 Chromium，节省约 1GB）
RUN python -c "import cloakbrowser; cloakbrowser.ensure_binary()" || true

# 清理编译依赖
RUN apt-get purge -y gcc python3-dev && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache/pip

# 复制应用代码（保留 stealth_browser 包名，因为内部 import 依赖它）
COPY stealth_browser/ /app/stealth_browser/

# 数据目录
RUN mkdir -p /data/sessions /data/profiles /data/logs

# 环境变量
ENV DISPLAY=:99 \
    CDP_PORT=19222 \
    HEADLESS=false \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    REBROWSER_PATCHES_RUNTIME_FIX_MODE=addBinding \
    TZ=Asia/Shanghai \
    LANG=zh_CN.UTF-8 \
    LANGUAGE=zh_CN:zh \
    LC_ALL=zh_CN.UTF-8

# 复制 entrypoint
COPY deploy/docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000 6080 5900

ENTRYPOINT ["/entrypoint.sh"]
