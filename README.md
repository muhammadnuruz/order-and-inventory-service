# Order & Inventory Reservation Service

Backend for a mini marketplace: products, multi-item orders with stock reservation,
idempotent order creation, cancellation, automatic expiry of unpaid orders and
real-time stock updates over WebSocket.

**Stack:** Python 3.12 · FastAPI · PostgreSQL 16 (asyncpg, hand-written SQL, no ORM) ·
Redis 7 (cache, JWT denylist, pub/sub, Celery broker) · Celery + beat · Alembic ·
Gunicorn/Uvicorn · Nginx · Docker Compose · pytest + testcontainers

---

## Quick start

```bash
docker compose up --build
```

- API: http://localhost:8080 (Swagger UI: http://localhost:8080/docs)
- No `.env` is required: every setting has a default in `docker-compose.yaml`; a `.env`
  file (see `.env.example`) only overrides them.
- Migrations run automatically when the `api` container starts.

Check the concurrency guarantee against the running stack:

```bash
python scripts/load_test.py --requests 50 --stock 10
# product 1: {201: 10, 409: 40}, stock left: 0
```

## API

All endpoints are under `/api/v1`. Everything except register/login/refresh and product
reads requires `Authorization: Bearer <access_token>`.

| Method | Path                    | Description                                                         |
|--------|-------------------------|---------------------------------------------------------------------|
| POST   | `/auth/register`        | Create a user                                                       |
| POST   | `/auth/login`           | OAuth2 password form (`username` = email) → access + refresh token  |
| POST   | `/auth/refresh`         | Rotate the token pair (old refresh token is revoked)                |
| POST   | `/auth/logout`          | Revoke the current access token                                     |
| GET    | `/users/me`             | Current user                                                        |
| POST   | `/products`             | Create a product (`name`, `price`, `stock_quantity`)                |
| GET    | `/products`             | List products (`skip`, `limit`), cached                             |
| GET    | `/products/{id}`        | Get a product, cached                                               |
| POST   | `/orders`               | Create an order. **`Idempotency-Key` header is required**           |
| GET    | `/orders/{id}`          | Get own order, status `pending` / `confirmed` / `cancelled`         |
| POST   | `/orders/{id}/cancel`   | Cancel a pending order, reserved stock is returned                  |
| POST   | `/orders/{id}/pay`      | Mock payment: `pending` → `confirmed` (only before `expires_at`)    |
| WS     | `/ws?token=<access>`    | Real-time `stock_changed` events                                    |
| GET    | `/health`, `/health/ready` | Liveness / readiness (DB + Redis)                                |

```bash
curl -X POST localhost:8080/api/v1/orders \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: 6f1c2b9e-0d8a-4c55-9a43-5d1f7b0e2a11" \
  -H "Content-Type: application/json" \
  -d '{"items": [{"product_id": 1, "quantity": 2}, {"product_id": 3, "quantity": 1}]}'
```

### Status codes

| Code | When |
|------|------|
| 201  | Order created, or the same request replayed with the same key (`Idempotent-Replayed: true`) |
| 400  | `Idempotency-Key` missing or malformed (8–255 printable ASCII characters, no spaces) |
| 401  | Missing / invalid / revoked token |
| 404  | Product or order not found (also for someone else's order, so ids can't be probed) |
| 409  | `insufficient_stock`, `invalid_order_state` (e.g. cancelling a confirmed order), key still being processed |
| 422  | Validation error, or `Idempotency-Key` reused with a different request body |

All errors share one shape:

```json
{"error": {"code": "insufficient_stock", "message": "not enough stock for product 1", "request_id": "..."}}
```

---

## Architecture

```
HTTP / WS ──► nginx :8080 ──► gunicorn (4 uvicorn workers)
                                   │
            app/api/v1/routes      │  handlers: HTTP only (status codes, headers, auth deps)
                   │               │
            app/services           │  business rules, transaction boundaries, cache + events
                   │               │
            app/repositories       │  hand-written SQL via asyncpg, return plain dataclasses
                   │
              PostgreSQL ◄──── Celery worker ◄── Celery beat (every 30s / hourly)
                   
              Redis: cache · JWT denylist · pub/sub (ws events) · Celery broker
```

