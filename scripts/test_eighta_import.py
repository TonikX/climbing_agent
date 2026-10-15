import unittest
from eighta_import import plan,sql_for,normalize


def source(name='Route',crag='Küllüin',sector='Küllüin',slug='route'):
    return dict(country='Турция',area='Geyikbayırı',discipline='sportclimbing',crag=crag,
                crag_url='https://www.8a.nu/crags/sportclimbing/turkey/kulluin/routes',
                sector=sector,name=name,grade='6b',url='https://www.8a.nu/crags/sportclimbing/turkey/kulluin/sectors/kuelluein/routes/'+slug)


class EightaImportTest(unittest.TestCase):
    def existing(self,grade=''):
        return [dict(kind='section',id='section_old',name='Kulluin',parent_id='location_old',grade=''),
                dict(kind='route',id='route_old',name='Route',parent_id='section_old',grade=grade)]

    def test_existing_id_retained_and_only_null_grade_filled(self):
        result=plan([source()],self.existing())
        self.assertEqual(result['matched'],1)
        self.assertEqual(result['new_routes'],{})
        self.assertEqual(result['accepted'][0]['target_id'],'route_old')
        sql,_,_=sql_for(result,'x')
        self.assertIn('AND grade IS NULL',sql)
        self.assertNotIn('UPDATE route_attempts',sql)
        conflict=plan([source()],self.existing('6C'))
        self.assertEqual(len(conflict['grade_conflicts']),1)

    def test_duplicate_source_names_are_held_not_merged(self):
        result=plan([source(slug='one'),source(slug='two')],self.existing())
        self.assertEqual(len(result['pending']),2)
        self.assertEqual(result['accepted'],[])

    def test_turkish_spelling_normalized_and_other_context_rejected(self):
        self.assertEqual(normalize('Küllüin'),normalize('Kulluin'))
        row=source();row['area']='Elsewhere'
        with self.assertRaises(ValueError):plan([row],[])


if __name__=='__main__':unittest.main()
