export function legacyTarget(path: string): string {
  const [pathname, query = ''] = path.replace(/^#/, '').split('?');
  const suffix = query ? '?' + query : '';
  if (pathname === '/bank') return '/bank.html';
  if (pathname === '/feed' || pathname === '/news') return '/dashboard' + suffix;
  if (/^\/feed\/[^/]+$/.test(pathname)) return '/news/' + pathname.slice(6) + suffix;
  if (pathname === '/onboarding') return '/register';
  if (pathname === '/company') {
    const params = new URLSearchParams(query); const tab = params.get('tab');
    if (!['roles', 'company', 'keywords', 'documents'].includes(tab ?? '')) params.set('tab', tab === 'analytics' ? 'company' : 'roles');
    return '/profile?' + params;
  }
  return /^\/(register|login|dashboard|news\/[^/]+|profile|landing)$/.test(pathname) ? pathname + suffix : '/';
}
