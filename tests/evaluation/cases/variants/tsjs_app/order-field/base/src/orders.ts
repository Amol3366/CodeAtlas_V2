export interface Order {
  id: number;
}

export function total(order: Order): number {
  return order.id.length;
}
