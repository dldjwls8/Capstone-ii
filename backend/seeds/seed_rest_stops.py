"""휴게소 · 공영차고지 시드 스크립트

XLS 파일에서 '운영중' 데이터를 읽어 TMAP 지오코딩 API로 좌표를 변환한 뒤
rest_stops 테이블에 저장합니다.

사용법:
    cd C:/CapstoneII
    python -m backend.seeds.seed_rest_stops --env backend/.env

환경 변수:
    DATABASE_URL   — asyncpg DSN
    TMAP_APP_KEY   — TMAP Open API 앱 키
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import httpx
import psycopg2
import xlrd
from dotenv import load_dotenv

# ── 경로 설정 ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]          # C:/CapstoneII
sys.path.insert(0, str(ROOT / "backend"))

from app.core.config import get_settings  # noqa: E402  (경로 설정 이후 import)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── 상수 ─────────────────────────────────────────────────────────────────────
XLS_REST   = ROOT / "자료" / "휴게소정보_260325.xls"
XLS_DEPOT  = ROOT / "자료" / "공영차고지정보_260325.xls"
GEOCODE_URL = "https://apis.openapi.sk.com/tmap/geo/fullAddrGeo"

# 유형(문자열) → RestStopType(DB Enum)
TYPE_MAP = {
    "고속도로": "highway_rest",
    "국도":    "highway_rest",
    "항만":    "highway_rest",
    "차고지":  "depot",
}


# ── TMAP 지오코딩 ─────────────────────────────────────────────────────────────

async def geocode(address: str, app_key: str, sem: asyncio.Semaphore) -> tuple[float, float] | None:
    """주소 문자열 → (lat, lon). 실패 시 None 반환."""
    async with sem:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    GEOCODE_URL,
                    params={"version": "1", "fullAddr": address, "appKey": app_key},
                )
                resp.raise_for_status()
                coords = resp.json().get("coordinateInfo", {}).get("coordinate", [])
                if coords:
                    lat = float(coords[0].get("newLat") or coords[0].get("lat") or 0)
                    lon = float(coords[0].get("newLon") or coords[0].get("lon") or 0)
                    if lat and lon:
                        return lat, lon
            logger.warning("좌표 없음: %s", address)
        except Exception as exc:
            logger.warning("지오코딩 실패 (%s): %s", address, exc)
    return None


# ── XLS 파싱 ─────────────────────────────────────────────────────────────────

def parse_rest_stops() -> list[dict]:
    """휴게소정보 XLS → 운영중 레코드 목록."""
    wb = xlrd.open_workbook(str(XLS_REST))
    ws = wb.sheet_by_index(0)
    records = []
    for r in range(1, ws.nrows):
        유형   = str(ws.cell_value(r, 0)).strip()
        구분   = str(ws.cell_value(r, 1)).strip()
        이름   = str(ws.cell_value(r, 3)).strip()
        주소   = str(ws.cell_value(r, 5)).strip()
        if 구분 != "운영중" or not 주소 or not 이름:
            continue
        records.append({
            "name":    이름,
            "address": 주소,
            "type":    TYPE_MAP.get(유형, "highway_rest"),
        })
    logger.info("휴게소 운영중 %d건 로드", len(records))
    return records


def parse_depots() -> list[dict]:
    """공영차고지정보 XLS → 운영중 레코드 목록."""
    wb = xlrd.open_workbook(str(XLS_DEPOT))
    ws = wb.sheet_by_index(0)
    records = []
    for r in range(1, ws.nrows):
        구분 = str(ws.cell_value(r, 0)).strip()
        이름 = str(ws.cell_value(r, 2)).strip()
        주소 = str(ws.cell_value(r, 3)).strip()
        if 구분 != "운영중" or not 주소 or not 이름:
            continue
        records.append({
            "name":    이름,
            "address": 주소,
            "type":    "depot",
        })
    logger.info("공영차고지 운영중 %d건 로드", len(records))
    return records


# ── 시드 실행 ─────────────────────────────────────────────────────────────────

async def seed(app_key: str, db_url: str, dry_run: bool = False) -> None:
    records = parse_rest_stops() + parse_depots()
    logger.info("전체 시드 대상: %d건", len(records))

    # 좌표 병렬 변환
    sem = asyncio.Semaphore(4)
    tasks = [geocode(r["address"], app_key, sem) for r in records]
    coords_list = await asyncio.gather(*tasks)

    # 좌표 붙이기 + 실패 제외
    seeded = []
    for rec, coords in zip(records, coords_list):
        if coords is None:
            logger.warning("제외 (좌표 없음): %s / %s", rec["name"], rec["address"])
            continue
        seeded.append({**rec, "lat": coords[0], "lon": coords[1]})

    logger.info("좌표 변환 성공: %d건 / 전체 %d건", len(seeded), len(records))

    if dry_run:
        for s in seeded:
            print(f"  {s['type']:15s} {s['name']:20s} {s['lat']:.5f}, {s['lon']:.5f}  {s['address']}")
        return

    # DB 저장 — docker exec psql로 직접 삽입 (Windows asyncpg/psycopg2 인코딩 이슈 우회)
    import subprocess

    sql_lines = ["BEGIN;"]
    for s in seeded:
        name  = s["name"].replace("'", "''")
        type_ = s["type"]
        lat   = s["lat"]
        lon   = s["lon"]
        sql_lines.append(
            f"INSERT INTO rest_stops (name, type, latitude, longitude, is_active) "
            f"VALUES ('{name}', '{type_}'::reststoptype, {lat}, {lon}, TRUE) "
            f"ON CONFLICT DO NOTHING;"
        )
    sql_lines.append("COMMIT;")
    sql_lines.append("SELECT COUNT(*) AS total FROM rest_stops;")
    sql_text = "\n".join(sql_lines)

    result = subprocess.run(
        ["docker", "exec", "-i", "routeon-db",
         "psql", "-U", "routeon", "-d", "routeon"],
        input=sql_text.encode("utf-8"),
        capture_output=True,
        timeout=60,
    )
    output = result.stdout.decode("utf-8", errors="replace")
    logger.info("DB 삽입 완료:\n%s", output.strip())
    if result.returncode != 0:
        logger.error("psql 오류: %s", result.stderr.decode("utf-8", errors="replace"))


# ── 진입점 ────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="휴게소·차고지 DB 시드")
    parser.add_argument("--env", default="backend/.env", help=".env 파일 경로")
    parser.add_argument("--dry-run", action="store_true", help="DB에 쓰지 않고 결과만 출력")
    args = parser.parse_args()

    load_dotenv(args.env, override=True)
    settings = get_settings()

    if not settings.TMAP_APP_KEY:
        logger.error("TMAP_APP_KEY 가 설정되지 않았습니다. .env 파일을 확인하세요.")
        sys.exit(1)

    # Windows에서 asyncpg는 SelectorEventLoop 필요 (ProactorEventLoop 비호환)
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    asyncio.run(seed(settings.TMAP_APP_KEY, settings.DATABASE_URL, dry_run=args.dry_run))


if __name__ == "__main__":
    main()
