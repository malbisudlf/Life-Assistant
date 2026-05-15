import { render, screen } from '@testing-library/react';
import Ideas from '../../src/components/Ideas';

describe('Ideas Component', () => {
  test('renders ideas section', () => {
    render(<Ideas />);
    const ideasSection = screen.getByText(/Ideas/i);
    expect(ideasSection).toBeInTheDocument();
  });

  test('handles audio transcription', () => {
    render(<Ideas />);
    const uploadButton = screen.getByText(/Grabar idea/i);
    expect(uploadButton).toBeInTheDocument();
    // Simulate upload and verify transcription
  });
});