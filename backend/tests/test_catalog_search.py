"""Real PostgreSQL search and deterministic Telegram catalogue resolution."""
import unittest
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

import test_public_service as journal_tests
from app.models import CatalogAlias, Location, Section, Route, RouteAttempt, TrainingSession, ExternalRef
from app.public_models import DialogState, Job, Outbox
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
                self.assertEqual(await session.scalar(text("SHOW jit")),"off")

    async def test_transliteration_and_language_fields_keep_parent_scope(self):
        await self.seed()
        async with AsyncSession(bind=self.conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            sector = await session.get(Section, self.sector.id)
            sector.name = "Кебап"
            route = await session.get(Route, self.route.id)
            route.name, route.name_native, route.name_en = "Лунная река", "Лунная река", "Moon River"
            await session.commit()
        for kind, query, parent, expected, match in (
            ("sections", "Kebap", self.area.id, self.sector.id, "similar"),
            ("routes", "Lunnaya reka", self.sector.id, self.route.id, "similar"),
            ("routes", "Lunnaia reka", self.sector.id, self.route.id, "similar"),
            ("routes", "Moon River", self.sector.id, self.route.id, "exact"),
            ("routes", "ЛУННАЯ РЕКА", self.sector.id, self.route.id, "exact")):
            response = await self.client.get("/api/v1/catalog-search/"+kind, headers=self.a,
                params={"q":query,"parent_id":parent})
            self.assertEqual(response.status_code,200,response.text)
            item = next(x for x in response.json()["items"] if x["id"] == expected)
            self.assertEqual(item["match"],match)
        hidden = await self.client.get("/api/v1/catalog-search/locations", headers=self.a,
            params={"q":"Секрет локатион"})
        self.assertNotIn(self.hidden.id, [x["id"] for x in hidden.json()["items"]])
        outside = await self.client.get("/api/v1/catalog-search/routes", headers=self.a,
            params={"q":"Outside only","parent_id":self.sector.id})
        self.assertEqual(outside.json()["items"], [])

    async def test_turkish_names_ascii_and_cyrillic_suggestions(self):
        await self.seed()
        async with AsyncSession(bind=self.conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            sector = await session.get(Section, self.sector.id)
            sector.name, sector.name_native = "Mağara", "Mağara"
            route = await session.get(Route, self.route.id)
            route.name, route.name_native = "Şeker Çocuk", "Şeker Çocuk"
            route.name_en = "İncir Özü"
            short = Route(name="Can", section_id=self.sector.id, grade="6A")
            session.add(short)
            await session.flush()
            short_id = short.id
            await session.commit()
        for kind, queries, parent, expected in (
            ("locations", ("Geyikbayiri", "Гейкбаири"), None, self.area.id),
            ("sections", ("MAGARA", "Магара", "Mağara"), self.area.id, self.sector.id),
            ("routes", ("Seker Cocuk", "Sheker Chocuk", "Шекер Чоджук", "ŞEKER ÇOCUK",
                        "İNCİR ÖZÜ", "Incir Ozu", "Инджир Озю"), self.sector.id, self.route.id),
            ("routes", ("Can", "Джан"), self.sector.id, short_id)):
            for query in queries:
                params = {"q": query}
                if parent:
                    params["parent_id"] = parent
                response = await self.client.get("/api/v1/catalog-search/"+kind, headers=self.a, params=params)
                self.assertEqual(response.status_code, 200, response.text)
                self.assertIn(expected, [item["id"] for item in response.json()["items"]], query)

    async def test_llm_card_in_name_and_cyrillic_grade_save_without_duplicate_fields(self):
        await self.seed()
        await self.client.post("/api/v1/trainings", headers=self.a, json={"date":"2026-10-20"})
        await self.send("2", "Запиши Engesh")
        await self.process("ai", Intent(kind="attempt", region="Geyikbayiri", sector="Kebap",
            name="Регион: Geyikbayiri Сектор: Kebap Название трассы: Engesh Категория: 6а Чисто: да",
            grade="6а", style="flash", belay="lead"))
        snapshot = await self.conn.scalar(select(RouteAttempt.route_snapshot))
        self.assertEqual(snapshot["name"], "Engesh")
        self.assertEqual(snapshot["grade"], "6A")
        self.assertIsNone(await self.draft())
        payload = await self.conn.scalar(select(Outbox.payload).order_by(Outbox.sequence.desc()).limit(1))
        self.assertTrue(payload["text"].startswith("Сохранено."))
        for label in ("Регион:", "Сектор:", "Название трассы:", "Категория:"):
            self.assertEqual(payload["text"].count(label), 1)

    async def test_multilingual_names_metadata_and_similar_choices(self):
        await self.seed()
        async with AsyncSession(bind=self.conn, expire_on_commit=False, join_transaction_mode="create_savepoint") as session:
            sector = await session.get(Section, self.sector.id)
            sector.name_en, sector.name_native = "Moon wall", "Лунная стена"
            route = await session.get(Route, self.route.id)
            route.name_en, route.name_native = "Moon river", "Лунная река"
            session.add(Route(name="Moon rivers", section_id=self.sector.id, grade="6B"))
            await session.commit()
        for kind, query, parent, expected in (
            ("sections", "ЛУННАЯ СТЕНА", self.area.id, self.sector.id),
            ("sections", "Moon wall", self.area.id, self.sector.id),
            ("routes", "Лунная река", self.sector.id, self.route.id),
            ("routes", "Moon river", self.sector.id, self.route.id)):
            response = await self.client.get(f"/api/v1/catalog-search/{kind}", headers=self.a,
                params={"q": query, "parent_id": parent})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["items"][0]["id"], expected)
            self.assertEqual(response.json()["items"][0]["match"], "exact")
        for query in ("6A", "Лунная стена", "river", "Moon riverr"):
            response = await self.client.get("/api/v1/catalog-search/routes", headers=self.a,
                params={"q": query, "parent_id": self.sector.id})
            items = response.json()["items"]
            self.assertIn(self.route.id, [x["id"] for x in items])
            self.assertTrue(all(x["match"] == "similar" for x in items))
            if query == "Moon riverr":
                self.assertEqual(len(items), 2)
            self.assertEqual(next(x for x in items if x["id"] == self.route.id)["name_native"], "Лунная река")

    async def test_language_fields_create_patch_and_public_protection(self):
        await self.seed()
        area = (await self.client.post("/api/v1/catalog/locations", headers=self.a,
            json={"name": "My area"})).json()
        sector = await self.client.post("/api/v1/catalog/sections", headers=self.a,
            json={"location_id": area["id"], "name": "Скала", "name_native": "Скала", "name_en": "Rock"})
        self.assertEqual(sector.status_code, 200, sector.text)
        self.assertEqual(sector.json()["name_en"], "Rock")
        route = await self.client.post("/api/v1/catalog/routes", headers=self.a,
            json={"section_id": sector.json()["id"], "name": "Путь", "name_native": "Путь", "name_en": "Way"})
        self.assertEqual(route.status_code, 200, route.text)
        changed = await self.client.patch(f"/api/v1/catalog/routes/{route.json()['id']}", headers=self.a,
            json={"name_en": "The way"})
        self.assertEqual(changed.status_code, 200, changed.text)
        self.assertEqual(changed.json()["name_en"], "The way")
        denied = await self.client.patch(f"/api/v1/catalog/routes/{self.route.id}", headers=self.a,
            json={"name_en": "Overwrite shared name"})
        self.assertIn(denied.status_code, (403, 404))

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
        other_results = (await self.client.get("/api/v1/catalog-search/locations",headers=self.b,params={"q":"Гейкбаири"})).json()["items"]
        # Public names can match by transliteration, but another user's alias cannot be exact.
        self.assertTrue(all(item["match"] == "similar" for item in other_results))
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
