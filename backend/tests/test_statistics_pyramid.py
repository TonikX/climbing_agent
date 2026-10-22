import unittest
from types import SimpleNamespace
from app.statistics_pyramid import bucket, counts, route_groups, dimensions
from app.tool_service import _grade_breakdown


def attempt(id, key, sequence, clean=False, style="with_falls", test=False, grade="6B"):
    return SimpleNamespace(id=id, route_session_key=key, sequence=sequence, clean_ascent=clean,
        reached_top=clean, style=style, is_test=test, attempts=2, belay="lead",
        route_snapshot={"grade":grade}, route=None)


class PyramidTest(unittest.TestCase):
    def test_styles_and_belays_are_independent_and_keep_failed_styles(self):
        values=[attempt("1","a",1,False,"with_falls"),
                attempt("2","b",2,False,"with_hangs"),
                attempt("3","c",3,True,"flash"),
                attempt("4","d",4,True,"top_rope")]
        values[2].belay="top_rope"
        result=dimensions(values)
        self.assertEqual(result['styles'],dict(onsight=0,flash=1,redpoint=0,with_falls=1,with_hangs=1,unknown=1))
        self.assertEqual(result['belays']['top_rope'],1)
        self.assertEqual(result['belays']['lead'],3)
        self.assertEqual(values[3].style,'top_rope')
    def test_buckets_are_disjoint_and_use_first_clean_ascent(self):
        values=[attempt("1","a",1),attempt("2","a",2,True,"redpoint"),
                attempt("3","a",3,True,"flash"),attempt("4","b",4,True,"flash"),
                attempt("5","c",5),attempt("6","test",6,True,"onsight",True),
                attempt("7","d",7,True,"top_rope"),attempt("8","e",8,True,"unknown")]
        result=counts(list(reversed(values)))
        self.assertEqual(result,dict(onsight=0,flash=1,redpoint=1,top_rope=1,other_clean=1,not_clean=1))
        dto=_grade_breakdown(values)[0]
        self.assertEqual(sum(dto["pyramid"].values()),dto["routesCount"])
        self.assertEqual(sum(v for k,v in dto["pyramid"].items() if k!="not_clean"),dto["completedRoutes"])

    def test_unknown_cleanliness_and_test_success_do_not_make_a_send(self):
        values=[attempt("1","a",1),attempt("2","a",2,True,"flash",True)]
        values[0].clean_ascent=None
        self.assertEqual(bucket(route_groups(values)[0]),"not_clean")

    def test_category_order_and_unknown_snapshot_are_preserved(self):
        values=[attempt("1","a",1,grade="6B"),attempt("2","b",2,grade="6B/6B+"),
                attempt("3","c",3,grade="6B+"),attempt("4","d",4,grade=None)]
        values[-1].route=SimpleNamespace(grade="8A")
        self.assertEqual([r["grade"] for r in _grade_breakdown(values)],
                         ["6B+","6B/6B+","6B","Без категории"])
