package com.shop.orders

import com.shop.payments.PaymentService

class OrderService(payments: PaymentService) {
  def capture(orderId: String): Unit = {
    payments.charge(orderId)
  }
}
