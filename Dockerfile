FROM python:3.10-slim

WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 安装 Node.js（用于构建前端）
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs

# 复制项目文件
COPY . .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 构建前端
RUN cd apps/dsa-web && \
    npm install && \
    npm run build && \
    cp -r dist ../../static && \
    cd ../..

# 暴露端口
EXPOSE 8000

# 启动命令
CMD ["python", "main.py", "--serve"]
