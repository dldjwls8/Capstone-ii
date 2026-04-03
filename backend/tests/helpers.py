"""
테스트 공용 상수 · 유틸리티

두 테스트 파일 공통으로 사용:
  - test_kakao_long.py  (장거리 배송)
  - test_kakao_local.py (지역 배송)
"""
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.services.rest_stop_inserter import RouteNode, REST_PLAN_SEC

# ── 테스트 노드 좌표 ────────────────────────────────────────────────────────

# 장거리: 서울 강남역 → 수원 → 천안 → 대전
LONG_NODES: list[dict] = [
    {"name": "서울 강남역",   "lat": 37.4979, "lon": 127.0276},
    {"name": "수원 영통구청", "lat": 37.2525, "lon": 127.0490},
    {"name": "천안 터미널",   "lat": 36.8151, "lon": 127.1139},
    {"name": "대전 유성구청", "lat": 36.3624, "lon": 127.3565},
]

# 지역 배송: 서울 시내 4개 거점 (반경 ~15km 이내)
LOCAL_NODES: list[dict] = [
    {"name": "강남역",   "lat": 37.4979, "lon": 127.0276},
    {"name": "잠실역",   "lat": 37.5133, "lon": 127.1000},
    {"name": "홍대입구", "lat": 37.5573, "lon": 126.9245},
    {"name": "여의도역", "lat": 37.5215, "lon": 126.9244},
]

# ── 졸음쉼터 CSV 로드 ────────────────────────────────────────────────────────

_CSV_PATH: Path = (
    Path(__file__).parent.parent.parent / "자료" / "한국도로공사_졸음쉼터_20260225.csv"
)


def _load_rest_candidates() -> list[dict]:
    if not _CSV_PATH.exists():
        return []
    candidates: list[dict] = []
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

# ── 지역 배송용 도심 휴게 후보 ───────────────────────────────────────────────
# 고속도로 졸음쉼터는 지역 배송과 무관 → 도심 주요 주차·휴게 거점 사용
# (RestStop.type = 'custom', scope = 'public' 에 해당)
LOCAL_REST_CANDIDATES: list[dict] = [
    {"name": "강남구청 공영주차장",  "latitude": 37.5172, "longitude": 127.0473, "is_active": True},
    {"name": "송파구청 인근 휴게소", "latitude": 37.5148, "longitude": 127.1059, "is_active": True},
    {"name": "마포구청 공영주차장",  "latitude": 37.5663, "longitude": 126.9014, "is_active": True},
    {"name": "영등포구청 주차장",    "latitude": 37.5260, "longitude": 126.8963, "is_active": True},
    {"name": "성동구청 주차장",      "latitude": 37.5635, "longitude": 127.0365, "is_active": True},
]

# ── 출력 헬퍼 ────────────────────────────────────────────────────────────────

