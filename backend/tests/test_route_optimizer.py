"""VRP 엔진 단위 테스트

외부 의존성(TMAP API, DB) 없이 순수 로직만 검증합니다.
실행:  pytest backend/tests/test_route_optimizer.py -v
"""

import asyncio
import math

import pytest

from app.services.route_optimizer import (
    MAX_DRIVE_SEC,
    MIN_REST_SEC,
    haversine_m,
    haversine_sec,
    insert_rest_stops,
    solve_tsp,
)


# ── 픽스처 / 헬퍼 ──────────────────────────────────────────────────────────────

def _node(name: str, lat: float, lon: float, ntype: str = "waypoint") -> dict:
    return {"name": name, "lat": lat, "lon": lon, "type": ntype}


def _matrix_from_positions(nodes: list[dict]) -> list[list[int]]:
    """테스트용: Haversine 기반으로 시간 행렬을 직접 구성합니다."""
    n = len(nodes)
    return [
        [
            0 if i == j else haversine_sec(nodes[i]["lat"], nodes[i]["lon"],
                                           nodes[j]["lat"], nodes[j]["lon"])
            for j in range(n)
        ]
        for i in range(n)
    ]


def _make_rest_stops(count: int = 3) -> list[dict]:
    """경부고속도로 인근 가상 휴게소."""
    positions = [
        ("천안휴게소", 36.8065, 127.1495),
        ("청주휴게소", 36.5970, 127.4740),
        ("대전휴게소", 36.3504, 127.3845),
    ][:count]
    return [{"name": n, "lat": la, "lon": lo, "type": "rest_stop"} for n, la, lo in positions]


# ── haversine ────────────────────────────────────────────────────────────────

class TestHaversine:
    def test_same_point_is_zero(self):
        assert haversine_m(37.5, 127.0, 37.5, 127.0) == 0.0

    def test_known_distance(self):
        # 서울(37.5665, 126.9780) ↔ 수원(37.2636, 127.0286) ≈ 34 km
        dist = haversine_m(37.5665, 126.9780, 37.2636, 127.0286)
        assert 30_000 < dist < 40_000, f"예상 30~40 km, 실제 {dist/1000:.1f} km"

    def test_symmetry(self):
        a = haversine_m(37.5, 127.0, 36.5, 128.0)
        b = haversine_m(36.5, 128.0, 37.5, 127.0)
        assert math.isclose(a, b, rel_tol=1e-9)

    def test_sec_positive(self):
        secs = haversine_sec(37.5665, 126.9780, 35.1796, 129.0756)  # 서울↔부산
        assert secs > 0


# ── solve_tsp ────────────────────────────────────────────────────────────────

class TestSolveTsp:
    def test_direct_route(self):
        """경유지 없음 → [0, 1]"""
        nodes = [
            _node("서울", 37.5665, 126.9780, "origin"),
            _node("부산", 35.1796, 129.0756, "destination"),
        ]
        matrix = _matrix_from_positions(nodes)
        order = solve_tsp(matrix, start=0, end=1)
        assert order[0] == 0
        assert order[-1] == 1

    def test_three_nodes_ends_at_destination(self):
        """경유지 1개: 순서는 어떻든 출발=0, 도착=마지막 노드."""
        nodes = [
            _node("서울", 37.5665, 126.9780, "origin"),
            _node("대전", 36.3504, 127.3845, "waypoint"),
            _node("부산", 35.1796, 129.0756, "destination"),
        ]
        matrix = _matrix_from_positions(nodes)
        order = solve_tsp(matrix, start=0, end=2)
        assert order[0] == 0
        assert order[-1] == 2

    def test_optimal_waypoint_ordering(self):
        """서울→광주→대구→부산 vs 서울→대구→광주→부산
        지리적으로 서울→대전→대구→부산이 서울→광주→대구→부산보다 짧아야 합니다.
        """
        nodes = [
            _node("서울", 37.5665, 126.9780, "origin"),
            _node("대전", 36.3504, 127.3845, "waypoint"),
            _node("광주", 35.1595, 126.8526, "waypoint"),
            _node("부산", 35.1796, 129.0756, "destination"),
        ]
        matrix = _matrix_from_positions(nodes)
        order = solve_tsp(matrix, start=0, end=3)

        # 대전(1)이 광주(2)보다 먼저 방문되어야 더 짧은 경로
        assert order.index(1) < order.index(2), (
            f"대전이 광주보다 나중에 방문됨: order={order}"
        )

    def test_single_node_fallback(self):
        """노드 1개 — 행렬 크기 1 예외 없이 처리.
        OR-Tools는 start=end=0 일 때 [0, 0]을 반환하므로 길이 >= 1, 첫/마지막=0 검증.
        """
        matrix = [[0]]
        order = solve_tsp(matrix, start=0, end=0)
        assert len(order) >= 1
        assert order[0] == 0
        assert order[-1] == 0

    def test_all_nodes_visited(self):
        """모든 필수 노드가 결과에 포함되어야 합니다."""
        nodes = [
            _node("A", 37.0, 127.0, "origin"),
            _node("B", 36.5, 127.5, "waypoint"),
            _node("C", 36.0, 128.0, "waypoint"),
            _node("D", 35.5, 128.5, "destination"),
        ]
        matrix = _matrix_from_positions(nodes)
        order = solve_tsp(matrix, start=0, end=3)
        assert sorted(order) == [0, 1, 2, 3]


