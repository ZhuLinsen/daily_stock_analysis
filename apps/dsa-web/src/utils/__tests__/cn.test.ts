import { describe, it, expect } from 'vitest';
import { cn } from '../cn';

describe('cn utility', () => {
  it('should merge basic tailwind classes', () => {
    expect(cn('p-2 text-sm', 'p-4')).toBe('text-sm p-4');
    expect(cn('bg-red-500', 'bg-blue-500')).toBe('bg-blue-500');
  });

  it('should handle conditional classes', () => {
    const isTrue = true;
    const isFalse = false;
    expect(cn('base-class', isTrue && 'active-class', isFalse && 'hidden-class')).toBe('base-class active-class');
  });

  it('should preserve custom extracted component classes alongside utilities', () => {
    // Tests our Phase 0 extracted classes
    expect(cn('terminal-card border-subtle', 'border-primary/50')).toBe('terminal-card border-primary/50');
    expect(cn('glass-card p-4', 'p-6')).toBe('glass-card p-6');
    expect(cn('btn-primary bg-blue-500', 'bg-red-500')).toBe('btn-primary bg-red-500');
  });

  it('should handle undefined and null gracefully', () => {
    expect(cn('base', undefined, null, '', 'extra')).toBe('base extra');
  });
});