def fmt_time(sec: int) -> str:
    h, m = divmod(sec // 60, 60)
    return f"{h}시간 {m:02d}분" if h else f"{m}분"


def print_matrix(label: str, nodes: list[dict], time_matrix, dist_matrix) -> None:
    """NxN 시간·거리 행렬을 표 형태로 출력합니다."""
    n = len(nodes)
    names = [nd["name"] for nd in nodes]
    col_w = 20
    print(f"\n{'='*65}")
    print(f"  {label} — 구간별 시간·거리 행렬 ({n}×{n})")
    print(f"{'='*65}")
    header = f"{'출발 \\ 도착':<{col_w}}" + "".join(f"{nm:<{col_w}}" for nm in names)
    print(header)
    print("-" * len(header))
    for i, from_name in enumerate(names):
        row_str = f"{from_name:<{col_w}}"
        for j in range(n):
            if i == j:
                row_str += f"{'—':<{col_w}}"
            else:
                km = dist_matrix[i][j] / 1000
                t  = fmt_time(time_matrix[i][j])
                cell = f"{km:.1f}km/{t}"
                row_str += f"{cell:<{col_w}}"
        print(row_str)


def print_rest_candidates_info() -> None:
    """졸음쉼터 CSV 로드 결과를 출력합니다."""
    print(f"\n{'='*65}")
    if not _CSV_PATH.exists():
        print(f"  [경고] CSV 파일 없음: {_CSV_PATH}")
    else:
        print(f"  졸음쉼터 CSV — {_CSV_PATH.name}")
        print(f"  후보 {len(REST_CANDIDATES)}개 로드됨")
    print(f"{'='*65}")


def collect_rest_in_segment(result: list[RouteNode]) -> dict[int, RouteNode]:
    """result 목록에서 rest_stop이 몇 번째 구간에 삽입됐는지 매핑합니다.
    구간 인덱스 = 앞뒤로 rest_stop이 아닌 노드 사이의 순번.
    """
    seg_idx = 0
    mapping: dict[int, RouteNode] = {}
    for node in result:
        if node.type == "rest_stop":
            mapping[seg_idx - 1] = node
        else:
            seg_idx += 1
    return mapping


def print_route_with_cumulative(
    nodes: list[dict],
    full_order: list[int],
    time_matrix: list[list[int]],
    dist_matrix: list[list[int]],
    rest_in_segment: dict[int, RouteNode],
    label: str = "운행 경로",
) -> None:
    """구간별 누적 운전시간과 삽입된 휴게소를 출력합니다."""
    print(f"\n{'='*65}")
    print(f"  {label} — 구간별 누적 운전시간 및 휴게소")
    print(f"  ※ 경유지(배송지) 도착·출발은 연속 운전으로 간주")
    print(f"{'='*65}")

    cum_sec   = 0
    total_sec = 0
    total_m   = 0
    dest_idx  = len(nodes) - 1

    for i in range(len(full_order) - 1):
        a, b = full_order[i], full_order[i + 1]
        seg_sec = time_matrix[a][b]
        seg_m   = dist_matrix[a][b]
        total_sec += seg_sec
        total_m   += seg_m
        cum_sec   += seg_sec

        from_tag = "[출발]" if i == 0 else "[경유]"
        to_tag   = "[목적]" if b == dest_idx else "[경유]"
        print(f"\n  {i+1}구간  {from_tag} {nodes[a]['name']}"
              f"  →  {to_tag} {nodes[b]['name']}")
        print(f"       거리/시간  : {seg_m/1000:.1f}km,  {fmt_time(seg_sec)}")
        print(f"       누적 운전  : {fmt_time(cum_sec)}"
              f"  (= {cum_sec}초 / 임계 {REST_PLAN_SEC}초)")

        if i in rest_in_segment:
            rest = rest_in_segment[i]
            print(f"       ┌─ ⚠ 누적 {fmt_time(cum_sec)} — 임계값({fmt_time(REST_PLAN_SEC)}) 초과")
            print(f"       ★ 휴게소 삽입: {rest.name}  ({rest.lat:.4f}, {rest.lon:.4f})")
            print(f"       └─ 최소 {rest.min_rest_minutes}분 휴식 후 출발  → 누적 운전 리셋")
            cum_sec = 0
        elif cum_sec > REST_PLAN_SEC:
            print(f"       ⚠ 누적 운전 임계값 초과 — 휴게소 후보 없음")

    print(f"\n{'─'*65}")
    print(f"  총 거리     : {total_m/1000:.1f}km")
    print(f"  총 순수운전 : {fmt_time(total_sec)}")
    print(f"  휴게소      : {len(rest_in_segment)}곳 삽입  (후보 {len(REST_CANDIDATES)}개 중)")


def skip_if_no_key() -> None:
    """KAKAO_API_KEY 없으면 테스트를 스킵합니다."""
    from app.core.config import settings
    if not settings.KAKAO_API_KEY:
        pytest.skip("KAKAO_API_KEY가 설정되어 있지 않습니다.")
