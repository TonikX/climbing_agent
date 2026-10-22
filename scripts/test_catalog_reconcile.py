import unittest
from catalog_reconcile import choose_route, immutable, fingerprint


class ReconcileTest(unittest.TestCase):
    def test_unique_grade_and_reviewed_spelling(self):
        target = {'id':'public', 'name':'Revolverheld', 'grade':'6A+'}
        chosen, _ = choose_route({'name':'revolverheld','grade':'6а+'}, [target], ['6a+'])
        self.assertEqual(chosen['id'], 'public')
        target = {'id':'public','name':'Эпоксипропокси','grade':'6B+'}
        self.assertEqual(choose_route({'name':'Epoxy Propoxy','grade':'6B+'},[target],[])[0]['id'], 'public')

    def test_conflicting_history_and_multiple_destinations_are_not_merged(self):
        target = {'id':'public','name':'Братское сердце','grade':'5B/5C'}
        self.assertEqual(choose_route({'name':'Братское сердце','grade':None}, [target], ['6B'])[1], 'grade_conflict')
        target = {'id':'public','name':'Same','grade':'6A'}
        self.assertEqual(choose_route({'name':'Same','grade':'6A'},[target,{**target,'id':'second'}],[])[1], 'ambiguous_name')
        self.assertIsNone(choose_route({'name':'Maja','grade':'6A+'},[{'name':'Maja P1','grade':'6A+'}],[])[0])

    def test_immutable_check_keeps_attempt_groups_results_and_snapshot_grade(self):
        before = {'trainings':[{'id':'t','version':1,'primary_location_id':'private','local_date':'2026-10-22'}],
                  'attempts':[{'id':'a','route_id':'private','route_session_key':'same-group','is_test':True,
                               'clean_ascent':False,'route_snapshot':{'name':'old','grade':'6A','sectorId':'private'}}]}
        after = {'trainings':[dict(before['trainings'][0],version=2,primary_location_id='public')],
                 'attempts':[dict(before['attempts'][0],route_id='public',route_snapshot={'name':'new','grade':'6A','sectorId':'public'})]}
        self.assertEqual(fingerprint(immutable(before)), fingerprint(immutable(after)))
        after['attempts'][0]['route_snapshot']['grade'] = '6B'
        self.assertNotEqual(fingerprint(immutable(before)), fingerprint(immutable(after)))


if __name__ == '__main__':
    unittest.main()
