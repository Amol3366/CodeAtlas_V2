// Configuration keys for the order service.

export interface Settings {
  databaseUrl: string;
  maxOrderQuantity: number;
}

// DATABASE_URL controls the database connection.
export function getSettings(): Settings {
  return {
    databaseUrl: process.env.DATABASE_URL ?? "sqlite://./orders.db",
    maxOrderQuantity: Number(process.env.MAX_ORDER_QUANTITY ?? "1000"),
  };
}
