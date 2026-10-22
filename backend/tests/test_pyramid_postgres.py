from datetime import date
import unittest
from sqlalchemy import insert
from app.models import Location, Section, TrainingSession, RouteAttempt
from tests import test_auth_postgres as fixtures


class PyramidPostgresTest(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixtures.AuthPostgresTest.asyncSetUp
    asyncTearDown=fixtures.AuthPostgresTest.asyncTearDown
    login=fixtures.AuthPostgresTest.login

    async def test_drilldown_matches_counts_filters_pages_and_identity(self):
        a,b=await self.login("901"),await self.login("902")
        ua=(await self.client.get('/api/v1/me',headers=a)).json()['id']
        ub=(await self.client.get('/api/v1/me',headers=b)).json()['id']
        await self.conn.execute(insert(Location).values(id='loc',name='Гейкбаири',type='outdoor',owner_id=ua,visibility='private',region='Анталья'))
        await self.conn.execute(insert(Section).values(id='sector',name='Мағара',location_id='loc',type='sector'))
        for tid,uid,day in [('ta',ua,date(2026,10,21)),('tb',ub,date(2026,10,21)),('old',ua,date(2025,1,1))]:
            await self.conn.execute(insert(TrainingSession).values(id=tid,user_id=uid,status='completed',local_date=day,timezone='Europe/Moscow',environment='outdoor'))
        async def add(id,key,seq,clean,style,tid='ta',test=False):
            await self.conn.execute(insert(RouteAttempt).values(id=id,training_id=tid,route_session_key=key,sequence=seq,
                clean_ascent=clean,reached_top=True,style=style,attempts=2,belay='top_rope',is_test=test,
                route_snapshot={'name':'Engesh','grade':'6а',**({'areaId':'loc','sectorId':'sector'} if tid!='tb' else {})}))
        await add('a1','project',1,False,'with_hangs')
        await add('a2','project',2,True,'redpoint')
        await add('a3','project',3,True,'flash')
        await add('a4','first',4,True,'onsight')
        await add('a5','pending',5,False,'unknown')
        await add('a6','test',6,True,'flash',test=True)
        await add('b1','private-b',1,True,'flash',tid='tb')
        await add('old1','old',1,True,'flash',tid='old')
        query='date_from=2026-10-01&date_to=2026-10-31&grade=6A'
        summary=(await self.client.get('/api/v1/statistics/grades?'+query,headers=a)).json()['grades'][0]
        self.assertEqual(summary['pyramid'],dict(onsight=1,flash=0,redpoint=1,top_rope=0,other_clean=0,not_clean=1))
        self.assertEqual(summary['styles']['unknown'],1)
        self.assertEqual(summary['belays']['top_rope'],3)
        filtered=(await self.client.get('/api/v1/statistics/grade-ascents?'+query+'&group_style=unknown&belay=top_rope',headers=a)).json()
        self.assertEqual(filtered['total'],1)
        self.assertEqual(filtered['items'][0]['routeSessionKey'],'pending')
        result=await self.client.get('/api/v1/statistics/grade-ascents?'+query+'&style=redpoint&region=Анталья&area_id=loc',headers=a)
        self.assertEqual(result.status_code,200,result.text)
        body=result.json();self.assertEqual(body['total'],1)
        item=body['items'][0]
        self.assertEqual(item['attemptsCount'],6)
        self.assertEqual(item['location']['name'],'Гейкбаири')
        self.assertEqual(item['sector']['name'],'Мағара')
        self.assertEqual(item['route']['grade'],'6A')
        self.assertEqual(item['belay'],'top_rope')
        self.assertEqual(len(item['attempts']),3)
        page=(await self.client.get('/api/v1/statistics/grade-ascents?'+query+'&limit=1',headers=a)).json()
        page2=(await self.client.get('/api/v1/statistics/grade-ascents?'+query+'&limit=1&offset='+str(page['nextOffset']),headers=a)).json()
        self.assertEqual(page['total'],3)
        self.assertNotEqual(page['items'][0]['routeSessionKey'],page2['items'][0]['routeSessionKey'])
        other=(await self.client.get('/api/v1/statistics/grade-ascents?'+query+'&area_id=loc',headers=b)).json()
        self.assertEqual(other['total'],0)
        own=(await self.client.get('/api/v1/statistics/grade-ascents?'+query,headers=b)).json()
        self.assertEqual([item['trainingId'] for item in own['items']],['tb'])
        self.assertEqual((await self.client.get('/api/v1/statistics/grade-ascents?'+query+'&style=invalid',headers=a)).status_code,422)
