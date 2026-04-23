import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ScrollArea } from '../ScrollArea';

describe('ScrollArea', () => {
  it('renders a scrollable viewport and forwards custom classes', () => {
    render(
      <ScrollArea
        className="outer-shell"
        viewportClassName="inner-viewport"
        testId="scroll-area-viewport"
      >
        <div>scroll content</div>
      </ScrollArea>
    );

    const viewport = screen.getByTestId('scroll-area-viewport');
    expect(viewport).toBeInTheDocument();
    expect(viewport).toHaveClass('inner-viewport');
    expect(viewport).toHaveTextContent('scroll content');
    expect(viewport.parentElement).toHaveClass('outer-shell');
  });
});
