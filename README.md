 # RouteOn (루트온)

화물차 운행 경로를 최적화하면서, 법정 휴게 규정을 자동 반영하는 FastAPI 기반 백엔드입니다.

핵심 파이프라인:
- Kakao Mobility API로 구간 시간/거리 행렬 생성
- OR-Tools TSP로 방문 순서 최적화
- 누적 운전 시간 기반 휴게소 자동 삽입

## 1. 프로젝트 개요

- 목적: 경유지 순서 최적화 + 법정 휴게 규정 자동 반영
- 백엔드: FastAPI + SQLAlchemy 2.x async + PostgreSQL(asyncpg)
- 라우팅 API: Kakao Mobility API
- 최적화 엔진: OR-Tools
- 데이터: 휴게소/졸음쉼터 시드 + 운행/차량/기사/위치 로그 CRUD

## 2. 법정 상수 (변경 금지)

아래 상수는 backend/app/services/rest_stop_inserter.py 기준입니다.

```python
REST_PLAN_SEC        = 6_000   # 1시간 40분: 선제적 휴게 삽입 임계값
MAX_DRIVE_SEC        = 7_200   # 2시간: 법정 최대 연속 운전
MIN_REST_MIN         = 15      # 법정 최소 휴식(분)
EMERGENCY_EXTEND_SEC = 3_600   # 긴급 예외 연장(초): 최대 3시간 연속 운전
EMERGENCY_REST_MIN   = 30      # 긴급 예외 시 최소 휴식(분)
```

## 3. 현재 구현 범위

구현 완료:
- 단일 차량 경로 최적화: POST /optimize/
- 운행 중 재최적화: POST /optimize/replan
- 운행/차량/기사/휴게소/위치 로그 CRUD
- 법정 휴게소 자동 삽입
- local/long_distance 라우팅 모드
- departure_time 기반 미래 교통 반영

미구현:
- 다수 차량 VRP 배차: POST /optimize/dispatch (501 Not Implemented)

## 4. 디렉토리 구조

```text
Capstone-ii/
├─ README.md
├─ SCHEMA.md
├─ 자료/
│  └─ 한국도로공사_졸음쉼터_20260225.csv
├─ backend/
│  ├─ requirements.txt
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ api/
│  │  ├─ core/
│  │  ├─ models/
│  │  ├─ schemas/
│  │  └─ services/
│  ├─ seeds/
│  └─ tests/
└─ Kakao_navi_api_EX/
```

## 5. 실행 방법 (로컬 개발)

현재 저장소에는 docker compose 파일이 포함되어 있지 않아, 기본 실행 경로는 로컬 실행입니다.

사전 요구사항:
- Python 3.11+
- PostgreSQL

