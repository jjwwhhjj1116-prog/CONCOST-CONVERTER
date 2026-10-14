# Stage 1: LibreDWG (dwgwrite / dwgread) 정적 바이너리 빌더
FROM python:3.11-slim-bookworm AS dwg-builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl xz-utils ca-certificates \
    && mkdir -p /tmp/libredwg \
    && curl -fsSL "https://github.com/LibreDWG/libredwg/releases/download/0.14/libredwg-0.14.tar.xz" | tar -xJ -C /tmp/libredwg --strip-components=1 \
    && cd /tmp/libredwg \
    && ./configure --disable-bindings --disable-doc --enable-shared=no \
    && make -j$(nproc) -C src \
    && make -j$(nproc) -C programs dwgwrite dwgread \
    && install -m 0755 programs/dwgwrite programs/dwgread /usr/local/bin/

# Stage 2: CONCOST Total Converter 클라우드 런타임
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PORT=8000

WORKDIR /app

# 한글 폰트(나눔고딕) 설치 및 LibreDWG 바이너리 복사
RUN apt-get update && apt-get install -y --no-install-recommends \
    fonts-nanum ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dwg-builder /usr/local/bin/dwgwrite /usr/local/bin/dwgwrite
COPY --from=dwg-builder /usr/local/bin/dwgread /usr/local/bin/dwgread

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/requirements.txt

COPY backend /app/backend
COPY frontend /app/frontend

RUN mkdir -p /app/storage/uploads /app/storage/outputs

EXPOSE 8000

CMD ["sh", "-c", "uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