# ── insert_rest_stops ────────────────────────────────────────────────────────

class TestInsertRestStops:
    def _short_matrix(self, nodes: list[dict]) -> list[list[int]]:
        return _matrix_from_positions(nodes)

    def test_no_rest_needed_short_route(self):
        """30분짜리 경로 → 휴게소 삽입 없어야 합니다."""
        nodes = [
            _node("서울", 37.5665, 126.9780, "origin"),
            _node("수원", 37.2636, 127.0286, "destination"),
        ]
        matrix = self._short_matrix(nodes)
        order = [0, 1]
        result = insert_rest_stops(nodes, matrix, order, _make_rest_stops())
        assert all(n["type"] != "rest_stop" for n in result)

    def test_rest_inserted_after_2h_drive(self):
        """서울→부산 직통 약 4.5시간 → 중간에 휴게소 최소 1개 삽입."""
        nodes = [
            _node("서울", 37.5665, 126.9780, "origin"),
            _node("부산", 35.1796, 129.0756, "destination"),
        ]
        matrix = self._short_matrix(nodes)
        # 부산까지 2시간 초과이므로 삽입 필요
        # 인위적으로 큰 시간 행렬로 강제
        big_matrix = [[0, MAX_DRIVE_SEC + 1], [MAX_DRIVE_SEC + 1, 0]]
        result = insert_rest_stops(nodes, big_matrix, [0, 1], _make_rest_stops())
        rest_nodes = [n for n in result if n["type"] == "rest_stop"]
        assert len(rest_nodes) >= 1

    def test_rest_node_has_min_rest_minutes(self):
        """삽입된 휴게 노드의 min_rest_minutes == 15."""
        nodes = [
            _node("A", 37.0, 127.0, "origin"),
            _node("B", 35.0, 129.0, "destination"),
        ]
        big_matrix = [[0, MAX_DRIVE_SEC + 3600], [MAX_DRIVE_SEC + 3600, 0]]
        result = insert_rest_stops(nodes, big_matrix, [0, 1], _make_rest_stops())
        for n in result:
            if n["type"] == "rest_stop":
                assert n["min_rest_minutes"] == MIN_REST_SEC // 60

    def test_nearest_rest_stop_selected(self):
        """우회 비용(prev→r→curr 합계)이 최소인 휴게소가 선택되는지 검증합니다."""
        origin = _node("서울", 37.5665, 126.9780, "origin")
        dest = _node("부산", 35.1796, 129.0756, "destination")
        nodes = [origin, dest]
        big_matrix = [[0, MAX_DRIVE_SEC + 1], [MAX_DRIVE_SEC + 1, 0]]

        # 천안(서울에서 ~100km)과 대구(서울에서 ~280km)
        # 서울→부산 경로 위에서:
        #   천안 경유: 서울→천안 + 천안→부산 ≈ 450km (경로에서 벗어남)
        #   대구 경유: 서울→대구 + 대구→부산 ≈ 370km (경로 위에 위치)
        # → 우회 비용 최소는 대구
        rest_stops = [
            {"name": "천안휴게소", "lat": 36.8065, "lon": 127.1495},
            {"name": "대구휴게소", "lat": 35.8714, "lon": 128.6014},
        ]
        result = insert_rest_stops(nodes, big_matrix, [0, 1], rest_stops)
        inserted = [n for n in result if n.get("type") == "rest_stop"]
        assert inserted[0]["name"] == "대구휴게소"

    def test_empty_rest_stops_no_insertion(self):
        """휴게소 목록이 빈 경우 삽입 없이 원본 반환."""
        nodes = [
            _node("A", 37.0, 127.0, "origin"),
            _node("B", 35.0, 129.0, "destination"),
        ]
        big_matrix = [[0, MAX_DRIVE_SEC + 1], [MAX_DRIVE_SEC + 1, 0]]
        result = insert_rest_stops(nodes, big_matrix, [0, 1], [])
        assert result == nodes

    def test_multiple_rest_insertions(self):
        """8시간 이동 → 최소 2회 휴게 삽입."""
        #  세그먼트 1: 3시간 → 삽입
        #  세그먼트 2: 3시간 → 삽입
        #  세그먼트 3: 2시간 → 삽입 없음
        nodes = [
            _node("A", 37.5, 127.0, "origin"),
            _node("B", 36.5, 127.5, "waypoint"),
            _node("C", 36.0, 128.0, "waypoint"),
            _node("D", 35.5, 128.5, "destination"),
        ]
        seg = MAX_DRIVE_SEC + 1  # 각 구간 2시간 초과
        matrix = [
            [0,   seg, seg, seg],
            [seg, 0,   seg, seg],
            [seg, seg, 0,   seg],
            [seg, seg, seg, 0  ],
        ]
        result = insert_rest_stops(nodes, matrix, [0, 1, 2, 3], _make_rest_stops())
        rest_count = sum(1 for n in result if n["type"] == "rest_stop")
        assert rest_count >= 2, f"예상 2개 이상 휴게 삽입, 실제 {rest_count}개"


