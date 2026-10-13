-- 사내 PC 변환 엔진의 터널 URL 등록 테이블
CREATE TABLE IF NOT EXISTS engine_registry (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
