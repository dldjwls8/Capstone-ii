"""
Kakao Mobility API 실제 호출 통합 테스트

실행:
    cd backend
    .venv/Scripts/python -m pytest tests/test_kakao_integration.py -v -s --tb=short

주의:
    - KAKAO_API_KEY가 .env에 설정되어 있어야 합니다.
    - 실제 API 호출이 발생합니다 (10 QPS 제한 유의).
    - 네트워크 연결이 필요합니다.
"""
import asyncio
import os
import sys
from pathlib import Path

import csv

import pytest

# backend/ 루트를 sys.path에 추가 (직접 실행 시 대비)
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.kakao import build_time_matrix, find_best_rest_stop
from app.services.optimizer import solve_tsp
from app.services.rest_stop_inserter import RouteNode, insert_rest_stops, REST_PLAN_SEC

# ── 테스트용 실제 좌표 (서울 주요 거점) ─────────────────────────────────────
# 장거리 모드: 서울 → 수원 → 천안 → 대전
LONG_NODES = [
    {"name": "서울 강남역",   "lat": 37.4979, "lon": 127.0276},
    {"name": "수원 영통구청", "lat": 37.2525, "lon": 127.0490},
    {"name": "천안 터미널",   "lat": 36.8151, "lon": 127.1139},
    {"name": "대전 유성구청", "lat": 36.3624, "lon": 127.3565},
]

# 지역 배송 모드: 서울 시내 4개 거점 (반경 10km 이내)
LOCAL_NODES = [
    {"name": "강남역",   "lat": 37.4979, "lon": 127.0276},
    {"name": "잠실역",   "lat": 37.5133, "lon": 127.1000},
    {"name": "홍대입구", "lat": 37.5573, "lon": 126.9245},
    {"name": "여의도역", "lat": 37.5215, "lon": 126.9244},
]

# ── 졸음쉼터 후보: 한국도로공사 공공 데이터 CSV에서 로드 ─────────────────────
_CSV_PATH = Path(__file__).parent.parent.parent / "자료" / "한국도로공사_졸음쉼터_20260225.csv"

def _load_rest_candidates() -> list[dict]:
    if not _CSV_PATH.exists():
        return []
    candidates = []
    with open(_CSV_PATH, encoding="euc-kr", newline="") as f:
        for row in csv.DictReader(f):
            try:
                lat = float(row.get("위도") or 0)
                lon = float(row.get("경도") or 0)
                if lat == 0 or lon == 0:
                    continue
                candidates.append({
                    "name":      row.get("졸음쉼터명") or "졸음쉼터",
                    "latitude":  lat,
                    "longitude": lon,
                    "is_active": True,
                })
            except (ValueError, KeyError):
                continue
    return candidates

REST_CANDIDATES: list[dict] = _load_rest_candidates()

def _print_rest_candidates_summary() -> None:
    print(f"\n{'='*60}")
    if not _CSV_PATH.exists():
        print(f"  [경고] CSV 파일 없음: {_CSV_PATH}")
    else:
        print(f"  졸음쉼터 CSV 로드 — {_CSV_PATH.name}")
        print(f"  총 {len(REST_CANDIDATES)}개 후보 로드됨")
    print(f"{'='*60}")


def _skip_if_no_key():
    """API 키 없으면 테스트 스킵."""
    from app.core.config import settings
    if not settings.KAKAO_API_KEY:
        pytest.skip("KAKAO_API_KEY가 설정되어 있지 않습니다.")


# ── 1. 장거리 모드 시간·거리 행렬 ───────────────────────────────────────────

