export async function loadOrder(id: string) {
  const response = await fetch(`/api/orders/${id}`);
  return response.json();
}

export const healthPath = "/health";
