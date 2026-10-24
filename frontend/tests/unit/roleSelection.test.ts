import { describe, expect, it } from 'vitest';
import { resolveActiveRole } from '../../src/roleSelection';

describe('header role selection', () => {
  it('keeps a saved role only while it is assigned to the user', () => {
    expect(resolveActiveRole(['strategy', 'cfo'], 'cfo')).toBe('cfo');
    expect(resolveActiveRole(['strategy'], 'cfo')).toBe('strategy');
  });

  it('chooses the first assigned role for empty or invalid saved values without an all-roles mode', () => {
    expect(resolveActiveRole(['strategy', 'cfo'], '')).toBe('strategy');
    expect(resolveActiveRole(['procurement', 'operations'], 'unknown')).toBe('procurement');
    expect(resolveActiveRole(['new-server-role'], '')).toBe('new-server-role');
  });

  it('has no active role if the user has no assignments', () => {
    expect(resolveActiveRole([], '')).toBe('');
    expect(resolveActiveRole([], 'cfo')).toBe('');
  });
});
