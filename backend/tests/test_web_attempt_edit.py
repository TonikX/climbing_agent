"""Website edit flow uses the same owned, versioned mutations as Telegram."""
import unittest
from tests import test_auth_postgres as fixtures


class WebAttemptEditTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixtures.AuthPostgresTest.asyncSetUp
    asyncTearDown = fixtures.AuthPostgresTest.asyncTearDown
    login = fixtures.AuthPostgresTest.login

    async def test_completed_attempt_edit_normalization_replay_and_statistics(self):
        headers = await self.login('9911')
        saved = await self.client.post('/api/v1/web-attempts', headers=headers, json={
            'date': '2026-10-23', 'region': 'Гейкбаири', 'sector': 'Кебап', 'name': 'Engesh',
            'grade': '6A', 'reached_top': True, 'clean_ascent': False, 'style': 'with_hangs', 'hangs': 2,
            'belay': 'lead'})
        self.assertEqual(saved.status_code, 201, saved.text)
        tid, aid = saved.json()['trainingId'], saved.json()['attempt']['id']
        ended = await self.client.post(f'/api/v1/trainings/{tid}/finish', headers=headers, json={})
        version = ended.json()['version']
        body = dict(expected_version=version, name='Engesh corrected', grade='6а+', clean_ascent=True,
                    style='redpoint', hangs=0, falls=0, belay='top_rope', notes=None)
        keyed = {**headers, 'Idempotency-Key': 'attempt-edit-retry'}
        for _ in range(2):
            response = await self.client.patch(f'/api/v1/attempts/{aid}', headers=keyed, json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()['version'], version + 1)
        detail = (await self.client.get(f'/api/v1/trainings/{tid}', headers=headers)).json()
        self.assertEqual(detail['status'], 'completed')
        self.assertEqual(len(detail['attempts']), 1)
        attempt = detail['attempts'][0]
        self.assertEqual(attempt['route_snapshot']['grade'], '6A+')
        self.assertEqual(attempt['route_snapshot']['name'], 'Engesh corrected')
        self.assertTrue(attempt['clean_ascent'])
        self.assertTrue(attempt['reached_top'])
        self.assertEqual(attempt['belay'], 'top_rope')
        stats = await self.client.get('/api/v1/statistics/month?date_from=2026-10-01&date_to=2026-10-31', headers=headers)
        self.assertEqual(stats.status_code, 200, stats.text)
        self.assertEqual(stats.json()['completedRoutes'], 1)
        stale = await self.client.patch(f'/api/v1/attempts/{aid}', headers=headers, json=body)
        self.assertEqual(stale.status_code, 409)
        other = await self.login('9912')
        foreign = await self.client.patch(f'/api/v1/attempts/{aid}', headers=other,
            json=dict(expected_version=version+1, notes='Foreign'))
        self.assertEqual(foreign.status_code, 404)
        changed = await self.client.patch(f'/api/v1/attempts/{aid}', headers=headers,
            json=dict(expected_version=version+1, clean_ascent=True, falls=1, style='with_falls'))
        self.assertEqual(changed.status_code, 200, changed.text)
        detail = (await self.client.get(f'/api/v1/trainings/{tid}', headers=headers)).json()
        self.assertFalse(detail['attempts'][0]['clean_ascent'])
        self.assertEqual(detail['attempts'][0]['style'], 'with_falls')
