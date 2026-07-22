// Inventory persistence (in-memory for the fixture).

export class InventoryRepository {
  private stock = new Map<string, number>();

  seed(sku: string, quantity: number): void {
    this.stock.set(sku, quantity);
  }

  available(sku: string): number {
    return this.stock.get(sku) ?? 0;
  }

  reserve(sku: string, quantity: number): boolean {
    const current = this.available(sku);
    if (current < quantity) {
      return false;
    }
    this.stock.set(sku, current - quantity);
    return true;
  }
}
