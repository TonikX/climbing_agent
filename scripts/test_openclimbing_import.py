import unittest
from openclimbing_import import collect, make_sql


def feature(kind, osm_type, osm_id, name, parent=None, **extra):
    return dict(type=kind,osmType=osm_type,osmId=osm_id,name=name,nameRaw=None,
                parentId=parent,countryCode="tr",lat=36.87,lon=30.48,
                tags="{}",members="[]",gradeTxt=None,**extra)


class OpenClimbingTest(unittest.TestCase):
    def test_parent_is_osm_relation_id_not_export_row_id_and_anchor_is_not_extra_sector(self):
        area=feature("area","relation",10,"Area")
        sector=feature("crag","relation",20,"Sector",10)
        sector["members"]='[{"type":"node","ref":30,"role":""}]'
        anchor=feature("crag","node",30,"Sector",20)
        route=feature("route","node",40,"Route",20)
        route["tags"]='{"climbing:grade:french":"6b+"}'
        rows,skips,aliases=collect([area,sector,anchor,route])
        self.assertEqual(len(rows),3)
        self.assertEqual(rows['route:node/40']['parent'],'section:relation/20')
        self.assertEqual(rows['route:node/40']['grade'],'6B+')
        self.assertEqual(aliases,{'node/30':'relation/20'})
        self.assertEqual(skips,[])

    def test_uiaa_orphan_and_cross_country_rows_do_not_create_false_data(self):
        area=feature("area","relation",10,"Area")
        sector=feature("crag","relation",20,"Sector",10)
        route=feature("route","node",40,"Route",20)
        route.update(gradeTxt="VII",tags='{"climbing:grade:uiaa":"VII"}')
        orphan=feature("route","node",50,"Orphan")
        foreign=feature("route","node",60,"Foreign",20)
        foreign["countryCode"]="ru"
        records,skips,_=collect([area,sector,route,orphan,foreign])
        self.assertEqual(records['route:node/40']['grade'],'')
        self.assertEqual(records['route:node/40']['raw_grade'],'VII')
        self.assertNotIn('route:node/50',records)
        self.assertNotIn('route:node/60',records)
        self.assertEqual(len(skips),2)

    def test_plan_has_public_guards_stable_ids_and_no_journal_mutations(self):
        rows,_,_=collect([feature('area','relation',10,"It's an area")])
        sql=make_sql(rows,{'location:relation/10':'location_existing'})
        self.assertIn("visibility='public' AND owner_id IS NULL",sql)
        self.assertIn("openstreetmap",sql)
        self.assertNotIn("route_attempts",sql)
        self.assertNotIn("UPDATE ",sql)
        self.assertEqual(sql,make_sql(rows,{'location:relation/10':'location_existing'}))
        plain=make_sql(rows,{})
        self.assertIn("It''s an area",plain)


if __name__ == '__main__':
    unittest.main()