# ── 통합: solve_tsp + insert_rest_stops ──────────────────────────────────────

class TestVrpIntegration:
    def test_full_pipeline_seoul_to_busan(self):
        """서울→부산 직통 전체 파이프라인 연기 없이 통과."""
        nodes = [
            _node("서울", 37.5665, 126.9780, "origin"),
            _node("부산", 35.1796, 129.0756, "destination"),
        ]
        matrix = _matrix_from_positions(nodes)
        order = solve_tsp(matrix, start=0, end=1)
        final = insert_rest_stops(
            [nodes[i] for i in order], matrix, order, _make_rest_stops()
        )

        assert final[0]["name"] == "서울"
        assert final[-1]["name"] == "부산"
        # 서울↔부산은 약 4.5시간 → 휴게소 최소 1개
        rest = [n for n in final if n["type"] == "rest_stop"]
        assert len(rest) >= 1

    def test_waypoint_order_optimized(self):
        """
        서울(출발) → [대구, 대전] → 부산(도착).
        지리적으로 대전이 대구보다 서울에 가까우므로 대전이 먼저 방문되어야 합니다.
        """
        nodes = [
            _node("서울", 37.5665, 126.9780, "origin"),
            _node("대구", 35.8714, 128.6014, "waypoint"),   # 인덱스 1
            _node("대전", 36.3504, 127.3845, "waypoint"),   # 인덱스 2
            _node("부산", 35.1796, 129.0756, "destination"),
        ]
        matrix = _matrix_from_positions(nodes)
        order = solve_tsp(matrix, start=0, end=3)
        # 대전(2)이 대구(1)보다 먼저 방문
        assert order.index(2) < order.index(1), (
            f"대전이 대구보다 늦게 방문됨: order={order}"
        )
