import json
import unittest
from pathlib import Path

import httpx

from scripts.seed_demo_profiles import DemoProfileSeeder, validate_base_url


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'fixtures' / 'miro-personas'


def response(request, status, payload=None, headers=None):
    return httpx.Response(status, json=payload, headers=headers, request=request)


class DemoProfileSeederTests(unittest.TestCase):
    def test_base_url_requires_literal_loopback_origin_without_extras(self):
        self.assertEqual(validate_base_url('http://127.0.0.1:8080'), 'http://127.0.0.1:8080')
        self.assertEqual(validate_base_url('http://[::1]:8080'), 'http://[::1]:8080')
        for value in (
            'https://localhost:8080',
            'http://localhost:8080',
            'http://127.0.0.1:8080/path',
            'http://127.0.0.1:8080/?x=1',
            'http://127.0.0.1:8080?',
            'http://127.0.0.1:8080/#fragment',
            'http://127.0.0.1:8080#',
            'http://user:pass@127.0.0.1:8080',
            'http://192.0.2.1:8080',
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_base_url(value)

    def test_first_run_onboards_then_rerun_skips_matching_profile_and_documents(self):
        registration = json.loads((FIXTURES / 'x5' / 'registration.json').read_text())
        profile = json.loads((FIXTURES / 'x5' / 'profile.json').read_text())
        files = sorted((FIXTURES / 'x5' / 'documents').glob('*.txt'))
        company = {'id': 21, 'inn': registration['company']['inn'], 'name': registration['company']['name'], 'profile': {}}
        user = {'id': 42, 'companyId': 21, **registration['user']}
        onboarded = False
        existing_files = []
        next_upload = iter(files)
        writes = []
        observed_null_collection = False

        def handler(request):
            nonlocal onboarded, observed_null_collection
            if request.url.path == '/api/v1/auth/login':
                if not onboarded:
                    return response(request, 401, {'error': 'not registered'})
                return response(request, 200, user, {'Set-Cookie': 'alpha_session=session; Path=/'})
            if request.url.path == '/api/v1/onboarding':
                onboarded = True
                return response(request, 201, {'company': company, 'user': user},
                                {'Set-Cookie': 'alpha_session=session; Path=/'})
            if request.url.path == '/api/v1/auth/me':
                self.assertTrue(onboarded)
                return response(request, 200, user)
            if request.url.path == '/api/v1/companies/21':
                return response(request, 200, company)
            if request.method == 'PATCH' and request.url.path == '/api/v1/companies/21/profile':
                company['profile'].update(json.loads(request.content))
                writes.append('profile')
                return response(request, 200, company)
            if request.url.path == '/api/v1/companies/21/files':
                if request.method == 'GET':
                    if not existing_files:
                        observed_null_collection = True
                        return response(request, 200, None)
                    return response(request, 200, existing_files)
                path = next(next_upload)
                existing_files.append({'filename': path.name, 'sizeBytes': path.stat().st_size, 'contentType': 'text/plain'})
                writes.append(path.name)
                return response(request, 201, {'filename': path.name})
            self.fail(f'unexpected state-changing request on rerun: {request.method} {request.url}')

        with httpx.Client(transport=httpx.MockTransport(handler), trust_env=True, follow_redirects=True) as client:
            seeder = DemoProfileSeeder(FIXTURES, 'http://127.0.0.1:8080', client)
            first = seeder.seed('x5')
            writes_after_first_run = len(writes)
            result = seeder.seed('x5')

        self.assertEqual(first, {'profile_updated': True, 'uploaded': 4})
        self.assertEqual(result, {'profile_updated': False, 'uploaded': 0})
        self.assertEqual(len(existing_files), len(files))
        self.assertEqual(company['profile'], profile)
        self.assertEqual(len(writes), writes_after_first_run)
        self.assertTrue(observed_null_collection)

    def test_wrong_file_collection_envelope_is_rejected(self):
        registration = json.loads((FIXTURES / 'x5' / 'registration.json').read_text())
        user = {'id': 42, 'companyId': 21, **registration['user']}
        company = {'id': 21, **registration['company'], 'profile': json.loads((FIXTURES / 'x5' / 'profile.json').read_text())}

        def handler(request):
            if request.url.path == '/api/v1/auth/login':
                return response(request, 200, user, {'Set-Cookie': 'alpha_session=session; Path=/'})
            if request.url.path == '/api/v1/auth/me':
                return response(request, 200, user)
            if request.url.path == '/api/v1/companies/21':
                return response(request, 200, company)
            if request.url.path == '/api/v1/companies/21/files':
                return response(request, 200, {'items': []})
            self.fail(f'unexpected request: {request.method} {request.url}')

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            seeder = DemoProfileSeeder(FIXTURES, 'http://127.0.0.1:8080', client)
            with self.assertRaisesRegex(RuntimeError, 'unexpected response'):
                seeder.seed('x5')

    def test_company_mismatch_is_rejected_before_profile_or_document_writes(self):
        registration = json.loads((FIXTURES / 'x5' / 'registration.json').read_text())
        user = {'id': 42, 'companyId': 21, **registration['user']}
        mismatched_company = {'id': 21, 'inn': '0000009999', 'name': 'Different company', 'profile': {}}
        writes = []

        def handler(request):
            if request.url.path == '/api/v1/auth/login':
                return response(request, 200, user, {'Set-Cookie': 'alpha_session=session; Path=/'})
            if request.url.path == '/api/v1/auth/me':
                return response(request, 200, user)
            if request.url.path == '/api/v1/companies/21':
                return response(request, 200, mismatched_company)
            if request.method in {'PATCH', 'POST'}:
                writes.append(request.url.path)
            self.fail(f'unexpected request: {request.method} {request.url}')

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            seeder = DemoProfileSeeder(FIXTURES, 'http://127.0.0.1:8080', client)
            with self.assertRaisesRegex(RuntimeError, 'exact synthetic fixture company'):
                seeder.seed('x5')

        self.assertEqual(writes, [])

    def test_failed_login_and_onboarding_are_reported(self):
        paths = []

        def handler(request):
            paths.append(request.url.path)
            status = 401 if request.url.path.endswith('/auth/login') else 401
            return response(request, status, {'error': 'bad credentials'})

        with httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True) as client:
            seeder = DemoProfileSeeder(FIXTURES, 'http://127.0.0.1:8080', client)
            with self.assertRaisesRegex(RuntimeError, 'login/onboarding failed'):
                seeder.seed('x5')

        self.assertEqual(paths, ['/api/v1/auth/login', '/api/v1/onboarding'])

    def test_redirect_is_rejected_without_following_target(self):
        targets = []

        def handler(request):
            targets.append(str(request.url))
            return response(request, 302, headers={'Location': 'http://192.0.2.99/steal'})

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            seeder = DemoProfileSeeder(FIXTURES, 'http://127.0.0.1:8080', client)
            with self.assertRaisesRegex(RuntimeError, 'redirect'):
                seeder.seed('x5')

        self.assertEqual(targets, ['http://127.0.0.1:8080/api/v1/auth/login'])


if __name__ == '__main__':
    unittest.main()
