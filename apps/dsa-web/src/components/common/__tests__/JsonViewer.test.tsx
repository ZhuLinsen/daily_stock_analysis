import { render, screen } from '@testing-library/react';
import type React from 'react';
import { describe, expect, it } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { JsonViewer } from '../JsonViewer';

function renderJsonViewer(data: React.ComponentProps<typeof JsonViewer>['data']) {
  return render(
    <UiLanguageProvider>
      <JsonViewer data={data} />
    </UiLanguageProvider>,
  );
}

describe('JsonViewer', () => {
  it('renders html-like JSON strings as inert text', () => {
    const { container } = renderJsonViewer({
      payload: '<img src=x onerror="window.__jsonViewerXss = true">',
      nested: {
        script: '<script>window.__jsonViewerScript = true</script>',
      },
    });

    expect(container.textContent).toContain('<img src=x onerror=\\"window.__jsonViewerXss = true\\">');
    expect(container.textContent).toContain('<script>window.__jsonViewerScript = true</script>');
    expect(container.querySelector('img')).toBeNull();
    expect(container.querySelector('script')).toBeNull();
    expect(container.querySelector('[onerror]')).toBeNull();
  });

  it('keeps keys and values visually tokenized without injecting html', () => {
    renderJsonViewer({
      status: true,
      score: 82,
      note: 'ok',
    });

    expect(screen.getByText('"status"')).toHaveClass('text-cyan-400');
    expect(screen.getByText('true')).toHaveClass('text-purple-400');
    expect(screen.getByText('82')).toHaveClass('text-amber-400');
    expect(screen.getByText('"ok"')).toHaveClass('text-emerald-400');
  });
});
