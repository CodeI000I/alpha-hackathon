import { describe, expect, it } from 'vitest';
import { legacyTarget } from '../../src/legacyRoutes';

describe('legacy route migration', () => {
  it.each([
    ['/feed', '/dashboard'],
    ['/news', '/dashboard'],
    ['#/feed', '/dashboard'],
    ['#/feed?role=cfo', '/dashboard?role=cfo'],
    ['/feed/101', '/news/101'],
    ['#/feed/101?saved=1', '/news/101?saved=1'],
    ['/bank', '/bank.html'],
    ['#/bank', '/bank.html'],
    ['/onboarding', '/register'],
  ])('maps %s to %s', (input, expected) => {
    expect(legacyTarget(input)).toBe(expected);
  });

  it.each([
    ['/company', '/profile?tab=roles'],
    ['/company?tab=summary', '/profile?tab=roles'],
    ['/company?tab=analytics', '/profile?tab=company'],
    ['/company?tab=roles', '/profile?tab=roles'],
    ['/company?tab=company', '/profile?tab=company'],
    ['/company?tab=keywords', '/profile?tab=keywords'],
    ['/company?tab=documents', '/profile?tab=documents'],
    ['/company?tab=unknown&from=old', '/profile?tab=roles&from=old'],
  ])('translates the old company tab %s', (input, expected) => {
    expect(legacyTarget(input)).toBe(expected);
  });

  it.each([
    ['/register', '/register'],
    ['/login', '/login'],
    ['/dashboard?role=cfo', '/dashboard?role=cfo'],
    ['/news/202', '/news/202'],
    ['/profile?tab=documents', '/profile?tab=documents'],
    ['/landing', '/landing'],
  ])('keeps current routes intact: %s', (input, expected) => {
    expect(legacyTarget(input)).toBe(expected);
  });

  it.each(['', '/', '/unknown', '/feed/', '/news/1/extra', '#/missing'])('falls back safely for %s', (input) => {
    expect(legacyTarget(input)).toBe('/');
  });
});
