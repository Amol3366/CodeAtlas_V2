// Express routes for orders.

import express, { Request, Response, Router } from "express";

import { InventoryRepository } from "../repositories/inventoryRepository";
import { OrderService } from "../services/orderService";

const inventory = new InventoryRepository();
const service = new OrderService(inventory);

export const orderRouter: Router = express.Router();

// POST /orders -> OrderService.createOrder
orderRouter.post("/orders", (req: Request, res: Response) => {
  const { sku, quantity } = req.body as { sku: string; quantity: number };
  const order = service.createOrder(sku, quantity);
  res.status(201).json(order);
});
