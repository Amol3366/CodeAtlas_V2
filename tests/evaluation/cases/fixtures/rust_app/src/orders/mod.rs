use crate::payments::PaymentService;

pub struct OrderService {
    payments: PaymentService,
}

impl OrderService {
    pub fn capture(&self, order_id: &str) {
        self.payments.charge(order_id);
    }
}
