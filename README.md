# Order and Inventory Service

Mini marketplace uchun buyurtma va ombor servisi.

## Texnologiyalar

- FastAPI (async, Pydantic, avtomatik OpenAPI docs)
- PostgreSQL — SQL query'lar orqali (ORM ishlatilmagan)
- Redis — mahsulotlar cache'i
- Alembic — migratsiyalar
- JWT — autentifikatsiya
- Docker Compose

## Ishga tushirish

```bash
docker compose up --build
```

Barcha servislar (Postgres, Redis, API) va migratsiyalar bitta buyruq bilan ishga tushadi.

- API — http://localhost:8080
- Docs — http://localhost:8080/docs
- Health — http://localhost:8080/health

## Endpointlar

| Method | Path | Tavsif |
|--------|------|--------|
| POST | `/auth/register` | Ro'yxatdan o'tish |
| POST | `/auth/login` | JWT token olish |
| POST | `/products` | Mahsulot yaratish |
| GET | `/products/{id}` | Mahsulotni olish |
| POST | `/orders` | Buyurtma yaratish |
| GET | `/orders/{id}` | Buyurtmani olish |
| POST | `/orders/{id}/pay` | To'lov |
| POST | `/orders/{id}/cancel` | Bekor qilish |

## Xususiyatlar

- **Stock nazorati** — bir mahsulotga bir vaqtda kelgan buyurtmalarda stock atomar (bitta SQL query) kamaytiriladi; stock yetmasa `409` qaytadi.
- **Idempotency** — `Idempotency-Key` header orqali bir buyurtma ikki marta yaratilmaydi.
- **Cache** — mahsulot GET so'rovlarida avval Redis tekshiriladi; mahsulot o'zgarsa cache tozalanadi.
- **Avtomatik bekor qilish** — 15 daqiqadan oshgan `pending` buyurtmalar har 30 soniyada bekor qilinadi.

## Database Schema

[DB Schema](https://dbdiagram.io/d/6aa03c2228e65f9ec2515b2d)