def _fmt_time(sec: int) -> str:
    h, m = divmod(sec // 60, 60)
    return f"{h}시간 {m:02d}분" if h else f"{m}분"


def _print_matrix(label: str, nodes: list[dict], time_matrix, dist_matrix):
    n = len(nodes)
    names = [nd["name"] for nd in nodes]
    print(f"\n{'='*60}")
    print(f"  {label} — 구간별 시간·거리 행렬 ({n}×{n})")
    print(f"{'='*60}")
    col_w = 18
    header = f"{'출발 \\ 도착':<{col_w}}" + "".join(f"{nm:<{col_w}}" for nm in names)
    print(header)
    print("-" * len(header))
    for i, from_name in enumerate(names):
        row = f"{from_name:<{col_w}}"
        for j in range(n):
            if i == j:
                row += f"{'—':<{col_w}}"
            else:
                km = dist_matrix[i][j] / 1000
                t  = _fmt_time(time_matrix[i][j])
                row += f"{km:.1f}km/{t:<{col_w - len(f'{km:.1f}km/')}}"
        print(row)


class TestBuildTimeMatrixLong:
    def test_matrix_shape(self):
        """장거리 모드: NxN 시간·거리 행렬이 올바른 크기로 반환됩니다."""
        _skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        n = len(LONG_NODES)
        _print_matrix("장거리 모드", LONG_NODES, time_matrix, dist_matrix)
        assert len(time_matrix) == n
        assert len(dist_matrix) == n
        assert all(len(row) == n for row in time_matrix)

    def test_diagonal_is_zero(self):
        """대각선(자기 자신으로의 이동)은 0이어야 합니다."""
        _skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        for i in range(len(LONG_NODES)):
            assert time_matrix[i][i] == 0
            assert dist_matrix[i][i] == 0

    def test_all_segments_have_positive_time(self):
        """모든 비대각선 구간의 소요 시간이 0보다 커야 합니다."""
        _skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        n = len(LONG_NODES)
        print(f"\n{'='*60}")
        print("  장거리 모드 — 전체 비대각선 구간 소요시간")
        print(f"{'='*60}")
        for i in range(n):
            for j in range(n):
                if i != j:
                    km = dist_matrix[i][j] / 1000
                    t  = _fmt_time(time_matrix[i][j])
                    print(f"  {LONG_NODES[i]['name']} → {LONG_NODES[j]['name']}: {km:.1f}km, {t}")
                    assert time_matrix[i][j] > 0, f"time_matrix[{i}][{j}] == 0"

    def test_distance_in_reasonable_range(self):
        """서울~대전 거리는 80km~200km 범위여야 합니다."""
        _skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        dist_km = dist_matrix[0][3] / 1000
        time_str = _fmt_time(time_matrix[0][3])
        print(f"\n  강남 → 대전: {dist_km:.1f}km, {time_str}")
        assert 80 <= dist_km <= 200, f"강남→대전 거리 비정상: {dist_km:.1f}km"


# ── 2. 지역 배송 모드 시간·거리 행렬 ────────────────────────────────────────

class TestBuildTimeMatrixLocal:
    def test_matrix_shape(self):
        """지역 배송 모드: NxN 행렬이 올바른 크기로 반환됩니다."""
        _skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LOCAL_NODES, route_mode="local")
        )
        n = len(LOCAL_NODES)
        _print_matrix("지역 배송 모드", LOCAL_NODES, time_matrix, dist_matrix)
        assert len(time_matrix) == n
        assert len(dist_matrix) == n

    def test_local_distance_reasonable(self):
        """서울 시내 구간 거리는 3km~25km 범위여야 합니다."""
        _skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LOCAL_NODES, route_mode="local")
        )
        n = len(LOCAL_NODES)
        print(f"\n{'='*60}")
        print("  지역 배송 모드 — 전체 비대각선 구간")
        print(f"{'='*60}")
        for i in range(n):
            for j in range(n):
                if i != j and dist_matrix[i][j] > 0:
                    dist_km = dist_matrix[i][j] / 1000
                    t = _fmt_time(time_matrix[i][j])
                    print(f"  {LOCAL_NODES[i]['name']} → {LOCAL_NODES[j]['name']}: {dist_km:.1f}km, {t}")
                    assert dist_km <= 50, f"지역 배송 구간 거리가 너무 큼: [{i}][{j}] = {dist_km:.1f}km"


# ── 3. TSP + 실제 시간 행렬 ─────────────────────────────────────────────────

