import { total } from "./orders";

export function render(order) {
  return `Total: ${total(order)}`;
}
