import asyncio
from datetime import datetime
from math import atan2, cos, radians, sin, sqrt
from typing import Any, Literal

import httpx
from cachetools import TTLCache

from app.core.config import settings

KAKAO_BASE = "https://apis-navi.kakaomobility.com/v1"

# 경로 탐색 실패 시 대체값 — 사실상 해당 경로를 TSP에서 제외
_UNREACHABLE_SEC = 10_800_000

# 다중 목적지 API 탐색 반경 (최대 10,000m) — 지역 배송 모드에서 사용
_LOCAL_RADIUS_M = 10_000

# TTL 캐시 — 1시간(3600초) 이내 동일 구간 재호출 방지
# maxsize: 최대 캐시 항목 수 (실시간/미래 개별 구간 각각)
_cache_realtime: TTLCache = TTLCache(maxsize=2_000, ttl=3_600)
_cache_future:   TTLCache = TTLCache(maxsize=2_000, ttl=3_600)
_cache_multi:    TTLCache = TTLCache(maxsize=500,   ttl=3_600)

async def _get_route_time_future(
    client: httpx.AsyncClient,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
    *,
    departure_time: str,
) -> int:
    """미래 운행 정보 길찾기 API로 두 지점 간 소요 시간(초)을 반환합니다."""
    # departure_time 형식: ISO-8601 → YYYYMMDDHHMM (12자리, API 스펙)
    try:
        dt = datetime.fromisoformat(departure_time)
        dt_str = dt.strftime("%Y%m%d%H%M")
    except ValueError:
        dt_str = departure_time[:12]  # 이미 올바른 포맷이면 앞 12자리만 사용

    cache_key = (round(origin_lat, 5), round(origin_lon, 5),
                 round(dest_lat, 5),   round(dest_lon, 5), dt_str)
    if cache_key in _cache_future:
        return _cache_future[cache_key]

    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = await client.get(
        f"{KAKAO_BASE}/future/directions",
        params={
            "origin": f"{origin_lon},{origin_lat}",
            "destination": f"{dest_lon},{dest_lat}",
            "departure_time": dt_str,
            "summary": "true",
        },
        headers=headers,
    )
    resp.raise_for_status()
    summary = resp.json()["routes"][0]["summary"]
    result = (int(summary["duration"]), int(summary["distance"]))
    _cache_future[cache_key] = result
    return result


async def _get_route_time_realtime(
    client: httpx.AsyncClient,
    origin_lat: float,
    origin_lon: float,
    dest_lat: float,
    dest_lon: float,
) -> tuple[int, int]:
    """자동차 길찾기 API로 두 지점 간 실시간 소요 시간(초)·거리(m)를 반환합니다."""
    cache_key = (round(origin_lat, 5), round(origin_lon, 5),
                 round(dest_lat, 5),   round(dest_lon, 5))
    if cache_key in _cache_realtime:
        return _cache_realtime[cache_key]

    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_API_KEY}",
        "Content-Type": "application/json",
    }
    resp = await client.get(
        f"{KAKAO_BASE}/directions",
        params={
            "origin": f"{origin_lon},{origin_lat}",
            "destination": f"{dest_lon},{dest_lat}",
            "summary": "true",
        },
        headers=headers,
    )
    resp.raise_for_status()
    summary = resp.json()["routes"][0]["summary"]
    result = (int(summary["duration"]), int(summary["distance"]))
    _cache_realtime[cache_key] = result
    return result