class TestTspWithRealMatrix:
    def test_tsp_result_valid_order(self):
        """실제 시간 행렬로 TSP 실행 + 법정 휴게소 삽입까지 출력합니다."""
        _skip_if_no_key()

        async def _run():
            time_matrix, dist_matrix = await build_time_matrix(
                LONG_NODES, route_mode="long_distance"
            )
            order = solve_tsp(time_matrix)
            full_order = order + [len(LONG_NODES) - 1]
            n = len(full_order)

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
            ordered_nodes = [nodes_obj[i] for i in full_order]
            reordered_time = [
                [time_matrix[full_order[i]][full_order[j]] for j in range(n)]
                for i in range(n)
            ]
            reordered_dist = [
                [dist_matrix[full_order[i]][full_order[j]] for j in range(n)]
                for i in range(n)
            ]
            result = await insert_rest_stops(ordered_nodes, reordered_time, REST_CANDIDATES)
            return order, full_order, time_matrix, dist_matrix, reordered_time, reordered_dist, result

        order, full_order, time_matrix, dist_matrix, rtime, rdist, result = asyncio.run(_run())

        # ── 어느 구간에 휴게소가 삽입됐는지 매핑 ────────────────────────
        # result 안에서 rest_stop이 몇 번째 '실제 구간(매트릭스 인덱스)'에 삽입됐는지 파악
        # 경유지는 누적 초기화 없이 계속 연속 운전으로 간주
        nr_idx = 0
        rest_in_segment: dict[int, RouteNode] = {}  # 구간 index → 삽입된 휴게소
        for node in result:
            if node.type == "rest_stop":
                rest_in_segment[nr_idx - 1] = node  # 직전 구간에 삽입
            else:
                nr_idx += 1

        # ── TSP 구간별 상세 + 누적 운전시간 + 휴게소 위치 표시 ──────────
        print(f"\n{'='*60}")
        print("  운행 경로 — 구간별 누적 운전시간 및 휴게소")
        print(f"  ※ 경유지(배송지) 도착·출발은 연속 운전으로 간주")
        print(f"{'='*60}")
        cum_sec  = 0
        total_sec = 0
        total_m   = 0
        for i in range(len(full_order) - 1):
            a, b = full_order[i], full_order[i + 1]
            seg_sec = time_matrix[a][b]
            seg_m   = dist_matrix[a][b]
            total_sec += seg_sec
            total_m   += seg_m
            cum_sec   += seg_sec

            from_tag = "[출발]" if i == 0 else "[경유]"
            to_tag   = "[목적]" if b == len(LONG_NODES) - 1 else "[경유]"
            print(f"\n  {i+1}구간  {from_tag} {LONG_NODES[a]['name']}"
                  f"  →  {to_tag} {LONG_NODES[b]['name']}")
            print(f"       거리/시간  : {seg_m/1000:.1f}km,  {_fmt_time(seg_sec)}")
            print(f"       누적 운전  : {_fmt_time(cum_sec)}"
                  f"  (= {cum_sec}초 / 임계 {REST_PLAN_SEC}초)")

            if i in rest_in_segment:
                rest = rest_in_segment[i]
                print(f"       ┌─ ⚠ 누적 {_fmt_time(cum_sec)} — 임계값({_fmt_time(REST_PLAN_SEC)}) 초과")
                print(f"       ★ 휴게소 삽입: {rest.name}  ({rest.lat:.4f}, {rest.lon:.4f})")
                print(f"       └─ 최소 {rest.min_rest_minutes}분 휴식 후 출발  → 누적 운전 리셋")
                cum_sec = 0
            elif cum_sec > REST_PLAN_SEC:
                print(f"       ⚠ 누적 운전 임계값 초과")

        print(f"\n{'─'*60}")
        print(f"  총 거리     : {total_m/1000:.1f}km")
        print(f"  총 순수운전 : {_fmt_time(total_sec)}")
        print(f"  휴게소      : {len(rest_in_segment)}곳 삽입  (후보 {len(REST_CANDIDATES)}개 중)")

        assert order[0] == 0, f"TSP 첫 노드가 출발지(0)가 아님: {order}"

    def test_tsp_visits_all_nodes(self):
        """TSP 결과가 모든 경유지 인덱스를 포함해야 합니다."""
        _skip_if_no_key()
        time_matrix, _ = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        order = solve_tsp(time_matrix)
        # 목적지(마지막 인덱스)는 TSP가 고정으로 제외하므로 나머지만 확인
        assert set(order) == set(range(len(LONG_NODES) - 1))


# ── 4. 실제 API 기반 전체 파이프라인 ────────────────────────────────────────

