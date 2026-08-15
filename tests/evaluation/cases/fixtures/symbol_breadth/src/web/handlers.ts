export interface OrderView {
  id: string;
  total: number;
}

export type OrderList = OrderView[];

export class OrderController {
  constructor(private readonly base: string) {}

  async load(id: string): Promise<OrderView> {
    return { id, total: 0 };
  }
}

export function formatTotal(view: OrderView): string {
  return `${view.total}`;
}

export const ORDERS_PATH = "/orders";