async def _get_row_times_multi_dest(
    client: httpx.AsyncClient,
    origin: dict,
    destinations: list[dict],
    dest_indices: list[int],
) -> list[tuple[int, int, int]]:
    """다중 목적지 길찾기 API로 출발지 → 여러 목적지 소요 시간(초)·거리(m)를 일괄 조회합니다.
    반환값: [(dest_index, duration_sec, distance_m), ...]
    """
    orig_key = (round(origin["lat"], 5), round(origin["lon"], 5))
    dest_keys = tuple(
        (round(d["lat"], 5), round(d["lon"], 5)) for d in destinations
    )
    cache_key = (orig_key, dest_keys)

    if cache_key in _cache_multi:
        cached_dur, cached_dist = _cache_multi[cache_key]
        return [(dest_indices[i], cached_dur[i], cached_dist[i]) for i in range(len(dest_indices))]

    headers = {
        "Authorization": f"KakaoAK {settings.KAKAO_API_KEY}",
        "Content-Type": "application/json",
    }
    body = {
        "origin": {"x": str(origin["lon"]), "y": str(origin["lat"])},
        "destinations": [
            {"x": str(d["lon"]), "y": str(d["lat"]), "key": str(idx)}
            for idx, d in zip(dest_indices, destinations)
        ],
        "radius": _LOCAL_RADIUS_M,
        "priority": "TIME",
    }
    resp = await client.post(
        f"{KAKAO_BASE}/destinations/directions",
        json=body,
        headers=headers,
    )
    resp.raise_for_status()

    results: list[tuple[int, int, int]] = []
    durations: list[int] = [_UNREACHABLE_SEC] * len(destinations)
    distances: list[int] = [0] * len(destinations)
    for route in resp.json()["routes"]:
        j = int(route["key"])
        if route.get("result_code", -1) == 0:
            dur  = int(route["summary"]["duration"])
            dist = int(route["summary"]["distance"])
        else:
            dur, dist = _UNREACHABLE_SEC, 0
        results.append((j, dur, dist))
        if j in dest_indices:
            pos = dest_indices.index(j)
            durations[pos] = dur
            distances[pos] = dist

    _cache_multi[cache_key] = (tuple(durations), tuple(distances))
    return results


async def build_time_matrix(
    nodes: list[dict],
    *,
    route_mode: Literal["local", "long_distance"] = "long_distance",
    departure_time: str | None = None,
    # Kakao는 차량 제원 파라미터를 지원하지 않으므로 서명 호환용으로만 유지
    height_m: float | None = None,
    weight_kg: float | None = None,
    length_cm: float | None = None,
    width_cm: float | None = None,
) -> tuple[list[list[int]], list[list[int]]]:
    """N개 노드 리스트로 (시간 행렬, 거리 행렬) 을 반환합니다.

    시간 행렬: NxN, 단위 초
    거리 행렬: NxN, 단위 m

    route_mode:
      - "local"         : 지역 배송 — 다중 목적지 API (N회 호출, 반경 10km 이내)
      - "long_distance" : 장거리 화물 — 자동차 길찾기 API 개별 호출 (N²-N회)

    departure_time 있으면 두 모드 모두 미래 운행 정보 API로 전환 (다중 목적지 API가 미지원)
    """
    n = len(nodes)
    matrix: list[list[int]] = [[0] * n for _ in range(n)]
    dist_matrix: list[list[int]] = [[0] * n for _ in range(n)]

    async with httpx.AsyncClient(timeout=15.0) as client:
        if departure_time:
            # 미래 교통 반영 — 두 모드 공통으로 개별 호출 (N²-N 회)
            async def fetch_future(i: int, j: int) -> tuple[int, int, int, int]:
                dur, dist = await _get_route_time_future(
                    client,
                    nodes[i]["lat"], nodes[i]["lon"],
                    nodes[j]["lat"], nodes[j]["lon"],
                    departure_time=departure_time,
                )
                return i, j, dur, dist

            tasks = [fetch_future(i, j) for i in range(n) for j in range(n) if i != j]
            for i, j, dur, dist in await asyncio.gather(*tasks):
                matrix[i][j] = dur
                dist_matrix[i][j] = dist

        elif route_mode == "local":
            # 지역 배송 — 다중 목적지 API로 행(row) 단위 일괄 조회 (N회 호출)
            async def fetch_row(i: int) -> tuple[int, list[tuple[int, int, int]]]:
                dest_indices = [j for j in range(n) if j != i]
                dest_nodes = [nodes[j] for j in dest_indices]
                row_results = await _get_row_times_multi_dest(
                    client, nodes[i], dest_nodes, dest_indices
                )
                return i, row_results

            rows = await asyncio.gather(*[fetch_row(i) for i in range(n)])
            for i, row_results in rows:
                for j, dur, dist in row_results:
                    matrix[i][j] = dur
                    dist_matrix[i][j] = dist

        else:
            # 장거리 화물 — 자동차 길찾기 API 개별 호출 (N²-N 회, 거리 제한 없음)
            async def fetch_long(i: int, j: int) -> tuple[int, int, int, int]:
                dur, dist = await _get_route_time_realtime(
                    client,
                    nodes[i]["lat"], nodes[i]["lon"],
                    nodes[j]["lat"], nodes[j]["lon"],
                )
                return i, j, dur, dist

            tasks = [fetch_long(i, j) for i in range(n) for j in range(n) if i != j]
            for i, j, dur, dist in await asyncio.gather(*tasks):
                matrix[i][j] = dur
                dist_matrix[i][j] = dist

    return matrix, dist_matrix


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """두 좌표 간 Haversine 거리(km)를 반환합니다."""
    R = 6_371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * atan2(sqrt(a), sqrt(1 - a))


