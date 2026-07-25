export async function loadOrder(id: string) {
  const response = await fetch(`/orders/${id}`);
  return response.json();
}

export const healthPath = "/health";
