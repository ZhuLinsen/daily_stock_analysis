import { describe, expect, it } from 'vitest';
import { isNearBottom } from '../chatScroll';

describe('isNearBottom', () => {
  it('returns true when the viewport is within the default threshold', () => {
    expect(
      isNearBottom({
        scrollTop: 604,
        clientHeight: 320,
        scrollHeight: 1000,
      }),
    ).toBe(true);
  });

  it('returns false when the viewport is far from the bottom', () => {
    expect(
      isNearBottom({
        scrollTop: 240,
        clientHeight: 320,
        scrollHeight: 1000,
      }),
    ).toBe(false);
  });
});
