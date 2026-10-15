"""Real PostgreSQL search and deterministic Telegram catalogue resolution."""
import unittest
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

import test_public_service as journal_tests
from app.models import CatalogAlias, Location, Section, Route, RouteAttempt, TrainingSession, ExternalRef
from app.public_models import DialogState, Job
from app.public_schemas import Intent


class CatalogSearchTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = journal_tests.PublicServiceTest.asyncSetUp
    asyncTearDown = journal_tests.PublicServiceTest.asyncTearDown
    asyncSetUpBase = journal_tests.PublicServiceTest.asyncSetUpBase
    asyncTearDownBase = journal_tests.PublicServiceTest.asyncTearDownBase
    login = journal_tests.PublicServiceTest.login
    send = journal_tests.PublicServiceTest.send
    process = journal_tests.PublicServiceTest.process
    approve_new_catalog = False

    async def seed(self):
        self.a, self.b = await self.login("2"), await self.login("3")
        async with AsyncSession(bind=self.conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            self.uid = await session.scalar(select(ExternalRef.user_id).where(ExternalRef.external_id=="2"))
            other_uid = await session.scalar(select(ExternalRef.user_id).where(ExternalRef.external_id=="3"))
            self.area = Location(name="Geyikbayırı", type="outdoor", visibility="public", country="TR")
            self.hidden = Location(name="Secret location", type="outdoor", owner_id=other_uid, visibility="private")
            session.add_all([self.area, self.hidden])
            await session.flush()
            self.sector = Section(name="Kebap", location_id=self.area.id, type="sector")
            another = Section(name="Other", location_id=self.area.id, type="sector")
            session.add_all([self.sector, another])
            await session.flush()
            self.route = Route(name="Engesh", grade="6A", section_id=self.sector.id)
            self.outside = Route(name="Outside only", grade="7A", section_id=another.id)
            session.add_all([self.route,self.outside])
            await session.commit()

    async def draft(self):
        return await self.conn.scalar(select(DialogState.data).where(DialogState.user_id==self.uid))

    async def choose(self, prefix, suffix=""):
        data = await self.draft()
        await self.send("2", prefix+":"+data["selection"]["token"]+suffix, True)
        await self.process()

    async def test_indexed_query_for_each_level(self):
        await self.seed()
        from app.catalog_search import search
        async with AsyncSession(bind=self.conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            for kind, name, parent, expected in (("locations","Geyikbayiri",None,self.area.id),
                ("sections","Kebap",self.area.id,self.sector.id),("routes","Engesh",self.sector.id,self.route.id)):
                result=await search(session,self.uid,kind,name,parent)
                self.assertEqual(result["items"][0]["id"],expected)

    async def test_search_alias_privacy_typo_parent_and_exact_shared_reuse(self):
        await self.seed()
        result = await self.client.get("/api/v1/catalog-search/locations", headers=self.a, params={"q":"GEYIKBAYIRI"})
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()["items"][0]["id"],self.area.id)
        self.assertEqual(result.json()["items"][0]["match"],"exact")
        self.assertEqual((await self.client.get("/api/v1/catalog-search/locations",headers=self.a,params={"q":"Secret location"})).json()["items"],[])
        alias = await self.client.post(f"/api/v1/catalog-aliases/locations/{self.area.id}",headers=self.a,json={"name":"Гейкбаири"})
        self.assertEqual(alias.status_code,200,alias.text)
        found=(await self.client.get("/api/v1/catalog-search/locations",headers=self.a,params={"q":"Гейкбаири"})).json()["items"]
        self.assertEqual(found[0]["match"],"exact")
        self.assertEqual((await self.client.get("/api/v1/catalog-search/locations",headers=self.b,params={"q":"Гейкбаири"})).json()["items"],[])
        denied=await self.client.post(f"/api/v1/catalog-aliases/locations/{self.hidden.id}",headers=self.a,json={"name":"leak"})
        self.assertEqual(denied.status_code,404)
        fuzzy=(await self.client.get("/api/v1/catalog-search/routes",headers=self.a,params={"q":"Engeshh","parent_id":self.sector.id})).json()["items"]
        self.assertEqual(fuzzy[0]["id"],self.route.id)
        self.assertEqual(fuzzy[0]["match"],"similar")
        self.assertEqual((await self.client.get("/api/v1/catalog-search/routes",headers=self.a,params={"q":"Outside only","parent_id":self.sector.id})).json()["items"],[])
        existing=await self.client.post("/api/v1/catalog/locations",headers=self.a,json={"name":"Гейкбаири"})
        self.assertEqual(existing.json()["id"],self.area.id)

    async def test_voice_fuzzy_choice_grade_disagreement_and_stale_button(self):
        await self.seed()
        await self.client.post("/api/v1/trainings",headers=self.a,json={"date":"2026-10-15"})
        await self.send("2","",voice=True)
        await self.process("ai", Intent(kind="attempt",region="Geyikbayiri",sector="Kebap",name="Engeshh",
            grade="6B",style="flash",belay="lead"))
        data = await self.draft()
        self.assertEqual(data["selection"]["ids"],[self.route.id])
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),0)
        old = "cs:"+data["selection"]["token"]+":0"
        await self.choose("cs",":0")
        self.assertEqual((await self.draft())["selection"]["field"],"grade")
        await self.send("2",old,True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),0)
        await self.choose("cg",":db")
        row=(await self.conn.execute(select(RouteAttempt.route_id,RouteAttempt.route_snapshot,RouteAttempt.clean_ascent))).one()
        self.assertEqual(row.route_id,self.route.id)
        self.assertEqual(row.route_snapshot["grade"],"6A")
        self.assertTrue(row.clean_ascent)
        self.assertEqual(await self.conn.scalar(select(func.count(Location.id))),2)
        self.assertEqual(await self.conn.scalar(select(func.count(Route.id))),2)
        self.assertEqual(await self.conn.scalar(select(func.count(CatalogAlias.id))),1)

    async def test_button_browse_manual_result_has_no_ai_calls(self):
        await self.seed()
        await self.client.post("/api/v1/trainings",headers=self.a,json={"date":"2026-10-15"})
        await self.send("2","training:location",True)
        await self.process()
        await self.send("2","Geyikbayiri")
        await self.process()
        await self.choose("cs",":0")
        data = await self.draft()
        position=data["selection"]["ids"].index(self.sector.id)
        await self.choose("cs",":"+str(position))
        self.assertEqual(await self.conn.scalar(select(TrainingSession.primary_location_id)),self.area.id)
        await self.send("2","catalog:choose",True)
        await self.process()
        await self.choose("cs",":0")
        data=await self.draft()
        await self.choose("cs",":"+str(data["selection"]["ids"].index(self.sector.id)))
        await self.choose("cs",":0")
        await self.send("2","catalog:manual",True)
        await self.process()
        for value in ("form:lead","form:yes","form:flash","form:yes","0","0"):
            await self.send("2",value,value.startswith("form:"))
            await self.process()
        self.assertEqual(await self.conn.scalar(select(RouteAttempt.route_id)),self.route.id)
        self.assertEqual(await self.conn.scalar(select(func.count(Job.id)).where(Job.lane=="ai")),0)
        self.assertIsNone(await self.draft())

    async def test_missing_route_requires_explicit_private_creation(self):
        await self.seed()
        await self.client.post("/api/v1/trainings",headers=self.a,json={"date":"2026-10-15"})
        await self.send("2","Brandnew 6A flash")
        await self.process("ai",Intent(kind="attempt",region="Geyikbayiri",sector="Kebap",name="Brandnew",
            grade="6A",style="flash",belay="lead"))
        self.assertEqual(await self.conn.scalar(select(func.count(Route.id))),2)
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),0)
        await self.choose("cn")
        row=(await self.conn.execute(select(RouteAttempt.route_snapshot,RouteAttempt.route_id))).one()
        self.assertNotEqual(row.route_snapshot["areaId"],self.area.id)
        self.assertEqual(await self.conn.scalar(select(Location.owner_id).where(Location.id==row.route_snapshot["areaId"])),self.uid)
        self.assertEqual(await self.conn.scalar(select(func.count(Route.id)).where(Route.section_id==self.sector.id)),1)
        self.assertIsNotNone(row.route_id)

    async def test_duplicate_exact_names_require_selection(self):
        await self.seed()
        async with AsyncSession(bind=self.conn, join_transaction_mode="create_savepoint") as session:
            session.add(Location(name="Geyikbayırı",type="outdoor",visibility="public",country="RU"))
            await session.commit()
        await self.client.post("/api/v1/trainings",headers=self.a,json={"date":"2026-10-15"})
        await self.send("2","Geyikbayiri Kebap Engesh flash")
        await self.process("ai",Intent(kind="attempt",region="Geyikbayiri",sector="Kebap",name="Engesh",style="flash",belay="lead"))
        data=await self.draft()
        self.assertEqual(data["selection"]["field"],"region")
        self.assertEqual(len(data["selection"]["ids"]),2)
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),0)
        token=data["selection"]["token"]
        await self.send("2",f"cs:{token}:99",True)
        await self.process()
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))),0)
        await self.choose("cs",":"+str(data["selection"]["ids"].index(self.area.id)))
        self.assertEqual(await self.conn.scalar(select(RouteAttempt.route_id)),self.route.id)
