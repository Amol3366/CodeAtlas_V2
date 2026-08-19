package com.shop.payments;

public class PaymentService {
    public void charge(String orderId) {
        if (orderId == null) {
            throw new IllegalArgumentException("orderId is required");
        }
    }
}
