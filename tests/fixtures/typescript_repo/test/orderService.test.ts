// Tests for OrderService.createOrder (jest).

import { InventoryRepository } from "../src/repositories/inventoryRepository";
import { OrderError, OrderService } from "../src/services/orderService";
import { OrderStatus } from "../src/types/order";

function makeService(): { service: OrderService; inventory: InventoryRepository } {
  const inventory = new InventoryRepository();
  const service = new OrderService(inventory);
  return { service, inventory };
}

describe("OrderService.createOrder", () => {
  it("reserves inventory when available", () => {
    const { service, inventory } = makeService();
    inventory.seed("sku-1", 10);
    const order = service.createOrder("sku-1", 3);
    expect(order.status).toBe(OrderStatus.Reserved);
  });

  it("stays pending when inventory is insufficient", () => {
    const { service } = makeService();
    const order = service.createOrder("sku-1", 3);
    expect(order.status).toBe(OrderStatus.Pending);
  });

  it("rejects non-positive quantity", () => {
    const { service } = makeService();
    expect(() => service.createOrder("sku-1", 0)).toThrow(OrderError);
  });
});
