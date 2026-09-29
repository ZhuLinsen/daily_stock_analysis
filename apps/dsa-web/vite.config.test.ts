// @vitest-environment node

import { describe, expect, it } from 'vitest'

import { resolveAppRevision } from './vite.config'

describe('resolveAppRevision', () => {
  it('prefers the explicitly injected release revision', () => {
    expect(resolveAppRevision({
      explicitRevision: 'release123456',
      checkedOutRevision: 'checkedout123',
      workflowRevision: 'workflow12345',
    })).toBe('release123456')
  })

  it('uses the checked-out revision before the workflow trigger revision', () => {
    expect(resolveAppRevision({
      checkedOutRevision: 'oldtag123456',
      workflowRevision: 'defaultbranch',
    })).toBe('oldtag123456')
  })

  it('falls back when the build has no Git checkout', () => {
    expect(resolveAppRevision({
      workflowRevision: 'workflow12345',
    })).toBe('workflow12345')
    expect(resolveAppRevision({})).toBe('unknown')
  })
})
