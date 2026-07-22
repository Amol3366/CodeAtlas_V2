// Domain types for the order subsystem.

export enum OrderStatus {
  Pending = "pending",
  Reserved = "reserved",
  Cancelled = "cancelled",
}

export interface Order {
  id: string;
  sku: string;
  quantity: number;
  status: OrderStatus;
}

export type OrderId = string;