```
app/
├── api/            deps.py (DI: connection → repositories → services), v1/routes/*
├── services/       auth, product, order
├── repositories/   user, product, order, idempotency_key  (raw SQL)
├── models/         plain dataclasses, no ORM
├── schemas/        pydantic request/response models
├── cache/          redis client, cache-aside helper
├── websocket/      connection manager, redis pub/sub fan-out
├── tasks/          celery app + periodic jobs
├── db/             asyncpg pool
└── core/           config, security (JWT), errors, logging, middleware, rate limit
```

Each request gets one pooled connection (`Depends(get_connection)`); FastAPI caches the
dependency, so every repository in a request shares it and the service decides where the
transaction starts and ends.

---

## Decisions

### 1. No ORM — asyncpg and hand-written SQL

- Repositories execute SQL directly with `asyncpg` (`$1` placeholders, never string
  interpolation of values). Rows are mapped into small frozen dataclasses in `app/models`.
- Why asyncpg: it is the fastest async Postgres driver and supports arrays well, so
  multi-row inserts use a single `INSERT ... SELECT FROM unnest(...)` statement.
- The earlier SQLAlchemy models were removed. Alembic is kept only as a **migration
  runner**: new migrations are written as plain SQL in `op.execute(...)`. It gives
  versioned, reversible migrations (`upgrade`/`downgrade`). No ORM is used at runtime.
- `updated_at` is maintained by a Postgres trigger, so no query can forget to set it.

### 2. Concurrency correctness (50 parallel requests, stock = 10 → exactly 10 succeed)

Stock is reserved with one conditional, atomic statement per product:

```sql
UPDATE products
SET stock_quantity = stock_quantity - $2
WHERE id = $1 AND stock_quantity >= $2
RETURNING price, stock_quantity;
```

- Postgres takes a row lock for the update. Concurrent transactions queue on that row.
  When a transaction gets the lock, it **re-evaluates the `WHERE` against the latest
  committed row**. The 11th request sees `stock_quantity = 0`, matches no rows, and gets
  `409 insufficient_stock`. Check and decrement are one step, so there is no
  "read, then write" race.
- **Multi-item orders**: lines are merged per product and reserved **in ascending
  `product_id` order** inside one transaction. Every transaction takes locks in the
  same global order, so two orders `[A, B]` and `[B, A]` cannot deadlock. A test covers
  this case. If any line fails, the whole transaction rolls back and nothing stays reserved.
- `CHECK (stock_quantity >= 0)` in the schema is the last line of defense.
- The order stores `unit_price` from `RETURNING price`. That is the price at the moment
  stock was locked, so later price changes do not affect existing orders.

Alternatives considered:

| Approach | Why not |
|---|---|
| `SELECT ... FOR UPDATE` then `UPDATE` | Takes the same lock but needs an extra round trip. The conditional update does both at once. |
| Optimistic locking (`version` column) | Under heavy contention on a hot product most requests conflict and must retry. |
| `SERIALIZABLE` isolation | Correct, but the app would have to retry serialization failures. Pessimistic row locks give the same result with less complexity. |
| Redis distributed lock / Redis stock counter | Two sources of truth. A lock in Redis plus a write in Postgres is not atomic. Postgres stays the single source of truth. |

Verified by `tests/test_orders.py::test_fifty_parallel_orders_for_ten_items_only_ten_succeed`
(service level), `tests/test_orders_api.py::test_fifty_parallel_requests_over_http`
(through the HTTP layer), and `scripts/load_test.py` (against the Docker stack through nginx).

### 3. Idempotency (`Idempotency-Key` is required on `POST /orders`)

- Keys are **scoped per user** (`UNIQUE (user_id, key)`), so two users can't collide or
  read each other's responses.
- The key is claimed **inside the same transaction** that reserves stock:

  ```sql
  INSERT INTO idempotency_keys (user_id, key, request_hash, status)
  VALUES ($1, $2, $3, 'processing')
  ON CONFLICT ON CONSTRAINT uq_idempotency_keys_user_id_key DO NOTHING
  RETURNING id;
  ```

  - Inserted: this request owns the key. It reserves stock, creates the order, stores
    the response (`status = 'completed'`, `response_body`, `order_id`) and commits
    **atomically** with the order.
  - Conflict while the first request is still running: Postgres makes the second
    `INSERT` **wait on the unique index** until the first transaction finishes. The
    second request then replays the stored response with the same `201` body and
    `Idempotent-Replayed: true`. Stock is decremented once. A test sends 20 parallel
    requests with one key and gets exactly one order.
  - Same key, different body: compared by `sha256` of the normalized body → `422`.
