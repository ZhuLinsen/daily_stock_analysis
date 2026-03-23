import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Button } from '../Button';

describe('Button', () => {
  it('renders children', () => {
    render(<Button>Click me</Button>);

    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument();
  });

  it('uses button type by default and exposes the selected variant', () => {
    render(<Button variant="danger">Delete</Button>);

    const button = screen.getByRole('button', { name: 'Delete' });
    expect(button).toHaveAttribute('type', 'button');
    expect(button).toHaveAttribute('data-variant', 'danger');
    expect(button.className).toContain('bg-danger');
  });

  it('disables the button when loading and shows loading text', () => {
    render(<Button isLoading loadingText="Saving">Save</Button>);

    const button = screen.getByRole('button', { name: /saving/i });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Saving')).toBeInTheDocument();
  });

  it('supports the danger-subtle variant', () => {
    render(<Button variant="danger-subtle">Bulk Delete</Button>);

    const button = screen.getByRole('button', { name: 'Bulk Delete' });
    expect(button).toHaveAttribute('data-variant', 'danger-subtle');
    expect(button.className).toContain('border-danger/60');
    expect(button.className).toContain('bg-danger/10');
  });
});
