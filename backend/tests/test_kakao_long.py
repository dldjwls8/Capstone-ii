"""
장거리 배송 — Kakao Mobility API 통합 테스트

실행:
    cd backend
    .venv/Scripts/python -m pytest tests/test_kakao_long.py -v -s --tb=short

범위:
    - 장거리 모드(long_distance) NxN 시간·거리 행렬 검증
    - OR-Tools TSP 최적 경로 + 법정 휴게소 삽입 (경유지는 연속 운전으로 간주)
    - 총 거리 합산 검증
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.kakao import build_time_matrix
from app.services.optimizer import solve_tsp
from app.services.rest_stop_inserter import RouteNode, insert_rest_stops

from tests.helpers import (
    LONG_NODES,
    REST_CANDIDATES,
    fmt_time,
    print_matrix,
    print_rest_candidates_info,
    print_route_with_cumulative,
    collect_rest_in_segment,
    skip_if_no_key,
)


# ── 1. NxN 시간·거리 행렬 ────────────────────────────────────────────────────

class TestLongDistanceMatrix:
    """장거리 모드 — 시간·거리 행렬 기본 검증"""

    def test_matrix_shape(self):
        """NxN 행렬이 올바른 크기로 반환됩니다."""
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        n = len(LONG_NODES)
        print_matrix("장거리 모드", LONG_NODES, time_matrix, dist_matrix)
        assert len(time_matrix) == n
        assert len(dist_matrix) == n
        assert all(len(row) == n for row in time_matrix)
        assert all(len(row) == n for row in dist_matrix)

    def test_diagonal_is_zero(self):
        """대각선(자기 자신 → 자기 자신)은 시간·거리 모두 0이어야 합니다."""
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        for i in range(len(LONG_NODES)):
            assert time_matrix[i][i] == 0
            assert dist_matrix[i][i] == 0

    def test_all_segments_positive_time(self):
        """모든 비대각선 구간의 소요시간이 양수여야 합니다."""
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        n = len(LONG_NODES)
        print(f"\n{'='*65}")
        print("  장거리 모드 — 전체 구간 소요시간")
        print(f"{'='*65}")
        for i in range(n):
            for j in range(n):
                if i != j:
                    km = dist_matrix[i][j] / 1000
                    t  = fmt_time(time_matrix[i][j])
                    print(f"  {LONG_NODES[i]['name']} → {LONG_NODES[j]['name']}: {km:.1f}km, {t}")
                    assert time_matrix[i][j] > 0, f"time_matrix[{i}][{j}] == 0"

    def test_seoul_daejeon_distance_range(self):
        """서울(강남) → 대전 구간은 80km~200km 범위여야 합니다."""
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        dist_km  = dist_matrix[0][3] / 1000
        time_str = fmt_time(time_matrix[0][3])
        print(f"\n  강남 → 대전: {dist_km:.1f}km, {time_str}")
        assert 80 <= dist_km <= 200, f"강남→대전 거리 비정상: {dist_km:.1f}km"


# ── 2. TSP 최적화 + 법정 휴게소 삽입 ────────────────────────────────────────

class TestLongDistanceTspAndRest:
    """장거리 — TSP 최적 경로 + 누적 운전시간 기반 휴게소 삽입"""

    def test_route_with_rest_stops(self):
        """TSP 경로에서 누적 운전 1시간40분 초과 시 휴게소가 삽입됩니다.
        경유지(배송지) 도착·출발은 연속 운전으로 간주합니다.
        """
        skip_if_no_key()

        async def _run():
            time_matrix, dist_matrix = await build_time_matrix(
                LONG_NODES, route_mode="long_distance"
            )
            order      = solve_tsp(time_matrix)
            full_order = order + [len(LONG_NODES) - 1]
            n          = len(full_order)

            nodes_obj = [
                RouteNode(
                    type="origin" if idx == 0 else (
                        "destination" if idx == len(LONG_NODES) - 1 else "waypoint"
                    ),
                    name=LONG_NODES[idx]["name"],
                    lat=LONG_NODES[idx]["lat"],
                    lon=LONG_NODES[idx]["lon"],
                )
                for idx in range(len(LONG_NODES))
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
            result = await insert_rest_stops(ordered_nodes, reordered_time, REST_CANDIDATES)
            return order, full_order, time_matrix, dist_matrix, result

        order, full_order, time_matrix, dist_matrix, result = asyncio.run(_run())

        rest_in_segment = collect_rest_in_segment(result)
        print_rest_candidates_info()
        print_route_with_cumulative(
            LONG_NODES, full_order, time_matrix, dist_matrix,
            rest_in_segment, label="장거리 배송 경로"
        )

        assert order[0] == 0, f"TSP 첫 노드가 출발지(0)가 아님: {order}"
        assert result[0].type  == "origin"
        assert result[-1].type == "destination"

    def test_visits_all_nodes(self):
        """TSP 결과가 출발지를 포함한 모든 경유지 인덱스를 포함해야 합니다."""
        skip_if_no_key()
        time_matrix, _ = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        order = solve_tsp(time_matrix)
        # 목적지(마지막 인덱스)는 TSP 결과에서 제외되고 뒤에 append됨
        assert set(order) == set(range(len(LONG_NODES) - 1))

    def test_total_distance_over_150km(self):
        """서울→수원→천안→대전 경로는 총 150km 이상이어야 합니다."""
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        order      = solve_tsp(time_matrix)
        full_order = order + [len(LONG_NODES) - 1]

        print(f"\n{'='*65}")
        print("  거리 기준 TSP 경로 — 구간 요약")
        print(f"{'='*65}")
        total_sec = 0
        total_m   = 0
        for i in range(len(full_order) - 1):
            a, b    = full_order[i], full_order[i + 1]
            seg_sec = time_matrix[a][b]
            seg_m   = dist_matrix[a][b]
            total_sec += seg_sec
            total_m   += seg_m
            print(f"  {i+1}. {LONG_NODES[a]['name']} → {LONG_NODES[b]['name']}: "
                  f"{seg_m/1000:.1f}km, {fmt_time(seg_sec)}")
        print(f"{'─'*65}")
        print(f"  총 거리: {total_m/1000:.1f}km   총 소요시간: {fmt_time(total_sec)}")

        assert total_m > 0,              "총 거리가 0입니다."
        assert total_m / 1000 >= 150,    f"총 거리 너무 짧음: {total_m/1000:.1f}km"