- If the order fails (for example insufficient stock), the transaction rolls back
  **including the key**. Failed attempts are not cached, and the client can retry with
  the same key after stock is added.
- Keys older than 24h are deleted by an hourly job (`IDEMPOTENCY_KEY_TTL_HOURS`).
- A missing header returns `400` instead of creating a non-idempotent order. The task
  requires the header.

### 4. Order lifecycle

```
pending ──pay──► confirmed
   │
   ├──cancel (user)──────────► cancelled   (stock returned)
   └──expires_at passed (job)─► cancelled   (stock returned)
```

- Every transition is one conditional update, for example
  `UPDATE orders SET status = 'cancelled' ... WHERE id = $1 AND user_id = $2 AND status = 'pending'`.
  Exactly one of several concurrent actions (cancel ×5, cancel vs. pay, user vs. job)
  wins. The others get `409`. A test sends 5 parallel cancels: stock is returned once.
- Cancel returns stock **in the same transaction** as the status change. Products are
  locked in id order (same rule as above). The quantity is summed per product, so an
  `UPDATE ... FROM` never applies only one of several matching rows.
- `pay` is a mock payment endpoint. It also checks `expires_at > now()`, so the 15-minute
  deadline is exact even if the background job hasn't run yet.
- `expires_at` is computed by the database (`now() + 15 min`), so app and DB clocks
  can't disagree.

### 5. Background job: auto-cancel unpaid orders after 15 minutes

- **Celery beat** schedules `orders.expire_pending` every 30s. A **Celery worker** runs it
  in a separate container from the API.
- The job picks expired orders with
  `SELECT ... WHERE status = 'pending' AND expires_at <= now() ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED`.
  It returns their stock and marks them `cancelled` in one transaction, batch by batch.
  - `SKIP LOCKED`: several workers, or a slow previous run, never process the same
    order twice and never block each other or a user's request.
  - A partial index `ON orders (expires_at) WHERE status = 'pending'` keeps the scan
    small. Confirmed and cancelled orders are not in the index.
- Why Celery and not an in-process scheduler (APScheduler): the API runs 4 gunicorn
  workers, so an in-process scheduler would fire 4 times. Celery also gives retries,
  monitoring, and independent scaling of background work.
- Worst-case delay from deadline to cancellation is about `EXPIRE_ORDERS_INTERVAL_SECONDS`.
  Paying is rejected exactly at the deadline (see 4).

### 6. Caching with Redis

**Strategies considered**

| Strategy | How it works | Used? |
|---|---|---|
| **Cache-aside (lazy loading)** | App reads cache → on miss reads DB and fills the cache with a TTL. On writes, the app deletes the key. | ✅ products, product lists, orders |
| Read-through | Cache library loads from DB itself on a miss. | ❌ same effect as cache-aside, but hides the DB call behind a library |
| Write-through | Every write updates DB and cache synchronously. | ❌ stock changes on every order. Rewriting the cache each time costs writes for data that may never be read, and two concurrent writers can leave the cache in the wrong order |
| Write-behind (write-back) | Write to cache, flush to DB later. | ❌ never for stock or money. Redis would become the source of truth and could lose reservations |
| Refresh-ahead | Refresh hot keys before they expire. | ❌ not needed at this scale |

**What is cached**

| Key | Value | TTL | Invalidated when |
|---|---|---|---|
| `product:{id}` | product JSON | 300s | stock changes (order, cancel, expiry) |
| `products:list:v{n}:{skip}:{limit}` | page JSON | 60s | product created / any stock change → `INCR products:list:version` |
| `order:{id}` | order JSON + owner id | 60s | cancel, pay, expiry |

Rules:

- **The cache is never used for decisions.** Reservation always runs the atomic SQL
  above. The cache only serves `GET` responses, so stale data can show an old
  `stock_quantity` for a moment but can never cause overselling.
- **Invalidate after commit** with delete, not set. Deleting before commit could let a
  concurrent reader re-cache the old value. Setting from the writer could race with
  another writer.
- **Versioned namespace for lists**: there is no `KEYS`/`SCAN`-and-delete. Bumping a
  version number makes all old list pages unreachable, and they expire by TTL.
- **TTL jitter** (+0–10%) spreads expirations so hot keys don't all expire at once
  (stampede).
- **Fail-open**: if Redis is down, cache calls are logged and treated as misses. The
  service keeps working on Postgres alone (`tests/test_cache.py`).
