export interface Order {
  id: string;
}

export function total(order: Order): number {
  return order.id.length;
}