async def find_best_rest_stop(
    prev: Any,
    nxt: Any,
    candidates: list[dict],
    pre_filter_km: float = 50.0,
) -> dict | None:
    """
    2단계 휴게소 후보 선택:
    1. Haversine으로 구간 중간지점 기준 pre_filter_km km 이내 후보 사전 필터링
    2. 다중 목적지 API로 prev→후보, nxt→후보 실제 도로 소요시간 조회 후 최적 반환
       (nxt→후보 ≈ 후보→nxt 방향 대칭 근사)

    API 호출 실패 시 Haversine 기반 fallback으로 최적 후보 반환.

    Args:
        prev / nxt    : .lat, .lon 속성을 가진 객체 (RouteNode 등)
        candidates    : 휴게소 후보 목록 {"latitude", "longitude", "name", "is_active"}
        pre_filter_km : Haversine 사전 필터 반경 (기본 50km)
    """
    active = [c for c in candidates if c.get("is_active", True)]
    if not active:
        return None

    # ── 1. Haversine 사전 필터 ───────────────────────────────────────────────
    mid_lat = (prev.lat + nxt.lat) / 2
    mid_lon = (prev.lon + nxt.lon) / 2

    filtered = [
        c for c in active
        if _haversine_km(mid_lat, mid_lon, c["latitude"], c["longitude"]) <= pre_filter_km
    ]
    if not filtered:
        # 반경 내 후보 없음 → 전체에서 Haversine 최적 반환
        return min(
            active,
            key=lambda c: (
                _haversine_km(prev.lat, prev.lon, c["latitude"], c["longitude"])
                + _haversine_km(c["latitude"], c["longitude"], nxt.lat, nxt.lon)
            ),
        )

    # ── 2. 다중 목적지 API — prev→후보, nxt→후보 소요시간 조회 ───────────────
    _BATCH = 30
    prev_dict = {"lat": prev.lat, "lon": prev.lon}
    nxt_dict  = {"lat": nxt.lat,  "lon": nxt.lon}

    # times[i] = [from_prev_sec, from_nxt_sec]
    times: dict[int, list[int]] = {
        i: [_UNREACHABLE_SEC, _UNREACHABLE_SEC] for i in range(len(filtered))
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for start in range(0, len(filtered), _BATCH):
                batch = filtered[start : start + _BATCH]
                indices = list(range(start, start + len(batch)))
                dest_nodes = [{"lat": c["latitude"], "lon": c["longitude"]} for c in batch]

                for idx, t, _ in await _get_row_times_multi_dest(client, prev_dict, dest_nodes, indices):
                    times[idx][0] = t
                for idx, t, _ in await _get_row_times_multi_dest(client, nxt_dict, dest_nodes, indices):
                    times[idx][1] = t

    except Exception:
        # API 실패 시 Haversine fallback
        return min(
            filtered,
            key=lambda c: (
                _haversine_km(prev.lat, prev.lon, c["latitude"], c["longitude"])
                + _haversine_km(c["latitude"], c["longitude"], nxt.lat, nxt.lon)
            ),
        )

    best_idx = min(times, key=lambda i: times[i][0] + times[i][1])
    return filtered[best_idx]
