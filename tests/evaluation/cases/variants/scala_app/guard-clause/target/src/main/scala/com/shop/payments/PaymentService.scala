package com.shop.payments

class PaymentService {
  def charge(orderId: String): Unit = {
    require(orderId != null, "orderId is required")
  }
}