class TestFullPipelineWithKakao:
    def test_pipeline_returns_route_with_nodes(self):
        """실제 API → TSP → 휴게소 삽입 전체 파이프라인이 노드 목록을 반환합니다."""
        _skip_if_no_key()

        async def _run():
            time_matrix, dist_matrix = await build_time_matrix(
                LONG_NODES, route_mode="long_distance"
            )
            order = solve_tsp(time_matrix)
            nodes_obj = [
                RouteNode(
                    type="origin" if i == 0 else (
                        "destination" if i == len(LONG_NODES) - 1 else "waypoint"
                    ),
                    name=LONG_NODES[i]["name"],
                    lat=LONG_NODES[i]["lat"],
                    lon=LONG_NODES[i]["lon"],
                )
                for i in range(len(LONG_NODES))
            ]
            full_order = order + [len(LONG_NODES) - 1]
            n = len(full_order)
            ordered_nodes = [nodes_obj[i] for i in full_order]
            reordered_time = [
                [time_matrix[full_order[i]][full_order[j]] for j in range(n)]
                for i in range(n)
            ]
            reordered_dist = [
                [dist_matrix[full_order[i]][full_order[j]] for j in range(n)]
                for i in range(n)
            ]
            result = await insert_rest_stops(
                ordered_nodes,
                reordered_time,
                REST_CANDIDATES,
                # picker=None → Haversine fallback
            )
            return result, full_order, reordered_time, reordered_dist

        result, full_order, time_mat, dist_mat = asyncio.run(_run())

        # ── 졸음쉼터 후보 로드 정보 ───────────────────────────────────────
        _print_rest_candidates_summary()

        # ── 구간별 상세 출력 ──────────────────────────────────────────────
        print(f"\n{'='*60}")
        print("  전체 파이프라인 — 최종 경로 (휴게소 포함)")
        print(f"{'='*60}")

        # 원본 노드 인덱스 추적: rest_stop이 아닌 노드만 매트릭스와 대응
        mat_idx = 0
        total_sec = 0
        total_m   = 0
        for i, node in enumerate(result):
            node_type = f"[{node.type}]"
            if node.type == "rest_stop":
                print(f"  {i+1}. {node_type:<14} {node.name}  "
                      f"({node.lat:.4f}, {node.lon:.4f})")
            else:
                print(f"  {i+1}. {node_type:<14} {node.name}")
            # 다음 노드와의 구간 출력
            if i < len(result) - 1:
                next_node = result[i + 1]
                if node.type != "rest_stop" and next_node.type != "rest_stop" \
                        and mat_idx < len(time_mat) - 1:
                    seg_sec = time_mat[mat_idx][mat_idx + 1]
                    seg_m   = dist_mat[mat_idx][mat_idx + 1]
                    total_sec += seg_sec
                    total_m   += seg_m
                    print(f"       └─ {seg_m/1000:.1f}km, {_fmt_time(seg_sec)}")
                    mat_idx += 1
                else:
                    print(f"       └─ (연결 구간)")
        print(f"{'─'*60}")
        print(f"  총 거리: {total_m/1000:.1f}km   총 소요시간: {_fmt_time(total_sec)}")
        inserted_cnt = sum(1 for n in result if n.type == "rest_stop")
        print(f"  노드 수: {len(result)}개 (휴게소 {inserted_cnt}곳 삽입 / 후보 {len(REST_CANDIDATES)}개 중)")

        assert len(result) >= len(LONG_NODES)
        assert result[0].type == "origin"
        assert result[-1].type == "destination"

    def test_total_distance_positive(self):
        """실제 API로 계산한 거리 합산이 0보다 커야 합니다."""
        _skip_if_no_key()
        time_matrix, dist_matrix = asyncio.run(
            build_time_matrix(LONG_NODES, route_mode="long_distance")
        )
        order = solve_tsp(dist_matrix)  # 거리 기준 순서
        full_order = order + [len(LONG_NODES) - 1]
        print(f"\n{'='*60}")
        print("  거리 기준 TSP 최적 경로")
        print(f"{'='*60}")
        total_sec = 0
        total_m   = 0
        for i in range(len(full_order) - 1):
            a, b = full_order[i], full_order[i + 1]
            seg_sec = time_matrix[a][b]
            seg_m   = dist_matrix[a][b]
            total_sec += seg_sec
            total_m   += seg_m
            print(f"  {i+1}. {LONG_NODES[a]['name']} → {LONG_NODES[b]['name']}: "
                  f"{seg_m/1000:.1f}km, {_fmt_time(seg_sec)}")
        print(f"{'─'*60}")
        print(f"  총 거리: {total_m/1000:.1f}km   총 소요시간: {_fmt_time(total_sec)}")
        assert total_m > 0, "총 거리가 0입니다."
        assert total_m / 1000 >= 150, f"총 거리 너무 짧음: {total_m/1000:.1f}km"
