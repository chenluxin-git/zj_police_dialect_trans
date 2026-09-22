# 后端镜像：Python 3.10 + ffmpeg（质检转码/ffprobe 依赖）
FROM python:3.10-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先装依赖（利用层缓存）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

EXPOSE 8000

# 数据不落镜像：DATABASE_URL/AUDIO_STORAGE_PATH/EXPORT_PATH 由 .env.docker 指向 /data 卷
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
