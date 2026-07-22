// Order orchestration service.

import { InventoryRepository } from "../repositories/inventoryRepository";
import { Order, OrderStatus } from "../types/order";

export class OrderError extends Error {}

export class OrderService {
  constructor(private readonly inventory: InventoryRepository) {}

  // Creates an order, reserving inventory via InventoryRepository.reserve.
  createOrder(sku: string, quantity: number): Order {
    if (quantity <= 0) {
      throw new OrderError("quantity must be positive");
    }
    const reserved = this.inventory.reserve(sku, quantity);
    const status = reserved ? OrderStatus.Reserved : OrderStatus.Pending;
    return {
      id: `ord_${sku}_${Date.now()}`,
      sku,
      quantity,
      status,
    };
  }
}
