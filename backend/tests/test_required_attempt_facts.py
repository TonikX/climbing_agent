"""Incomplete facts never become saved attempts; migration never guesses history."""
import importlib.util
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, func, text
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.attempt_outcome import outcome, normalized_style, validated_belay
from app.models import RouteAttempt
from app.public_models import Outbox
from app.public_schemas import Intent
import test_public_service as public_tests


class RequiredFactsTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = public_tests.PublicServiceTest.asyncSetUp
    asyncTearDown = public_tests.PublicServiceTest.asyncTearDown
    asyncSetUpBase = public_tests.PublicServiceTest.asyncSetUpBase
    asyncTearDownBase = public_tests.PublicServiceTest.asyncTearDownBase
    login = public_tests.PublicServiceTest.login
    send = public_tests.PublicServiceTest.send
    process = public_tests.PublicServiceTest.process

    async def test_ai_asks_for_each_missing_fact_before_saving(self):
        await self.login('2')
        await self.send('2', 'training:start', True)
        await self.process()
        await self.send('2', 'Трасса 6A')
        await self.process('ai', Intent(kind='attempt', region='Район', sector='Сектор', name='Трасса', grade='6A'))
        message = await self.conn.scalar(select(Outbox.payload).order_by(Outbox.sequence.desc()).limit(1))
        for field in ('Дошёл до конца', 'Чисто', 'Страховка'):
            self.assertIn(field, message['text'])
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)
        await self.send('2', 'С зависанием')
        await self.process('ai', Intent(kind='attempt', style='with_hangs', hangs=1))
        message = await self.conn.scalar(select(Outbox.payload).order_by(Outbox.sequence.desc()).limit(1))
        self.assertIn('Дошёл до конца', message['text'])
        self.assertIn('Страховка', message['text'])
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)
        await self.send('2', 'Долез, нижняя')
        await self.process('ai', Intent(kind='attempt', reached_top=True, belay='lead'))
        row = (await self.conn.execute(select(RouteAttempt.reached_top, RouteAttempt.clean_ascent, RouteAttempt.belay, RouteAttempt.style))).one()
        self.assertEqual(row, (True, False, 'lead', 'with_hangs'))

    async def test_api_rejects_missing_unknown_and_upper_style(self):
        headers = await self.login('2')
        training = (await self.client.post('/api/v1/trainings', headers=headers, json={'date':'2026-10-22'})).json()
        for values in ({'clean_ascent':True}, {'reached_top':True,'belay':'lead'},
                       {'clean_ascent':False,'belay':'lead'}, {'style':'top_rope','belay':'top_rope','clean_ascent':True},
                       {'clean_ascent':True,'belay':'unknown'}, {'clean_ascent':None,'reached_top':True,'belay':'lead'}):
            response = await self.client.post('/api/v1/trainings/'+training['id']+'/attempts', headers=headers, json={'name':'R',**values})
            self.assertEqual(response.status_code, 422, (values,response.text))
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)
        for raw in ({}, {'belay':'unknown'}, {'belay':None}):
            with self.assertRaises(HTTPException):
                validated_belay(raw)
        with self.assertRaises(HTTPException):
            normalized_style({'style':'top_rope'})
        with self.assertRaises(HTTPException):
            outcome({'style':'flash','falls':1})  # A contradictory style cannot establish reaching the top.
        self.assertEqual(outcome({'style':'flash'})['clean_ascent'], True)
        self.assertEqual(outcome({'reachedTop':False})['clean_ascent'], False)

    async def test_contradictory_clarification_does_not_keep_an_inferred_top(self):
        await self.login('2')
        await self.send('2', 'training:start', True)
        await self.process()
        await self.send('2', 'Трасса 6A flash')
        await self.process('ai', Intent(kind='attempt', region='Район', sector='Сектор', name='Трасса', grade='6A', style='flash'))
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)
        await self.send('2', 'Со срывом, нижняя страховка')
        await self.process('ai', Intent(kind='attempt', falls=1, belay='lead'))
        self.assertEqual(await self.conn.scalar(select(func.count(RouteAttempt.id))), 0)
        message = await self.conn.scalar(select(Outbox.payload).order_by(Outbox.sequence.desc()).limit(1))
        self.assertIn('Дошёл до конца', message['text'])
        await self.send('2', 'Нет, не долез')
        await self.process('ai', Intent(kind='attempt', reached_top=False))
        self.assertEqual((await self.conn.execute(select(RouteAttempt.reached_top, RouteAttempt.clean_ascent, RouteAttempt.belay))).one(),
            (False, False, 'lead'))

    async def migration(self):
        path = Path(__file__).parents[1]/'migrations/versions/20261022_0020_required_attempt_facts.py'
        spec = importlib.util.spec_from_file_location('required_facts_migration', path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        def upgrade(conn):
            with Operations.context(MigrationContext.configure(conn)):
                migration.upgrade()
        await self.conn.run_sync(upgrade)

    async def legacy_table(self):
        await self.conn.execute(text('DROP TABLE route_attempts CASCADE'))
        await self.conn.execute(text("""CREATE TABLE route_attempts (id text PRIMARY KEY, style text,
            belay varchar(20) NOT NULL DEFAULT 'unknown', reached_top boolean, clean_ascent boolean,
            falls int, hangs int, result text,
            CONSTRAINT ck_attempt_style CHECK(style IN ('onsight','flash','redpoint','with_falls','with_hangs','top_rope','unknown')),
            CONSTRAINT ck_attempt_belay CHECK(belay IN ('lead','top_rope','auto_belay','bouldering','unknown')))"""))

    async def test_migration_stops_for_unknowns_then_moves_upper_to_belay_and_enforces_db(self):
        await self.legacy_table()
        await self.conn.execute(text("""INSERT INTO route_attempts VALUES
            ('upper','top_rope','unknown',true,false,1,0,'project'),
            ('missing','unknown','lead',NULL,false,0,0,'project')"""))
        with self.assertRaisesRegex(RuntimeError, 'incomplete historical'):
            async with self.conn.begin_nested():
                await self.migration()
        self.assertEqual((await self.conn.execute(text("SELECT style,belay FROM route_attempts WHERE id='upper'"))).one(), ('top_rope','unknown'))
        await self.conn.execute(text("UPDATE route_attempts SET reached_top=false WHERE id='missing'"))
        await self.migration()
        self.assertEqual((await self.conn.execute(text("SELECT style,belay,reached_top,clean_ascent,result FROM route_attempts WHERE id='upper'"))).one(),
            ('with_falls','top_rope',True,False,'project'))
        for fragment in ('reached_top=NULL','clean_ascent=NULL',"style='top_rope'","belay='unknown'"):
            with self.assertRaises(IntegrityError):
                async with self.conn.begin_nested():
                    await self.conn.execute(text('UPDATE route_attempts SET '+fragment+" WHERE id='upper'"))

    async def test_migration_does_not_overwrite_conflicting_belay(self):
        await self.legacy_table()
        await self.conn.execute(text("INSERT INTO route_attempts VALUES ('conflict','top_rope','lead',true,true,0,0,'send')"))
        with self.assertRaisesRegex(RuntimeError, 'conflicts'):
            async with self.conn.begin_nested():
                await self.migration()
        self.assertEqual(await self.conn.scalar(text("SELECT belay FROM route_attempts")), 'lead')
