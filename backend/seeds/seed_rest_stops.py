"""
고속도로 휴게소 + 졸음쉼터 시드 스크립트

실행:
    cd backend
    python seeds/seed_rest_stops.py

주의: 스크립트 실행 전 .env 파일에 DATABASE_URL이 설정되어 있어야 합니다.
"""
import asyncio
import csv
import os
import sys
from pathlib import Path

# backend/ 기준으로 패키지 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

DATABASE_URL: str = os.environ["DATABASE_URL"].replace(
    "postgresql+asyncpg://", "postgresql://"
)

# 졸음쉼터 CSV 경로 (프로젝트 루트 기준)
DROWSY_CSV: Path = Path(__file__).parent.parent.parent / "자료" / "한국도로공사_졸음쉼터_20260225.csv"


async def seed() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        inserted = 0

        # ── 졸음쉼터 (한국도로공사 공공 데이터) ──────────────────────────────
        if DROWSY_CSV.exists():
            with open(DROWSY_CSV, encoding="euc-kr", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        lat = float(row.get("위도") or 0)
                        lon = float(row.get("경도") or 0)
                        name = row.get("졸음쉼터명") or "졸음쉼터"
                        direction = row.get("도로노선방향") or None
                        if lat == 0 or lon == 0:
                            continue
                        await conn.execute(
                            """
                            INSERT INTO rest_stops (name, type, latitude, longitude, direction, is_active, scope)
                            VALUES ($1, 'drowsy_shelter', $2, $3, $4, true, 'public')
                            ON CONFLICT DO NOTHING
                            """,
                            name, lat, lon, direction,
                        )
                        inserted += 1
                    except (ValueError, KeyError):
                        continue
            print(f"졸음쉼터 {inserted}건 삽입 완료")
        else:
            print(f"CSV 파일 없음: {DROWSY_CSV}")

    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(seed())
