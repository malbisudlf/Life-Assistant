import { render, screen } from '@testing-library/react';
import { ClassesPanel } from '../../src/components/ClassesPanel';

describe('Classes Panel Component', () => {
  test('renders classes panel with schedule', () => {
    render(<ClassesPanel />);
    const panel = screen.getByText(/Clases/i);
    expect(panel).toBeInTheDocument();
  });

  test('handles class selection', () => {
    render(<ClassesPanel />);
    const classItem = screen.getByText(/Math/i);
    expect(classItem).toBeInTheDocument();
    // Simulate selection and verify state change
  });
});