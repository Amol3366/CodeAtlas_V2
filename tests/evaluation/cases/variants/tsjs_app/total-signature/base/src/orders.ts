export interface Order {
  id: string;
}

export function total(order: Order): string {
  return order.id;
}
