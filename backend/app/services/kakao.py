import asyncio
from datetime import datetime

import httpx

from app.core.config import settings

KAKAO_BASE = "https://apis-navi.kakaomobility.com/v1"


async def _get_route_info(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    *,
    departure_time: str | None = None,
) -> tuple[int, int]:
    """두 지점 간 예상 소요 시간(초)과 거리(m)를 Kakao Mobility API로 반환합니다."""
    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_API_KEY}",
        "Content-Type": "application/json",
    }

    origin_str = f"{origin_lon},{origin_lat}"
    dest_str = f"{dest_lon},{dest_lat}"

    if departure_time:
        # Future Directions API — 출발 예정 시각의 미래 교통 반영
        # departure_time 형식: ISO-8601 → YYYYMMDDHHmmss 변환
        try:
            dt = datetime.fromisoformat(departure_time)
            dt_str = dt.strftime("%Y%m%d%H%M%S")
        except ValueError:
            dt_str = departure_time  # 이미 올바른 포맷이면 그대로 사용

        url = f"{KAKAO_BASE}/future/directions"
        params = {
            "origin": origin_str,
            "destination": dest_str,
            "departure_time": dt_str,
            "summary": "true",
        }
    else:
        # 실시간 길찾기 API
        url = f"{KAKAO_BASE}/directions"
        params = {
            "origin": origin_str,
            "destination": dest_str,
            "summary": "true",
        }

    async with semaphore:
        resp = await client.get(url, params=params, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    summary = data["routes"][0]["summary"]
    duration_sec = int(summary["duration"])
    distance_m = int(summary.get("distance", 0))
    return duration_sec, distance_m


async def build_time_matrix(
    nodes: list[dict],
    *,
    departure_time: str | None = None,
    # Kakao는 차량 제원 파라미터를 지원하지 않으므로 서명 호환용으로만 유지
    height_m: float | None = None,
    weight_kg: float | None = None,
    length_cm: float | None = None,
    width_cm: float | None = None,
) -> tuple[list[list[int]], list[list[int]]]:
    """N개 노드 리스트로 N×N 시간 행렬(초)과 거리 행렬(m)을 동시에 계산합니다.

    Returns:
        (time_matrix, distance_matrix) — 각각 N×N 정수 행렬
    """
    n = len(nodes)
    # Kakao 무료 플랜 10 QPS 제한 — 동시 호출 수를 10개로 제한
    semaphore = asyncio.Semaphore(10)

    async def fetch(client: httpx.AsyncClient, i: int, j: int) -> tuple[int, int, int, int]:
        if i == j:
            return i, j, 0, 0
        dur, dist = await _get_route_info(
            client, semaphore,
            nodes[i]["lat"], nodes[i]["lon"],
            nodes[j]["lat"], nodes[j]["lon"],
            departure_time=departure_time,
        )
        return i, j, dur, dist

    # 클라이언트 1개를 모든 호출이 공유 → TCP 연결 재사용
    async with httpx.AsyncClient(timeout=10.0) as client:
        tasks = [fetch(client, i, j) for i in range(n) for j in range(n)]
        results = await asyncio.gather(*tasks)

    time_matrix: list[list[int]] = [[0] * n for _ in range(n)]
    dist_matrix: list[list[int]] = [[0] * n for _ in range(n)]
    for i, j, dur, dist in results:
        time_matrix[i][j] = dur
        dist_matrix[i][j] = dist

    return time_matrix, dist_matrix
