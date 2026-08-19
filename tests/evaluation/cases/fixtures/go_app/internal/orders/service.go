package orders

import (
	"myapp/internal/payments"
)

type OrderService struct {
	pay *payments.Service
}

func (s *OrderService) Capture(orderID string) error {
	return s.pay.Charge(orderID)
}
