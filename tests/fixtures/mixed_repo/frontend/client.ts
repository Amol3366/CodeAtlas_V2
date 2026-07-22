// Notification client that calls the backend.

export interface Receipt {
  channel: string;
  recipient: string;
  status: string;
}

export class NotificationClient {
  constructor(private readonly baseUrl: string) {}

  // Posts a notification to the backend NotificationService.
  async notify(recipient: string, message: string): Promise<Receipt> {
    const res = await fetch(`${this.baseUrl}/notify`, {
      method: "POST",
      body: JSON.stringify({ recipient, message }),
    });
    return (await res.json()) as Receipt;
  }
}
