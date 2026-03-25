-- routeon DB 초기 테이블 생성
-- 사용법: docker exec -i routeon-db psql -U routeon -d routeon < backend/seeds/init_tables.sql

DO $$ BEGIN
    CREATE TYPE userrole AS ENUM ('admin', 'driver');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE reststoptype AS ENUM ('highway_rest', 'drowsy_shelter', 'depot');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE tripstatus AS ENUM ('scheduled', 'in_progress', 'completed', 'cancelled');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE drivingstate AS ENUM ('driving', 'resting', 'traffic_stop', 'unknown');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE TABLE IF NOT EXISTS users (
    id          SERIAL PRIMARY KEY,
    email       VARCHAR(255) UNIQUE NOT NULL,
    hashed_password VARCHAR(255) NOT NULL,
    role        userrole NOT NULL DEFAULT 'driver',
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS drivers (
    id          SERIAL PRIMARY KEY,
    user_id     INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(50) NOT NULL,
    license_no  VARCHAR(30),
    phone       VARCHAR(20),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS vehicles (
    id           SERIAL PRIMARY KEY,
    plate_number VARCHAR(20) UNIQUE NOT NULL,
    height_m     FLOAT,
    weight_kg    FLOAT,
    length_cm    FLOAT,
    width_cm     FLOAT,
    is_active    BOOLEAN NOT NULL DEFAULT TRUE,
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS trips (
    id               SERIAL PRIMARY KEY,
    driver_id        INTEGER REFERENCES drivers(id),
    vehicle_id       INTEGER REFERENCES vehicles(id),
    status           tripstatus NOT NULL DEFAULT 'scheduled',
    optimized_route  JSONB,
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS location_logs (
    id            SERIAL PRIMARY KEY,
    trip_id       INTEGER NOT NULL REFERENCES trips(id),
    latitude      FLOAT NOT NULL,
    longitude     FLOAT NOT NULL,
    speed_kmh     FLOAT,
    state         drivingstate NOT NULL DEFAULT 'unknown',
    recorded_at   TIMESTAMPTZ DEFAULT NOW(),
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    updated_at    TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rest_stops (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    type        reststoptype NOT NULL,
    latitude    FLOAT NOT NULL,
    longitude   FLOAT NOT NULL,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW()
);

SELECT 'tables created' AS result;
