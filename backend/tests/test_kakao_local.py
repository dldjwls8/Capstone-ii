"""
지역 배송 — Kakao Mobility API 통합 테스트

실행:
    cd backend
    .venv/Scripts/python -m pytest tests/test_kakao_local.py -v -s --tb=short

범위:
    - 지역 배송 모드(local) NxN 시간·거리 행렬 검증
    - OR-Tools TSP 최적 경로 + 누적 운전시간 기반 휴게소 삽입
      - 단거리(누적 < 1h40m): 휴게소 삽입 없음이 정상
      - 장시간 지역 배송: 도심 거점(주차장·편의점 등) 삽입

참고:
    - 지역 배송 휴게 후보는 고속도로 졸음쉼터(CSV)가 아닌
      LOCAL_REST_CANDIDATES(도심 거점)를 사용합니다.
    - 일부 시내 구간은 다중목적지 API가 경로를 반환하지 않을 수 있습니다
      (카카오 로컬 API 제약). 해당 구간은 "API 미반환"으로 표시됩니다.
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.kakao import build_time_matrix, search_local_rest_candidates
from app.services.optimizer import solve_tsp
from app.services.rest_stop_inserter import RouteNode, insert_rest_stops, REST_PLAN_SEC

from tests.helpers import (
    LOCAL_NODES,
    LOCAL_REST_CANDIDATES,
    fmt_time,
    print_matrix,
    print_route_with_cumulative,
    collect_rest_in_segment,
    skip_if_no_key,
)

_UNREACHABLE_SEC = 10_800_000  # kakao.py 와 동일 — API 미반환 구간 감지용


def _is_reachable(sec: int) -> bool:
    return sec < _UNREACHABLE_SEC


# ── 1. NxN 시간·거리 행렬 ────────────────────────────────────────────────────

class TestLocalDeliveryMatrix:
    """지역 배송 모드 — 시간·거리 행렬 기본 검증"""

    def test_matrix_shape(self):
        """NxN 행렬이 올바른 크기로 반환됩니다."""
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LOCAL_NODES, route_mode="local")
        )
        n = len(LOCAL_NODES)
        print_matrix("지역 배송 모드", LOCAL_NODES, time_matrix, dist_matrix)
        assert len(time_matrix) == n
        assert len(dist_matrix) == n
        assert all(len(row) == n for row in time_matrix)
        assert all(len(row) == n for row in dist_matrix)

    def test_reachable_segments_under_50km(self):
        """API가 경로를 반환한 구간의 거리는 50km 이하여야 합니다.
        미반환 구간(API 제약)은 검증에서 제외합니다.
        """
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LOCAL_NODES, route_mode="local")
        )
        n = len(LOCAL_NODES)
        print(f"\n{'='*65}")
        print("  지역 배송 모드 — 구간별 경로 현황")
        print(f"{'='*65}")
        reachable, unreachable = 0, 0
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                if _is_reachable(time_matrix[i][j]):
                    dist_km = dist_matrix[i][j] / 1000
                    t = fmt_time(time_matrix[i][j])
                    print(f"  ✓ {LOCAL_NODES[i]['name']} → {LOCAL_NODES[j]['name']}: {dist_km:.1f}km, {t}")
                    assert dist_km <= 50, f"거리 초과: [{i}][{j}] = {dist_km:.1f}km"
                    reachable += 1
                else:
                    print(f"  ✗ {LOCAL_NODES[i]['name']} → {LOCAL_NODES[j]['name']}: API 미반환 (카카오 로컬 제약)")
                    unreachable += 1
        print(f"{'─'*65}")
        print(f"  도달 가능: {reachable}개   미반환: {unreachable}개")

    def test_diagonal_is_zero(self):
        """대각선(자기 자신 → 자기 자신)은 0이어야 합니다."""
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LOCAL_NODES, route_mode="local")
        )
        for i in range(len(LOCAL_NODES)):
            assert time_matrix[i][i] == 0
            assert dist_matrix[i][i] == 0


# ── 2. TSP 최적화 + 법정 휴게소 삽입 ────────────────────────────────────────

class TestLocalDeliveryTspAndRest:
    """지역 배송 — TSP 최적 경로 + 누적 운전시간 기반 휴게소 삽입

    ※ 지역 배송 휴게 후보: 도심 거점(주차장·휴게 공간) — LOCAL_REST_CANDIDATES
       고속도로 졸음쉼터(CSV)는 지역 배송과 무관하므로 사용하지 않습니다.
    """

    def test_route_sequence_and_rest_insertion(self):
        """TSP 경로에서 API 미반환 구간을 제외하고 유효 누적 운전시간을 계산합니다.
        유효 누적이 1h40m 초과 시 도심 거점을 휴게소로 삽입합니다.
        """
        skip_if_no_key()

        async def _run():
            time_matrix, dist_matrix = await build_time_matrix(
                LOCAL_NODES, route_mode="local"
            )
            order      = solve_tsp(time_matrix)
            full_order = order + [len(LOCAL_NODES) - 1]
            n          = len(full_order)

            nodes_obj = [
                RouteNode(
                    type="origin" if idx == 0 else (
                        "destination" if idx == len(LOCAL_NODES) - 1 else "waypoint"
                    ),
                    name=LOCAL_NODES[idx]["name"],
                    lat=LOCAL_NODES[idx]["lat"],
                    lon=LOCAL_NODES[idx]["lon"],
                )
                for idx in range(len(LOCAL_NODES))
            ]
            ordered_nodes  = [nodes_obj[i] for i in full_order]
            reordered_time = [
                [time_matrix[full_order[i]][full_order[j]] for j in range(n)]
                for i in range(n)
            ]
            reordered_dist = [
                [dist_matrix[full_order[i]][full_order[j]] for j in range(n)]
                for i in range(n)
            ]
            # 지역 배송 전용 도심 거점 후보 사용
            result = await insert_rest_stops(
                ordered_nodes, reordered_time, LOCAL_REST_CANDIDATES
            )
            return order, full_order, time_matrix, dist_matrix, result

        order, full_order, time_matrix, dist_matrix, result = asyncio.run(_run())

        rest_in_segment = collect_rest_in_segment(result)

        # ── 도심 휴게 후보 목록 출력 ─────────────────────────────────────
        print(f"\n{'='*65}")
        print("  지역 배송 휴게 후보 (도심 거점)")
        print(f"{'='*65}")
        for i, c in enumerate(LOCAL_REST_CANDIDATES, 1):
            print(f"  {i}. {c['name']}  ({c['latitude']:.4f}, {c['longitude']:.4f})")

        # ── 경로 + 누적 운전시간 출력 (API 미반환 구간 명시) ─────────────
        print(f"\n{'='*65}")
        print("  지역 배송 경로 — 구간별 누적 운전시간 및 휴게소")
        print(f"  ※ 경유지(배송지) 도착·출발 = 연속 운전")
        print(f"  ※ API 미반환 구간은 '—' 로 표시, 유효 누적에서 제외")
        print(f"{'='*65}")

        cum_valid_sec = 0   # API 미반환 구간 제외한 유효 누적 운전
        total_valid_sec = 0
        total_m = 0
        dest_idx = len(LOCAL_NODES) - 1

        for i in range(len(full_order) - 1):
            a, b    = full_order[i], full_order[i + 1]
            seg_sec = time_matrix[a][b]
            seg_m   = dist_matrix[a][b]
            reachable = _is_reachable(seg_sec)

            from_tag = "[출발]" if i == 0 else "[경유]"
            to_tag   = "[목적]" if b == dest_idx else "[경유]"
            print(f"\n  {i+1}구간  {from_tag} {LOCAL_NODES[a]['name']}"
                  f"  →  {to_tag} {LOCAL_NODES[b]['name']}")

            if reachable:
                total_valid_sec += seg_sec
                total_m         += seg_m
                cum_valid_sec   += seg_sec
                print(f"       거리/시간  : {seg_m/1000:.1f}km,  {fmt_time(seg_sec)}")
                print(f"       유효 누적  : {fmt_time(cum_valid_sec)}"
                      f"  (= {cum_valid_sec}초 / 임계 {REST_PLAN_SEC}초)")
            else:
                print(f"       거리/시간  : — (API 미반환, 유효 누적 미반영)")
                print(f"       유효 누적  : {fmt_time(cum_valid_sec)}  (변동 없음)")

            if i in rest_in_segment:
                rest = rest_in_segment[i]
                print(f"       ┌─ ⚠ 누적 {fmt_time(cum_valid_sec)} — 임계값 초과")
                print(f"       ★ 도심 휴게소 삽입: {rest.name}"
                      f"  ({rest.lat:.4f}, {rest.lon:.4f})")
                print(f"       └─ 최소 {rest.min_rest_minutes}분 휴식 후 출발 → 누적 리셋")
                cum_valid_sec = 0

        print(f"\n{'─'*65}")
        print(f"  유효 거리     : {total_m/1000:.1f}km")
        print(f"  유효 운전시간 : {fmt_time(total_valid_sec)}")
        print(f"  휴게소        : {len(rest_in_segment)}곳 삽입"
              f"  (도심 후보 {len(LOCAL_REST_CANDIDATES)}개 중)")

        assert order[0] == 0, f"TSP 첫 노드가 출발지(0)가 아님: {order}"
        assert result[0].type  == "origin"
        assert result[-1].type == "destination"

    def test_visits_all_nodes(self):
        """TSP 결과가 출발지를 포함한 모든 경유지 인덱스를 포함해야 합니다."""
        skip_if_no_key()
        time_matrix, _ = asyncio.run(
            build_time_matrix(LOCAL_NODES, route_mode="local")
        )
        order = solve_tsp(time_matrix)
        assert set(order) == set(range(len(LOCAL_NODES) - 1))

    def test_total_distance_positive(self):
        """도달 가능한 구간의 총 거리는 양수여야 합니다."""
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LOCAL_NODES, route_mode="local")
        )
        order      = solve_tsp(time_matrix)
        full_order = order + [len(LOCAL_NODES) - 1]

        print(f"\n{'='*65}")
        print("  지역 배송 TSP 경로 — 구간 요약")
        print(f"{'='*65}")
        total_sec = 0
        total_m   = 0
        for i in range(len(full_order) - 1):
            a, b    = full_order[i], full_order[i + 1]
            seg_sec = time_matrix[a][b]
            seg_m   = dist_matrix[a][b]
            if _is_reachable(seg_sec):
                total_sec += seg_sec
                total_m   += seg_m
                print(f"  {i+1}. {LOCAL_NODES[a]['name']} → {LOCAL_NODES[b]['name']}: "
                      f"{seg_m/1000:.1f}km, {fmt_time(seg_sec)}")
            else:
                print(f"  {i+1}. {LOCAL_NODES[a]['name']} → {LOCAL_NODES[b]['name']}: "
                      f"API 미반환")
        print(f"{'─'*65}")
        print(f"  유효 거리: {total_m/1000:.1f}km   유효 운전: {fmt_time(total_sec)}")

        assert total_m >= 0, "총 거리가 음수입니다."


# ── 3. Kakao Local API 위치 검색 ─────────────────────────────────────────────

class TestLocalSearch:
    """Kakao Local API — 실시간 도심 휴게 후보 검색 검증

    search_local_rest_candidates() 를 직접 호출해 결과를 검증합니다.
    카카오 로컬 API 카테고리:
        PK6 = 주차장   CE7 = 카페   CS2 = 편의점
    """

    def test_search_returns_results(self):
        """서울 시내(강남역 부근) 반경 1km 에서 후보가 1건 이상 반환됩니다."""
        skip_if_no_key()
        # 강남역 중심 (37.4979, 127.0276)
        candidates = asyncio.run(
            search_local_rest_candidates(
                center_lat=37.4979, center_lon=127.0276,
                radius_m=1_000,
            )
        )
        print(f"\n{'='*65}")
        print("  Kakao Local 검색 결과 — 강남역 반경 1km")
        print(f"{'='*65}")
        if candidates:
            for i, c in enumerate(candidates, 1):
                print(f"  {i:3}. [{c['category']}] {c['name']}")
                print(f"       {c['address']}")
                print(f"       ({c['latitude']:.4f}, {c['longitude']:.4f})")
        else:
            print("  ※ 검색 결과 없음")
        print(f"{'─'*65}")
        print(f"  총 {len(candidates)}건 반환")
        assert len(candidates) >= 1, "도심 후보가 1건도 반환되지 않았습니다."

    def test_search_result_fields(self):
        """반환된 각 후보가 필수 필드(name/latitude/longitude/category/is_active)를 가집니다."""
        skip_if_no_key()
        candidates = asyncio.run(
            search_local_rest_candidates(
                center_lat=37.5215, center_lon=126.9244,  # 여의도
                radius_m=1_500,
                categories=["PK6"],  # 주차장만
            )
        )
        print(f"\n{'='*65}")
        print("  여의도 반경 1.5km — 주차장(PK6) 후보")
        print(f"{'='*65}")
        for c in candidates:
            print(f"  {c['name']}  {c['address']}")
        assert all(
            isinstance(c.get("name"), str) and
            isinstance(c.get("latitude"), float) and
            isinstance(c.get("longitude"), float) and
            isinstance(c.get("is_active"), bool)
            for c in candidates
        ), "후보 필드 형식 오류"

    def test_search_categories_variety(self):
        """PK6·CE7·CS2 세 카테고리가 각각 결과를 반환합니다(홍대입구 반경 2km)."""
        skip_if_no_key()
        cats = ["PK6", "CE7", "CS2"]
        print(f"\n{'='*65}")
        print("  홍대입구 반경 2km — 카테고리별 검색")
        print(f"{'='*65}")
        counts: dict[str, int] = {}
        for cat in cats:
            result = asyncio.run(
                search_local_rest_candidates(
                    center_lat=37.5577, center_lon=126.9244,
                    radius_m=2_000,
                    categories=[cat],
                    max_per_category=5,
                )
            )
            counts[cat] = len(result)
            label = {"PK6": "주차장", "CE7": "카페   ", "CS2": "편의점"}.get(cat, cat)
            print(f"  {label} ({cat}): {len(result)}건")
            for c in result[:3]:
                print(f"    - {c['name']}  {c['address']}")
        total = sum(counts.values())
        print(f"{'─'*65}")
        print(f"  카테고리 합계: {total}건")
        assert total >= 1, "세 카테고리 중 결과가 하나도 없습니다."

    def test_search_used_in_tsp_pipeline(self):
        """search_local_rest_candidates 결과를 insert_rest_stops 에 직접 투입합니다.
        하드코딩 후보 없이 실시간 검색 결과만으로 파이프라인이 동작해야 합니다.
        """
        skip_if_no_key()

        async def _run():
            # 경로 중심 계산 (LOCAL_NODES 평균)
            center_lat = sum(n["lat"] for n in LOCAL_NODES) / len(LOCAL_NODES)
            center_lon = sum(n["lon"] for n in LOCAL_NODES) / len(LOCAL_NODES)

            # 1) 실시간으로 도심 휴게 후보 검색
            candidates = await search_local_rest_candidates(
                center_lat=center_lat, center_lon=center_lon,
                radius_m=3_000,
            )

            # 2) 행렬 계산 + TSP
            time_matrix, dist_matrix = await build_time_matrix(
                LOCAL_NODES, route_mode="local"
            )
            order      = solve_tsp(time_matrix)
            full_order = order + [len(LOCAL_NODES) - 1]
            n          = len(full_order)

            nodes_obj = [
                RouteNode(
                    type="origin" if idx == 0 else (
                        "destination" if idx == len(LOCAL_NODES) - 1 else "waypoint"
                    ),
                    name=LOCAL_NODES[idx]["name"],
                    lat=LOCAL_NODES[idx]["lat"],
                    lon=LOCAL_NODES[idx]["lon"],
                )
                for idx in range(len(LOCAL_NODES))
            ]
            ordered_nodes  = [nodes_obj[i] for i in full_order]
            reordered_time = [
                [time_matrix[full_order[i]][full_order[j]] for j in range(n)]
                for i in range(n)
            ]

            # 3) 휴게소 삽입 (검색 결과 사용)
            result = await insert_rest_stops(
                ordered_nodes, reordered_time,
                candidates if candidates else LOCAL_REST_CANDIDATES,  # fallback
            )
            return candidates, result

        candidates, result = asyncio.run(_run())

        rest_nodes = [r for r in result if r.type == "rest_stop"]

        print(f"\n{'='*65}")
        print("  실시간 검색 후보 → 파이프라인 통합 결과")
        print(f"{'='*65}")
        print(f"  후보 {len(candidates)}건 (실시간 검색)" if candidates
              else "  ※ 검색 결과 없음 — LOCAL_REST_CANDIDATES fallback 사용")
        print(f"  최종 경로 노드 수  : {len(result)}")
        print(f"  삽입된 휴게소 수   : {len(rest_nodes)}")
        for r in rest_nodes:
            print(f"    ★ {r.name}  ({r.lat:.4f}, {r.lon:.4f})")

        assert result[0].type  == "origin"
        assert result[-1].type == "destination"
