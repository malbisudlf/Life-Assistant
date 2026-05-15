import { render, screen } from '@testing-library/react';
import Dashboard from '../../src/components/Dashboard';

describe('Dashboard Component', () => {
  test('renders dashboard with authentication form', () => {
    render(<Dashboard />);
    const loginButton = screen.getByText(/Login/i);
    expect(loginButton).toBeInTheDocument();
  });

  test('handles Home Assistant toggle', () => {
    render(<Dashboard />);
    const haToggle = screen.getByLabelText(/Toggle HA/LA/i);
    expect(haToggle).toBeInTheDocument();
    // Simulate toggle action and verify state change
  });
});