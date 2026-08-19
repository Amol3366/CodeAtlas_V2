pub struct PaymentService;

impl PaymentService {
    pub fn charge(&self, order_id: &str) {
        assert!(!order_id.is_empty());
    }
}
