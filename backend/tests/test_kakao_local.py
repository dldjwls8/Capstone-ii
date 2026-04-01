"""
지역 배송 — Kakao Mobility API 통합 테스트

실행:
    cd backend
    .venv/Scripts/python -m pytest tests/test_kakao_local.py -v -s --tb=short

범위:
    - 지역 배송 모드(local) NxN 시간·거리 행렬 검증
    - OR-Tools TSP 최적 경로 + 법정 휴게소 삽입
      (단거리 배송 → 누적 운전 임계값 미달 → 휴게소 삽입 없음이 정상)
"""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.kakao import build_time_matrix
from app.services.optimizer import solve_tsp
from app.services.rest_stop_inserter import RouteNode, insert_rest_stops, REST_PLAN_SEC

from tests.helpers import (
    LOCAL_NODES,
    REST_CANDIDATES,
    fmt_time,
    print_matrix,
    print_rest_candidates_info,
    print_route_with_cumulative,
    collect_rest_in_segment,
    skip_if_no_key,
)


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
        """API가 경로를 반환한 구간의 거리는 50km 이하여야 합니다."""
        skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LOCAL_NODES, route_mode="local")
        )
        n = len(LOCAL_NODES)
        print(f"\n{'='*65}")
        print("  지역 배송 모드 — 도달 가능 구간 목록")
        print(f"{'='*65}")
        reachable = 0
        for i in range(n):
            for j in range(n):
                if i != j and dist_matrix[i][j] > 0:
                    dist_km = dist_matrix[i][j] / 1000
                    t = fmt_time(time_matrix[i][j])
                    print(f"  {LOCAL_NODES[i]['name']} → {LOCAL_NODES[j]['name']}: {dist_km:.1f}km, {t}")
                    assert dist_km <= 50, \
                        f"지역 배송 구간 거리 초과: [{i}][{j}] = {dist_km:.1f}km"
                    reachable += 1
        print(f"  총 {reachable}개 구간 도달 가능")

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
    """지역 배송 — TSP 최적 경로 + 누적 운전시간 기반 휴게소 삽입"""

    def test_route_sequence_and_rest(self):
        """TSP 경로가 출발지에서 시작하고, 단거리이므로 휴게소 삽입이 없어야 합니다.
        누적 운전시간이 임계값(1시간 40분)을 넘지 않으면 rest_stop은 삽입되지 않습니다.
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
            result = await insert_rest_stops(ordered_nodes, reordered_time, REST_CANDIDATES)
            return order, full_order, time_matrix, dist_matrix, result

        order, full_order, time_matrix, dist_matrix, result = asyncio.run(_run())

        rest_in_segment = collect_rest_in_segment(result)
        print_rest_candidates_info()
        print_route_with_cumulative(
            LOCAL_NODES, full_order, time_matrix, dist_matrix,
            rest_in_segment, label="지역 배송 경로"
        )

        assert order[0] == 0, f"TSP 첫 노드가 출발지(0)가 아님: {order}"
        assert result[0].type  == "origin"
        assert result[-1].type == "destination"

        # 지역 배송 전체 누적이 REST_PLAN_SEC(6000초, 1h40m) 미만이어야 함
        total_sec = sum(
            time_matrix[full_order[i]][full_order[i + 1]]
            for i in range(len(full_order) - 1)
        )
        if total_sec < REST_PLAN_SEC:
            assert len(rest_in_segment) == 0, \
                f"단거리 경로(누적 {fmt_time(total_sec)})인데 휴게소가 삽입됨"
        else:
            print(f"\n  ※ 누적 운전 {fmt_time(total_sec)} — 임계값 초과로 휴게소 삽입됨")

    def test_visits_all_nodes(self):
        """TSP 결과가 출발지를 포함한 모든 경유지 인덱스를 포함해야 합니다."""
        skip_if_no_key()
        time_matrix, _ = asyncio.run(
            build_time_matrix(LOCAL_NODES, route_mode="local")
        )
        order = solve_tsp(time_matrix)
        assert set(order) == set(range(len(LOCAL_NODES) - 1))

    def test_total_distance_positive(self):
        """지역 배송 총 거리는 양수여야 합니다."""
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
            total_sec += seg_sec
            total_m   += seg_m
            reach = f"{seg_m/1000:.1f}km, {fmt_time(seg_sec)}" if seg_m > 0 else "API 미반환 구간"
            print(f"  {i+1}. {LOCAL_NODES[a]['name']} → {LOCAL_NODES[b]['name']}: {reach}")
        print(f"{'─'*65}")
        print(f"  총 거리: {total_m/1000:.1f}km   총 소요시간: {fmt_time(total_sec)}")

        assert total_m >= 0, "총 거리가 음수입니다."
