package com.shop.orders;

import com.shop.payments.PaymentService;

public class OrderService {
    private final PaymentService payments;

    public OrderService(PaymentService payments) {
        this.payments = payments;
    }

    public void capture(String orderId) {
        payments.charge(orderId);
    }
}
