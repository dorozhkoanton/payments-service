# Payment Service

## Запуск

```bash
cp .env.example .env
docker compose up -d --build
```

| Сервис | Адрес |
| --- | --- |
| API (Swagger) | http://localhost:8000/docs |
| RabbitMQ | http://localhost:15672 (guest / guest) |
| Приемник webhook | http://localhost:8081/webhook/received |

API-ключ `dev-secret-key`, задается `.env`

## Тесты

```bash
uv sync
uv run pytest
```

## Примеры

Создание платежа

```bash
curl -X POST localhost:8000/api/v1/payments \
  -H 'X-API-Key: dev-secret-key' \
  -H 'Idempotency-Key: order-1' \
  -H 'Content-Type: application/json' \
  -d '{"amount": "100.00", "currency": "RUB", "description": "Заказ 1", "metadata": {"order_id": "1"}, "webhook_url": "http://webhook-receiver:8080/webhook"}'
```

```json
{"payment_id": "...", "status": "pending", "created_at": "..."}
```

Получение платежа

```bash
curl localhost:8000/api/v1/payments/<payment_id> -H 'X-API-Key: dev-secret-key'
```