FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    LD_LIBRARY_PATH=/usr/local/lib \
    PORT=8000

WORKDIR /app

# 한글 폰트(나눔고딕), curl, bzip2, libxml2 설치 및 프리빌트 LibreDWG(dwgwrite/dwgread) 추출
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-nanum curl bzip2 ca-certificates libxml2 ffmpeg \
    && mkdir -p /tmp/libredwg \
    && curl -fsSL "https://api.anaconda.org/download/conda-forge/libredwg/0.11.3876/linux-64/libredwg-0.11.3876-py37pl5321h77fd288_2.tar.bz2" | tar -xj -C /tmp/libredwg \
    && cp -f /tmp/libredwg/bin/dwgwrite /tmp/libredwg/bin/dwgread /usr/local/bin/ \
    && cp -fP /tmp/libredwg/lib/libredwg.so* /usr/local/lib/ \
    && chmod +x /usr/local/bin/dwgwrite /usr/local/bin/dwgread \
    && ldconfig \
    && rm -rf /tmp/libredwg /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

RUN mkdir -p /app/storage/uploads /app/storage/outputs

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
