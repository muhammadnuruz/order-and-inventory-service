# Order and Inventory Service

Order and inventory service for a mini marketplace.

## Tech Stack

- FastAPI (async, Pydantic, automatic OpenAPI docs)
- PostgreSQL — accessed via raw SQL queries (no ORM)
- Redis — product cache
- Alembic — database migrations
- JWT — authentication
- Docker Compose

## Getting Started

```bash
docker compose up --build
```

All services (Postgres, Redis, API) and migrations start with a single command.

- API — http://localhost:8080
- Docs — http://localhost:8080/docs
- Health — http://localhost:8080/health

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| POST | `/auth/register` | Register a new user |
| POST | `/auth/login` | Obtain a JWT token |
| POST | `/products` | Create a product |
| GET | `/products/{id}` | Get a product |
| POST | `/orders` | Create an order |
| GET | `/orders/{id}` | Get an order |
| POST | `/orders/{id}/pay` | Pay for an order |
| POST | `/orders/{id}/cancel` | Cancel an order |

## Features

- **Stock control** — for concurrent orders on the same product, stock is decremented atomically in a single SQL query; if stock is insufficient the request returns `409`.
- **Idempotency** — the `Idempotency-Key` header prevents the same order from being created twice.
- **Caching** — product `GET` requests check Redis first; the cache is invalidated when a product changes.
- **Auto-cancellation** — `pending` orders older than 15 minutes are cancelled every 30 seconds.

## Database Schema

[DB Schema](https://dbdiagram.io/d/6aa03c2228e65f9ec2515b2d)
