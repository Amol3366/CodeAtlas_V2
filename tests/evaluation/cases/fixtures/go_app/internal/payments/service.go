package payments

type Service struct{}

func (s *Service) Charge(orderID string) error {
	return nil
}
