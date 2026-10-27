"""Training edits preserve attempts and reject stale or foreign writes."""
import unittest
from sqlalchemy import select
from app.models import TrainingSession
from tests import test_auth_postgres as fixtures


class TrainingEditTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.AuthPostgresTest.asyncSetUp
    asyncTearDown = fixtures.AuthPostgresTest.asyncTearDown
    login = fixtures.AuthPostgresTest.login

    async def test_completed_training_edit_retry_conflict_and_clear(self):
        headers = await self.login('9901')
        created = await self.client.post('/api/v1/trainings', headers=headers,
            json={'date': '2026-10-01', 'environment': 'outdoor'})
        tid = created.json()['id']
        attempt = await self.client.post(f'/api/v1/trainings/{tid}/attempts', headers=headers,
            json={'name': 'Engesh', 'grade': '6A', 'reached_top': True, 'clean_ascent': True,
                  'style': 'flash', 'belay': 'lead'})
        self.assertEqual(attempt.status_code, 201, attempt.text)
        ended = await self.client.post(f'/api/v1/trainings/{tid}/finish', headers=headers, json={})
        version = ended.json()['version']
        body = {'expected_version': version, 'date': '2026-09-30', 'duration_minutes': 95,
                'notes': 'Заметка', 'physical_state': 'Хорошо', 'environment': 'indoor'}
        keyed = {**headers, 'Idempotency-Key': 'edit-retry'}
        first = await self.client.patch(f'/api/v1/trainings/{tid}', headers=keyed, json=body)
        self.assertEqual(first.status_code, 200, first.text)
        saved = first.json()
        self.assertEqual(saved['local_date'], '2026-09-30')
        self.assertEqual(saved['version'], version + 1)
        self.assertEqual(saved['status'], 'completed')
        self.assertEqual(saved['attempts'][0]['id'], attempt.json()['id'])
        retry = await self.client.patch(f'/api/v1/trainings/{tid}', headers=keyed, json=body)
        self.assertEqual(retry.json(), saved)
        stale = await self.client.patch(f'/api/v1/trainings/{tid}', headers=headers, json=body)
        self.assertEqual(stale.status_code, 409)
        cleared = await self.client.patch(f'/api/v1/trainings/{tid}', headers=headers,
            json={'expected_version': saved['version'], 'duration_minutes': None, 'notes': None})
        self.assertEqual(cleared.status_code, 200, cleared.text)
        self.assertIsNone(cleared.json()['notes'])
        self.assertIsNone(cleared.json()['duration_minutes'])
        self.assertEqual(cleared.json()['physical_state'], 'Хорошо')

    async def test_owner_boundary_invalid_fields_and_active_status(self):
        owner, other = await self.login('9902'), await self.login('9903')
        created = await self.client.post('/api/v1/trainings', headers=owner, json={'date': '2026-10-01'})
        tid, version = created.json()['id'], created.json()['version']
        for body in ({'date': None}, {'environment': None}, {'duration_minutes': 0}, {'status': 'completed'}):
            result = await self.client.patch(f'/api/v1/trainings/{tid}', headers=owner,
                json={'expected_version': version, **body})
            self.assertEqual(result.status_code, 422, result.text)
        foreign = await self.client.patch(f'/api/v1/trainings/{tid}', headers=other,
            json={'expected_version': version, 'notes': 'Foreign'})
        self.assertEqual(foreign.status_code, 404)
        anonymous = await self.client.patch(f'/api/v1/trainings/{tid}',
            json={'expected_version': version, 'notes': 'Anonymous'})
        self.assertEqual(anonymous.status_code, 401)
        updated = await self.client.patch(f'/api/v1/trainings/{tid}', headers=owner,
            json={'expected_version': version, 'date': '2026-09-29'})
        self.assertEqual(updated.status_code, 200, updated.text)
        self.assertEqual(updated.json()['status'], 'active')
        saved_date = await self.conn.scalar(select(TrainingSession.local_date).where(TrainingSession.id == tid))
        self.assertEqual(str(saved_date), '2026-09-29')