```bash
cd backend

# 1) 가상환경
python -m venv .venv

# Windows PowerShell
.venv\Scripts\Activate.ps1

# 2) 의존성 설치
pip install -r requirements.txt

# 3) 환경 변수
copy .env.example .env

# 4) 서버 실행
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

접속:
- API: http://localhost:8000
- Swagger: http://localhost:8000/docs
- Health: http://localhost:8000/health

## 6. 환경 변수

backend/.env

```env
DATABASE_URL=postgresql+asyncpg://routeon:routeon@localhost:5432/routeon
KAKAO_API_KEY=YOUR_KAKAO_REST_API_KEY
SECRET_KEY=CHANGE_ME_IN_PRODUCTION
DEBUG=false
```

주의:
- KAKAO_API_KEY가 없으면 Kakao 연동 테스트는 skip 됩니다.
- SECRET_KEY 기본값은 운영 배포 전 반드시 변경하세요.

## 7. 데이터베이스/시드

앱 시작 시 SQLAlchemy create_all로 테이블 생성이 수행됩니다.

휴게소/졸음쉼터 시드:

```bash
cd backend
python seeds/seed_rest_stops.py
```

특이사항:
- CSV 인코딩: euc-kr
- 시드 스크립트는 drowsy_shelter 데이터를 rest_stops에 적재

## 8. API 요약

최적화:
- POST /optimize/
- POST /optimize/replan
- POST /optimize/dispatch (501)

운행:
- GET /trips/
- POST /trips/
- GET /trips/{trip_id}
- PATCH /trips/{trip_id}/status

차량:
- GET /vehicles/
- POST /vehicles/
- PATCH /vehicles/{vehicle_id}

운전자:
- GET /drivers/
- POST /drivers/

휴게소:
- GET /rest-stops/
- POST /rest-stops/
- DELETE /rest-stops/{stop_id}

위치 로그:
- POST /location-logs/
- GET /location-logs/{trip_id}

## 9. 최적화 동작 상세

### 9.1 optimize 파이프라인

1. trip_id로 Trip 로드
2. 노드 구성: origin + waypoints + extra_stops + destination
3. 시간/거리 행렬 생성
4. OR-Tools TSP로 순서 최적화 (출발지 고정, 목적지 고정)
5. 누적 운전 시간 기준 휴게소 삽입
6. optimized_route 저장 후 응답

### 9.2 route_mode

- local:
  - departure_time이 없으면 다중 목적지 API를 행 단위로 호출 (N회)
- long_distance:
  - 실시간 directions 개별 호출 (N^2 - N회)
- departure_time 존재 시:
  - 두 모드 모두 future directions 개별 호출 (N^2 - N회)

### 9.3 차량 제원 우선순위

최적화 요청값이 trip 저장값보다 우선합니다.

- optimize 요청 vehicle_* 존재 -> 요청값 사용
- 없으면 trip.vehicle_* 사용

## 10. 주요 요청 예시

### 10.1 Trip 생성

```json
{
  "driver_id": 1,
  "vehicle_id": 1,
  "dest_name": "부산 물류단지",
  "dest_lat": 35.1796,
  "dest_lon": 129.0756,
  "waypoints": [
    {"name": "대전 창고", "lat": 36.3504, "lon": 127.3845}
  ],
  "vehicle_height_m": 4.0,
  "vehicle_weight_kg": 25000,
  "departure_time": "2026-03-26T08:00:00+09:00"
}
```

### 10.2 Optimize

```json
{
  "trip_id": 1,
  "origin_name": "서울 자택",
  "origin_lat": 37.5665,
  "origin_lon": 126.978,
  "initial_drive_sec": 0,
  "route_mode": "long_distance",
  "extra_stops": [
    {
      "stop_type": "rest_preferred",
      "name": "칠원휴게소",
      "lat": 35.2345,
      "lon": 128.4567
    }
  ]
}
```

extra_stops.stop_type:
- waypoint: 경유지 추가
- destination: 목적지 교체(기존 목적지는 경유지로 이동)
- rest_preferred: 휴게 후보 우선순위 상향

### 10.3 Replan

```json
{
  "trip_id": 1,
  "current_lat": 36.1234,
  "current_lon": 127.4567,
  "current_name": "현재위치",
  "current_drive_sec": 5400,
  "remaining_waypoints": [
    {"name": "대구 창고", "lat": 35.8714, "lon": 128.6014}
  ],
  "dest_name": "부산 물류단지",
  "dest_lat": 35.1796,
  "dest_lon": 129.0756,
  "is_emergency": true,
  "route_mode": "long_distance"
}
```

## 11. 테스트

```bash
cd backend
pytest -q
```

테스트 파일:
- tests/test_route_pipeline.py: TSP + 휴게소 삽입 파이프라인
- tests/test_kakao_local.py: 지역 배송 모드 통합
- tests/test_kakao_long.py: 장거리 모드 통합

참고:
- Kakao 통합 테스트는 실제 API 키와 네트워크 상태에 영향을 받습니다.

## 12. 운영/개발 주의사항

- Kakao API 키 누락/한도 초과(429) 시 일부 경로 조회 실패 가능
- Kakao 좌표 파라미터는 lon,lat 순서
- API 미반환 구간은 큰 페널티 시간으로 처리되어 TSP에서 사실상 배제
- DB 스키마 변경 시 SCHEMA.md, seeds/init_tables.sql, models 동기화 필요

## 13. 참고 문서

- DB 스키마: SCHEMA.md
- DDL: backend/seeds/init_tables.sql
- Kakao API 참고 샘플: Kakao_navi_api_EX/
