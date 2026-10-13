# Order & Inventory Reservation Service

[![CI](https://github.com/muhammadnuruz/order-and-inventory-service/actions/workflows/ci.yml/badge.svg)](https://github.com/muhammadnuruz/order-and-inventory-service/actions/workflows/ci.yml)

Backend for a small marketplace. It handles:

- products
- orders with several items and stock reservation
- idempotent order creation
- order cancellation
- automatic expiry of unpaid orders
- real-time stock updates over WebSocket

**Stack:** Python 3.12, FastAPI, PostgreSQL 16, SQLAlchemy 2.0 (async, asyncpg), Redis 7, Celery + beat, Alembic, Gunicorn/Uvicorn, Nginx, Docker Compose, pytest + testcontainers.

---

## Quick start

```bash
docker compose up --build
```

- API: http://localhost:8080
- Swagger UI: http://localhost:8080/docs
- No `.env` file is needed. Every setting has a default in `docker-compose.yaml`. A `.env` file (see `.env.example`) only overrides them.
- Migrations run automatically when the `api` container starts.

To check the stock guarantee against the running stack:

```bash
python scripts/load_test.py --requests 50 --stock 10
# product 1: {201: 10, 409: 40}, stock left: 0
```

---

## API

All endpoints are under `/api/v1`. Every endpoint except register, login, refresh and product reads needs `Authorization: Bearer <access_token>`.

| Method | Path                       | Description                                                          |
|--------|----------------------------|----------------------------------------------------------------------|
| POST   | `/auth/register`           | Create a user                                                        |
| POST   | `/auth/login`              | OAuth2 password form (`username` = email). Returns access + refresh token |
| POST   | `/auth/refresh`            | Get a new token pair. The old refresh token is revoked               |
| POST   | `/auth/logout`             | Revoke the current access token                                      |
| GET    | `/users/me`                | Current user                                                         |
| POST   | `/products`                | Create a product (`name`, `price`, `stock_quantity`)                 |
| GET    | `/products`                | List products (`skip`, `limit`). Cached                              |
| GET    | `/products/{id}`           | Get a product. Cached                                                |
| POST   | `/orders`                  | Create an order. **`Idempotency-Key` header is required**            |
| GET    | `/orders/{id}`             | Get your own order. Status: `pending`, `confirmed` or `cancelled`    |
| POST   | `/orders/{id}/cancel`      | Cancel a pending order. Reserved stock is returned                   |
| POST   | `/orders/{id}/pay`         | Mock payment: `pending` → `confirmed`. Only before `expires_at`      |
| WS     | `/ws?token=<access>`       | Real-time `stock_changed` events                                     |
| GET    | `/health`, `/health/ready` | Liveness and readiness (DB + Redis)                                  |

Example:

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
| 201  | Order created. Or the same request was sent again with the same key (response has `Idempotent-Replayed: true`) |
| 400  | `Idempotency-Key` is missing or invalid (8–255 printable ASCII characters, no spaces) |
| 401  | Token is missing, invalid or revoked |
| 404  | Product or order not found. Also returned for someone else's order, so IDs can't be guessed |
| 409  | `insufficient_stock`, `invalid_order_state` (for example, cancelling a confirmed order), or the key is still being processed |
| 422  | Validation error, or the `Idempotency-Key` was reused with a different body |

All errors use the same shape:

```json
{"error": {"code": "insufficient_stock", "message": "not enough stock for product 1", "request_id": "..."}}
```

---

## Architecture

```
HTTP / WS ──► nginx :8080 ──► gunicorn (4 uvicorn workers)
                                   │
            app/api/v1/routes      │  HTTP only: status codes, headers, auth dependencies
                   │               │
            app/services           │  business rules, transaction boundaries, cache, events
                   │               │
            app/repositories       │  SQLAlchemy queries
                   │
              PostgreSQL ◄──── Celery worker ◄── Celery beat (every 30s / hourly)

              Redis: cache · JWT denylist · pub/sub (WS events) · Celery broker
```

```
app/
├── api/            deps.py (dependency injection), v1/routes/*
├── services/       auth, product, order
├── repositories/   user, product, order, idempotency_key
├── models/         SQLAlchemy ORM models
├── schemas/        Pydantic request and response models
├── cache/          Redis client, cache-aside helper
├── websocket/      connection manager, Redis pub/sub fan-out
├── tasks/          Celery app and periodic jobs
├── db/             declarative base, async engine and session
└── core/           config, JWT security, errors, logging, middleware, rate limit
```

Each request gets one `AsyncSession` (`Depends(get_session)`). All repositories in a request share it. The service decides where the transaction ends (commit or rollback).

---

## Design decisions

### 1. SQLAlchemy 2.0 async ORM

The task asked for raw SQL without an ORM. I used SQLAlchemy anyway:

- Models, constraints and indexes are in one place (`app/models`). `alembic check` confirms the migrations match the models.
- The critical paths use explicit SQL statements (`update ... where`, `insert ... on conflict do nothing`, `select ... for update skip locked`). They are not "load object, change it, flush". ORM objects are used for reads and for creating rows.
- The driver is `asyncpg`. Relations that are always needed (`Order.items`) use `lazy="selectin"`, so async code never does a hidden lazy load.
- Status columns use `Enum(native_enum=False)` (varchar + CHECK). Adding a status later is a normal migration.

### 2. Concurrency: 50 parallel requests, stock = 10 → exactly 10 succeed

Stock is reserved with one conditional, atomic statement per product:

```python
update(Product)
.where(Product.id == product_id, Product.stock_quantity >= quantity)
.values(stock_quantity=Product.stock_quantity - quantity)
.returning(Product.price, Product.stock_quantity)
```

```sql
UPDATE products SET stock_quantity = stock_quantity - :qty, updated_at = now()
WHERE id = :id AND stock_quantity >= :qty
RETURNING price, stock_quantity;
```

- Postgres locks the row during the update. Other transactions wait for that lock. When a transaction gets the lock, Postgres checks the `WHERE` against the latest committed row. The 11th request sees `stock_quantity = 0`, matches no row, and gets `409 insufficient_stock`.
- The check and the decrement happen in one statement. There is no read-then-write race.
- **Multi-item orders:** lines are merged per product and reserved in ascending `product_id` order, in one transaction. Every transaction takes locks in the same order, so orders `[A, B]` and `[B, A]` cannot deadlock. If any line fails, the whole transaction rolls back.
- `CHECK (stock_quantity >= 0)` in the schema is the last safety net.
- The order stores `unit_price` from `RETURNING price`. Later price changes do not affect existing orders.

Other options I rejected:

| Approach | Why not |
|---|---|
| `SELECT ... FOR UPDATE`, then `UPDATE` | Same lock, but one extra round trip |
| Optimistic locking (`version` column) | On a hot product, most requests conflict and must retry |
| `SERIALIZABLE` isolation | Correct, but the app must retry serialization errors |
| Redis lock or Redis stock counter | Two sources of truth. A Redis lock plus a Postgres write is not atomic |

Tests: `tests/test_orders.py::test_fifty_parallel_orders_for_ten_items_only_ten_succeed` (service level), `tests/test_orders_api.py::test_fifty_parallel_requests_over_http` (HTTP level), and `scripts/load_test.py` (Docker stack through nginx).

### 3. Idempotency

`Idempotency-Key` is required on `POST /orders`.

- Keys are scoped per user (`UNIQUE (user_id, key)`). Two users cannot collide or read each other's responses.
- The key is claimed in the same transaction that reserves stock:

  ```python
  insert(IdempotencyKey)
  .values(user_id=user_id, key=key, request_hash=request_hash, status=PROCESSING)
  .on_conflict_do_nothing(constraint="uq_idempotency_keys_user_id_key")
  .returning(IdempotencyKey.id)
  ```

  - **Insert succeeds:** this request owns the key. It reserves stock, creates the order, stores the response (`status = COMPLETED`, `response_body`, `order_id`), and commits everything at once.
  - **Conflict while the first request is still running:** the second `INSERT` waits on the unique index until the first transaction ends. Then it returns the stored response with `201` and `Idempotent-Replayed: true`. Stock is decremented once. A test sends 20 parallel requests with one key and gets exactly one order.
  - **Same key, different body:** the body is compared by normalized SHA-256 hash. Result: `422`.
- If the order fails (for example, not enough stock), the transaction rolls back, including the key. Failed attempts are not cached, so the client can retry with the same key after stock is added.
- An hourly job deletes keys older than 24 hours (`IDEMPOTENCY_KEY_TTL_HOURS`).
- A missing header returns `400`. The order is never created without the key.

### 4. Order lifecycle

```
pending ──pay──► confirmed
   │
   ├── cancel (user) ───────► cancelled   (stock returned)
   └── expires_at passed ───► cancelled   (stock returned)
```

- Every status change is one conditional update, for example `UPDATE orders SET status = 'CANCELLED' ... WHERE id = :id AND user_id = :user_id AND status = 'PENDING'`. When several actions race (5 cancels, cancel vs. pay, user vs. job), exactly one wins. The others get `409`. A test sends 5 parallel cancels and checks that stock is returned once.
- Cancel returns stock in the same transaction as the status change. Products are locked in ID order. Quantities are summed per product.
- `pay` also checks `expires_at > now()`. The 15-minute deadline is exact, even if the background job has not run yet.
- `expires_at` is set by the database (`now() + 15 min`), so the app and the DB clock cannot disagree.

### 5. Background job: cancel unpaid orders after 15 minutes

- **Celery beat** runs `orders.expire_pending` every 30 seconds. A **Celery worker** runs it in its own container, separate from the API.
- The job selects expired orders with `SELECT ... WHERE status = 'PENDING' AND expires_at <= now() ORDER BY id LIMIT 100 FOR UPDATE SKIP LOCKED`. In one transaction per batch, it returns the stock and sets the status to `cancelled`.
  - `SKIP LOCKED`: several workers, or a slow previous run, never process the same order twice or block each other.
  - A partial index `ON orders (expires_at) WHERE status = 'PENDING'` keeps the scan small.
- Each task run uses its own engine with `NullPool`. Celery calls `asyncio.run` per task, so a pooled connection from an old event loop is never reused.
- Why Celery and not APScheduler: the API runs 4 Gunicorn workers. An in-process scheduler would run 4 times. Celery also gives retries, monitoring, and separate scaling.
- Maximum delay between the deadline and the cancellation is about `EXPIRE_ORDERS_INTERVAL_SECONDS`. Payment is rejected exactly at the deadline anyway (see 4).

### 6. Caching with Redis

**Strategies**

| Strategy | Used? | Reason |
|---|---|---|
| Cache-aside (lazy loading) | Yes | Read cache. On a miss, read DB and fill the cache with a TTL. On writes, delete the key |
| Read-through | No | Same result as cache-aside, but hides the DB call inside a library |
| Write-through | No | Stock changes on every order. Updating the cache each time costs writes, and two writers can leave the cache in the wrong order |
| Write-behind | No | Never for stock or money. Redis would become the source of truth and could lose reservations |
| Refresh-ahead | No | Not needed at this scale |

**What is cached**

| Key | Value | TTL | Invalidated when |
|---|---|---|---|
| `product:{id}` | product JSON | 300s | Stock changes (order, cancel, expiry) |
| `products:list:v{n}:{skip}:{limit}` | page JSON | 60s | Product created, or any stock change (`INCR products:list:version`) |
| `order:{id}` | order JSON + owner ID | 60s | Cancel, pay, expiry |

Rules:

- **The cache is never used to make decisions.** Reservation always runs the atomic SQL above. The cache only serves `GET` responses. A stale `stock_quantity` can show for a moment, but it cannot cause overselling.
- **Delete after commit, don't set.** Deleting before commit lets a concurrent reader cache the old value again. Setting from the writer can race with another writer.
- **Versioned list keys.** No `KEYS`/`SCAN` deletes. Bumping the version makes old list pages unreachable. They expire by TTL.
- **TTL jitter** (+0–10%) so hot keys don't all expire at the same time.
- **Fail-open.** If Redis is down, cache calls are logged and treated as misses. The service works on Postgres alone (`tests/test_cache.py`).
- Cached orders are ownership-checked too. The cached value stores `user_id`.

### 7. Authentication

- JWT (HS256). Access token: 30 minutes. Refresh token: 7 days. Both have a `jti` and a `type`, so a refresh token cannot be used as an access token.
- Refresh rotates the pair and adds the old refresh `jti` to the denylist. Logout adds the access `jti` to the denylist. The denylist is in Redis, with a TTL equal to the token's remaining lifetime.
- Passwords are hashed with bcrypt.
- Login is rate-limited (`slowapi`). Outside the local environment, limits are stored in Redis, so all workers share them.
- Registration uses `insert(User).on_conflict_do_nothing(index_elements=[User.email])`. Two parallel sign-ups with the same email cannot both succeed.

### 8. WebSocket (real-time stock)

- URL: `ws://localhost:8080/api/v1/ws?token=<access_token>`. Browsers cannot set headers on a WebSocket handshake, so the token is in the query string. Invalid tokens are closed with code `1008`.
- After a commit that changes stock, the service publishes `{"event": "stock_changed", "product_id": 1, "stock_quantity": 7}` to the Redis channel `ws:events`.
- Every API process subscribes to that channel and forwards events to its own clients. This is needed because the 4 Gunicorn workers have separate memory. Expiry runs in the Celery worker, which has no WebSocket clients.
- Only stock changes are broadcast. Order details are private.

### 9. Operations

- `docker compose up --build` starts Postgres, Redis, api, worker, beat and nginx. Health checks control the start order.
- nginx listens on port **8080** (`APP_PORT`) and forwards WebSocket upgrades.
- Connection pool: 4 workers × (`DB_POOL_SIZE=5` + `DB_MAX_OVERFLOW=5`) = at most 40 connections. Postgres allows 100 by default. Requests over the limit wait for a free connection.
- Logs are structured (structlog, JSON outside local). Every request has an `X-Request-ID`, which also appears in error responses.

---

## Database schema

Diagram: https://dbdiagram.io/d/6aa03c2228e65f9ec2515b2d
Source: [`docs/schema.dbml`](docs/schema.dbml)

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
             varchar status "PENDING|CONFIRMED|CANCELLED"
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
make test             # unit and integration tests
```

Integration tests need a real Postgres. They use `TEST_DATABASE_URL` if it is set. Otherwise they start `postgres:16` with testcontainers. If neither is available, they are skipped.

```bash
TEST_DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/oi_test pytest
```

The tests cover:

- 50 parallel orders against stock 10
- 20 parallel requests with one idempotency key
- key reuse with a different body
- per-user key scope
- full rollback on failure
- crossing multi-item orders (deadlock check)
- 5 parallel cancels
- ownership checks
- pay and cancel transitions
- the expiry job
- HTTP status codes and headers
- cache fail-open
- WebSocket auth

### CI

GitHub Actions (`.github/workflows/ci.yml`) runs on every pull request and on every push to `main`:

1. **lint:** `ruff check`, `ruff format --check`, `mypy app`.
2. **test:** Postgres 16 service container. Runs `alembic upgrade head` and `alembic check`, then `pytest`.
3. **docker:** builds and starts the full Compose stack, waits for `/health/ready`, and runs `scripts/load_test.py` through nginx. The result must be exactly 10 × `201` out of 50.

---

## Trade-offs and next steps

- A hot product serializes its buyers on one row lock. This is correct and fine at this scale. At much larger scale, split a product's stock into several rows ("buckets"), or use a reservation queue.
- `pay` is a mock. A real integration would confirm payment through a provider webhook, using the same conditional `UPDATE ... WHERE status = 'PENDING'`.
- Any authenticated user can create products. A real marketplace would need roles (seller, admin).
- Events are fire-and-forget. If clients must never miss an update, use Redis Streams or an outbox table.
