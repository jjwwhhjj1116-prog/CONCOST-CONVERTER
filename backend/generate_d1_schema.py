"""Cloudflare D1 스키마 및 118명 임직원 데이터 생성 스크립트"""
from pathlib import Path
from backend.auth import AuthManager

def generate():
    auth = AuthManager()
    sql_lines = [
        "-- CONCOST Cloudflare D1 데이터베이스 스키마",
        "CREATE TABLE IF NOT EXISTS users (",
        "    login_id TEXT PRIMARY KEY,",
        "    name TEXT NOT NULL,",
        "    department TEXT NOT NULL,",
        "    rank TEXT NOT NULL,",
        "    password_hash TEXT NOT NULL,",
        "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        ");",
        "",
        "CREATE TABLE IF NOT EXISTS conversions (",
        "    id TEXT PRIMARY KEY,",
        "    user_id TEXT,",
        "    filename TEXT NOT NULL,",
        "    source_format TEXT NOT NULL,",
        "    target_format TEXT NOT NULL,",
        "    status TEXT NOT NULL,",
        "    file_size INTEGER,",
        "    entities_count INTEGER DEFAULT 0,",
        "    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        ");",
        "",
        "-- 임직원 118명 초기 데이터",
    ]

    for u in auth.users.values():
        lid = u.login_id.replace("'", "''")
        name = u.name.replace("'", "''")
        dept = u.department.replace("'", "''")
        rank = u.rank.replace("'", "''")
        pwd = u.password_hash
        sql_lines.append(f"INSERT OR REPLACE INTO users (login_id, name, department, rank, password_hash) VALUES ('{lid}', '{name}', '{dept}', '{rank}', '{pwd}');")

    target = Path("schema.sql")
    target.write_text("\n".join(sql_lines), encoding="utf-8")
    print(f"[PASS] Successfully generated schema.sql with {len(auth.users)} employees.")

if __name__ == "__main__":
    generate()
