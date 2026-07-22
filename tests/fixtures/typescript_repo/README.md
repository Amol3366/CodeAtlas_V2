# orders-typescript (fixture)

A small Express + TypeScript order service used as a CodeAtlas evaluation
fixture. Contains ESM imports, classes, an Express route, interfaces/enums/type
aliases, configuration, and a jest test.

Key symbols:
- `OrderService.createOrder` — `src/services/orderService.ts`
- `InventoryRepository.reserve` — `src/repositories/inventoryRepository.ts`
- `orderRouter` (route: `POST /orders`) — `src/routes/orderRoutes.ts`
- `Order`, `OrderStatus` — `src/types/order.ts`

Fixture data only — not built or installed as part of CodeAtlas.
