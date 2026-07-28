export interface Order {
  id: string;
}

function total(order: Order): number {
  return order.id.length;
}
