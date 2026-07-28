import { total } from "./orders";

export function render(order) {
  return `Total is ${total(order)}`;
}
