"""Load the repository's synthetic Miro personas into a loopback demo API."""

from __future__ import annotations

import argparse
import ipaddress
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PERSONAS = ('x5', 'rzd')
PERSONAS = ('beeline', 'x5', 'rzd', 'etalon')


def validate_base_url(value: str) -> str:
    """Accept only an HTTP(S) origin whose host is a literal loopback IP."""
    try:
        parsed = urlsplit(value)
        if '?' in value or '#' in value or '%' in (parsed.hostname or ''):
            raise ValueError('query strings, fragments, and scoped IP addresses are not allowed')
        address = ipaddress.ip_address(parsed.hostname or '')
        port = parsed.port
    except ValueError as exc:
        raise ValueError('base URL must use a literal loopback IP address') from exc
    if (parsed.scheme not in {'http', 'https'} or not address.is_loopback
            or parsed.username is not None or parsed.password is not None
            or parsed.query or parsed.fragment or parsed.path not in {'', '/'}):
        raise ValueError('base URL must be a loopback HTTP(S) origin without credentials, path, query, or fragment')
    if port is not None and not 1 <= port <= 65535:
        raise ValueError('base URL port must be between 1 and 65535')
    return f'{parsed.scheme}://{parsed.netloc}'


class DemoProfileSeeder:
    def __init__(self, fixtures_dir: Path, base_url: str, client: httpx.Client):
        self.fixtures_dir = Path(fixtures_dir)
        self.base_url = validate_base_url(base_url)
        self.client = client

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self.client.request(method, self.base_url + path, follow_redirects=False, **kwargs)
        if 300 <= response.status_code < 400:
            raise RuntimeError(f'{method} {path} returned a redirect; redirects are not followed')
        return response

    @staticmethod
    def _expect(response: httpx.Response, statuses: set[int], action: str) -> dict[str, Any] | list[Any] | None:
        if response.status_code not in statuses:
            detail = response.text[:500]
            raise RuntimeError(f'{action} failed ({response.status_code}): {detail}')
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _fixture(self, persona: str) -> tuple[dict[str, Any], str, dict[str, Any], dict[str, Any]]:
        if persona not in PERSONAS:
            raise ValueError(f'unknown persona {persona!r}; choose from {", ".join(PERSONAS)}')
        registration = json.loads((self.fixtures_dir / persona / 'registration.json').read_text())
        requests = json.loads((self.fixtures_dir / 'registration-requests.json').read_text())
        candidates = [item for item in requests if item.get('persona') == persona]
        if len(candidates) != 1:
            raise ValueError(f'expected one registration request for {persona}')
        account = candidates[0]
        request_company = account['company']
        request_user = {key: value for key, value in account['user'].items() if key != 'password'}
        if request_company != registration['company'] or request_user != registration['user']:
            raise ValueError(f'{persona} registration files disagree about company or user')
        profile = json.loads((self.fixtures_dir / persona / 'profile.json').read_text())
        return registration, account['user']['password'], profile, registration['company']

    def _sign_in(self, persona: str, registration: dict[str, Any], password: str) -> dict[str, Any]:
        origin = {'Origin': self.base_url}
        login = self._request('POST', '/api/v1/auth/login', headers=origin,
                              json={'email': registration['user']['email'], 'password': password})
        if login.status_code == 401:
            payload = {'company': registration['company'], 'user': {**registration['user'], 'password': password}}
            # Stable across retries; backend validates the original password on replays.
            key = f'demo-persona-{persona}-v1'
            onboard = self._request('POST', '/api/v1/onboarding', headers={**origin, 'Idempotency-Key': key}, json=payload)
            if onboard.status_code not in {200, 201}:
                raise RuntimeError(f'login/onboarding failed ({login.status_code}/{onboard.status_code}); '
                                   'the fixture account may have a different password or company identity')
        elif login.status_code != 200:
            self._expect(login, {200}, 'login')
        current_response = self._request('GET', '/api/v1/auth/me')
        current = self._expect(current_response, {200}, 'read signed-in user')
        if not isinstance(current, dict):
            raise RuntimeError('auth/me returned an unexpected response')
        expected = registration['user']
        company_id = current.get('companyId')
        if (current.get('email', '').lower() != expected['email'].lower()
                or current.get('fullName') != expected['fullName']
                or set(current.get('roles') or []) != set(expected['roles'])
                or not isinstance(company_id, int)):
            raise RuntimeError(f'{persona} login belongs to a different fixture account; refusing to seed it')
        return current

    def seed(self, persona: str) -> dict[str, int]:
        registration, password, profile, expected_company = self._fixture(persona)
        user = self._sign_in(persona, registration, password)
        company_id = user['companyId']
        company_response = self._request('GET', f'/api/v1/companies/{company_id}')
        company = self._expect(company_response, {200}, 'read company')
        if not isinstance(company, dict) or company.get('inn') != expected_company['inn'] or company.get('name') != expected_company['name']:
            raise RuntimeError(f'{persona} account is not attached to the exact synthetic fixture company; refusing to seed it')

        current_profile = company.get('profile') or {}
        patch = {key: value for key, value in profile.items() if current_profile.get(key) != value}
        if patch:
            profile_response = self._request('PATCH', f'/api/v1/companies/{company_id}/profile',
                                             headers={'Origin': self.base_url}, json=patch)
            self._expect(profile_response, {200}, 'update company profile')

        files_response = self._request('GET', f'/api/v1/companies/{company_id}/files')
        current_files = self._expect(files_response, {200}, 'list company files')
        if current_files is None:
            current_files = []
        elif not isinstance(current_files, list):
            raise RuntimeError('company files endpoint returned an unexpected response')
        uploaded = 0
        for path in sorted((self.fixtures_dir / persona / 'documents').glob('*.txt')):
            size = path.stat().st_size
            matches = [item for item in current_files if item.get('filename') == path.name]
            if matches:
                if any(item.get('sizeBytes') != size or item.get('contentType') != 'text/plain' for item in matches):
                    raise RuntimeError(f'existing {path.name} does not match the fixture metadata; refusing duplicate upload')
                continue
            with path.open('rb') as content:
                response = self._request('POST', f'/api/v1/companies/{company_id}/files',
                                         headers={'Origin': self.base_url},
                                         files={'file': (path.name, content, 'text/plain')})
            self._expect(response, {201}, f'upload {path.name}')
            current_files.append({'filename': path.name, 'sizeBytes': size, 'contentType': 'text/plain'})
            uploaded += 1
        return {'profile_updated': bool(patch), 'uploaded': uploaded}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Load existing synthetic Miro personas into a loopback demo API.')
    parser.add_argument('--base-url', required=True, help='HTTP(S) origin such as http://127.0.0.1:8080')
    parser.add_argument('--personas', nargs='+', choices=PERSONAS, default=list(DEFAULT_PERSONAS),
                        help='persona fixtures to load (default: x5 rzd)')
    args = parser.parse_args(argv)
    base_url = validate_base_url(args.base_url)
    fixtures_dir = ROOT / 'fixtures' / 'miro-personas'
    with httpx.Client(trust_env=False, follow_redirects=False, timeout=20) as client:
        seeder = DemoProfileSeeder(fixtures_dir, base_url, client)
        for persona in args.personas:
            result = seeder.seed(persona)
            print(f'{persona}: profile {"updated" if result["profile_updated"] else "already matches"}; '
                  f'{result["uploaded"]} document(s) uploaded. Upload queues backend analysis; this script does not verify completion.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
