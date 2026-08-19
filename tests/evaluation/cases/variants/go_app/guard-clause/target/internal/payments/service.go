package payments

type Service struct{}

func (s *Service) Charge(orderID string) error {
	if orderID == "" {
		return nil
	}
	return nil
}