- Ownership is checked on cached orders too. The cached value stores `user_id`.

### 7. Authentication

- JWT (HS256) access token (30 min) and refresh token (7 days). Each has a `jti` and a
  `type`, so a refresh token can't be used as an access token.
- Refresh **rotates** the pair and denylists the old refresh `jti`. Logout denylists the
  access `jti`. The denylist lives in Redis with TTL = remaining token lifetime, so it
  cleans itself.
- Passwords are hashed with bcrypt. Login is rate-limited (`slowapi`; Redis storage
  outside local env, so limits are shared across workers).
- Registration uses `INSERT ... ON CONFLICT (email) DO NOTHING`, so two parallel sign-ups
  with the same email can't both succeed.

### 8. WebSocket (real-time stock)

- `ws://localhost:8080/api/v1/ws?token=<access_token>`. Browsers can't set headers on a
  WebSocket handshake, so the token is passed in the query string. Invalid tokens are
  closed with `1008`.
- After a commit that changes stock (order, cancel, expiry), the service publishes
  `{"event": "stock_changed", "product_id": 1, "stock_quantity": 7}` to the Redis channel
  `ws:events`. **Every API process subscribes** and forwards the event to its own
  clients. This is needed because there are 4 gunicorn workers with separate memory, and
  expiry happens in the Celery worker, which has no WebSocket clients at all.
- Only stock is broadcast. Order details are private and are never broadcast to everyone.

### 9. Operations

- One command: `docker compose up --build` starts postgres, redis, api, worker, beat and
  nginx. Health checks gate the start order. nginx serves on **:8080** (`APP_PORT`) and
  forwards WebSocket upgrades.
- Pool sizing: 4 workers × `DB_POOL_MAX_SIZE=10` = 40 connections, below Postgres'
  default 100. Requests over the limit wait for a free connection instead of failing.
- Structured logs (structlog, JSON outside local) with an `X-Request-ID` that also
  appears in error responses.

---

## Database schema

Source for [dbdiagram.io](https://dbdiagram.io/d): [`docs/schema.dbml`](docs/schema.dbml).
Paste it into the editor to get the diagram.

```mermaid
erDiagram
    users ||--o{ orders : places
    users ||--o{ idempotency_keys : owns
    orders ||--|{ order_items : contains
    products ||--o{ order_items : "reserved in"
    orders |o--o| idempotency_keys : "created by"

    users { int id PK
            varchar email UK
            varchar hashed_password
            bool is_active }
    products { int id PK
               varchar name
               numeric price "CHECK >= 0"
               int stock_quantity "CHECK >= 0" }
    orders { int id PK
             int user_id FK
             varchar status "pending|confirmed|cancelled"
             numeric total_price
             timestamptz expires_at "partial index WHERE pending" }
    order_items { int id PK
                  int order_id FK
                  int product_id FK
                  int quantity "CHECK > 0"
                  numeric unit_price "price snapshot" }
    idempotency_keys { int id PK
                       int user_id FK "UNIQUE(user_id, key)"
                       varchar key
                       varchar request_hash
                       varchar status
                       jsonb response_body
                       int order_id FK }
```

---

## Development

```bash
python -m venv .venv && source .venv/bin/activate
make install          # pip install -e ".[dev]"
make lint typecheck   # ruff + mypy
make test             # unit + integration tests
```

Integration tests need a real Postgres. They use `TEST_DATABASE_URL` if set, otherwise
they start `postgres:16` with testcontainers. Without either, they are skipped.

```bash
TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/oi_test pytest
```

What the tests cover: 50 parallel orders vs. stock 10, 20 parallel requests with one
idempotency key, key reuse with a different body, per-user key scope, full rollback on
failure, crossing multi-item orders (deadlock check), 5 parallel cancels, ownership,
pay/cancel transitions, expiry job, HTTP status codes and headers, cache fail-open, and
WebSocket auth.

## Trade-offs and possible next steps

- A hot product serializes its buyers on one row lock. That is correct, and fine for
  this scope. At much larger scale, the next step would be stock sharded into several
  rows ("buckets") per product, or a reservation queue.
- `pay` is a mock. A real integration would confirm via a payment-provider webhook,
  using the same conditional `UPDATE ... WHERE status = 'pending'` transition.
- Product creation is open to any authenticated user. A real marketplace would add
  roles (seller/admin).
- Events are fire-and-forget pub/sub. If clients must never miss an update, use Redis
  Streams or an outbox table.
