import { render, screen } from '@testing-library/react';
import HomeAssistant from '../../src/components/HomeAssistant';

describe('Home Assistant Component', () => {
  test('renders HA toggle', () => {
    render(<HomeAssistant />);
    const haToggle = screen.getByText(/Toggle HA/LA/i);
    expect(haToggle).toBeInTheDocument();
  });

  test('handles toggle action', () => {
    render(<HomeAssistant />);
    const toggleButton = screen.getByLabelText(/Toggle HA/LA/i);
    expect(toggleButton).toBeInTheDocument();
    // Simulate toggle and verify state change
  });
});