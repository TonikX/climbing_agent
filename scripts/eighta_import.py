"""Prepare an 8a.nu import from saved browser CSV and a public catalogue snapshot.

No network or DB connection. Ambiguous matches stay in the PostgreSQL run report,
not duplicated in the route catalogue. Existing IDs and known grades are retained.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit, quote

LOCATION = "location_c79a7c4e-e852-4a9b-9fca-27149bb11508"
SOURCE = "8a.nu"
AREA_URL = "https://www.8a.nu/areas/turkey/geyikbayiri/crags"


def normalize(value):
    value=unicodedata.normalize('NFKD',value.casefold().replace('ı','i'))
    value=''.join(c for c in value if not unicodedata.combining(c))
    return ' '.join(re.findall(r'\w+',value))


def literal(value):
    if '\0' in str(value):raise ValueError('NUL in SQL')
    return "'"+str(value).replace("'","''")+"'"


def external_id(url):
    return 'url:'+hashlib.sha256(url.encode()).hexdigest()


def internal_id(kind,url):
    return kind+'_'+hashlib.sha256((SOURCE+':'+kind+':'+url).encode()).hexdigest()[:32]


def related(existing,crag,sector):
    name=normalize(existing)
    for value in [normalize(crag),normalize(sector)]:
        if name==value or name.startswith(value+' ') or value.startswith(name+' '):return True
    return normalize(crag)=='kebap' and name in {'kebab left','kebab right'}


def plan(rows,existing):
    sections={r['id']:r for r in existing if r['kind']=='section'}
    old_routes=[r for r in existing if r['kind']=='route']
    sector_counts=Counter((r['crag_url'],r['sector'],normalize(r['name'])) for r in rows)
    old_by_name=defaultdict(list)
    for r in old_routes:old_by_name[normalize(r['name'])].append(r)
    refs, new_sections, new_routes, accepted, pending, grade_conflicts = [], {}, {}, [], [], []
    section_map={}
    names={normalize(s['name']):s['id'] for s in sections.values()}
    if len(names)!=len(sections):raise ValueError('Ambiguous existing sector names')
    for row in rows:
        path=urlsplit(row['url'])
        parts=path.path.strip('/').split('/')
        if path.scheme!='https' or path.netloc!='www.8a.nu' or path.query or len(parts)!=8 or parts[0]!='crags' or parts[1] not in {'sportclimbing','bouldering'} or parts[2]!='turkey' or parts[4]!='sectors' or parts[6]!='routes':
            raise ValueError('Unexpected route URL')
        if row['country']!='Турция' or row['area']!='Geyikbayırı' or row['discipline']!=parts[1] or not row['name'] or len(row['name'])>200:
            raise ValueError('Invalid source context/name')
        if row['crag_url']!='https://www.8a.nu/'+'/'.join(parts[:4])+'/routes':raise ValueError('Crag URL mismatch')
        if not re.fullmatch(r'[3-9][a-cA-C]?\+?',row['grade']):raise ValueError('Unreviewed grade notation')
        grade=row['grade'].upper()
        candidates=old_by_name[normalize(row['name'])] if row['discipline']=='sportclimbing' else []
        candidates=[r for r in candidates if related(sections[r['parent_id']]['name'],row['crag'],row['sector']) or row['crag']=='Unknown Crag']
        reason=None
        if sector_counts[(row['crag_url'],row['sector'],normalize(row['name']))]>1:reason='duplicate_name_in_source_sector'
        elif len(candidates)>1:reason='multiple_existing_candidates'
        elif candidates and row['crag']=='Unknown Crag':reason='unknown_source_sector_existing_candidate'
        if reason:
            pending.append({**row,'reason':reason,'candidate_ids':[r['id'] for r in candidates]})
            continue
        section_url=row['crag_url']+'?sector='+quote(parts[5],safe='-_.~')
        if section_url not in section_map:
            label=row['sector']
            if not normalize(label).startswith(normalize(row['crag'])):label=row['crag']+' / '+label
            if row['discipline']=='bouldering':label+=' (боулдеринг)'
            if len(label)>200:raise ValueError('Sector name too long')
            target=names.get(normalize(label)) if row['discipline']=='sportclimbing' else None
            target=target or internal_id('section',section_url)
            section_map[section_url]=target
            if target not in sections:
                new_sections[target]={'id':target,'name':label,'url':section_url}
            refs.append(('section',section_url,target))
        if candidates:
            old=candidates[0]
            target=old['id']
            if old['grade'] and old['grade'].upper()!=grade:grade_conflicts.append({'id':target,'existing_grade':old['grade'],'source_grade':grade,'url':row['url']})
            accepted.append({**row,'target_id':target,'section_id':old['parent_id'],'existing_name':old['name'],'action':'existing','grade_value':grade})
        else:
            target=internal_id('route',row['url'])
            new_routes[target]={'id':target,'name':row['name'],'section_id':section_map[section_url],'grade':grade}
            accepted.append({**row,'target_id':target,'section_id':section_map[section_url],'action':'new','grade_value':grade})
        refs.append(('route',row['url'],target))
    refs.insert(0,('location',AREA_URL,LOCATION))
    return dict(refs=refs,new_sections=new_sections,new_routes=new_routes,accepted=accepted,pending=pending,grade_conflicts=grade_conflicts,
                matched=sum(r['action']=='existing' for r in accepted),filled=sum(r['action']=='existing' and not next(e['grade'] for e in old_routes if e['id']==r['target_id']) for r in accepted))


def sql_for(result,source_hash):
    counts={'source_rows':len(result['accepted'])+len(result['pending']),'accepted_refs':len(result['accepted']),
            'new_routes':len(result['new_routes']),'matched_existing':result['matched'],'new_sections':len(result['new_sections']),
            'empty_grades_filled':result['filled'],'pending_count':len(result['pending'])}
    report={**counts,'source_url':AREA_URL,'source_sha256':source_hash,'pending':result['pending'],'grade_conflicts':result['grade_conflicts'],
            'notes':'Saved authenticated browser tables; public catalogue only; existing IDs/names/known grades retained; bouldering separate'}
    run_id='import_'+hashlib.sha256((SOURCE+source_hash).encode()).hexdigest()[:32]
    lines=['BEGIN;','SET LOCAL standard_conforming_strings=on;','SELECT pg_advisory_xact_lock(718394139489);',
           'CREATE TEMP TABLE eighta_guard(ok boolean NOT NULL CHECK(ok)) ON COMMIT DROP;',
           "INSERT INTO eighta_guard SELECT EXISTS(SELECT 1 FROM locations WHERE id="+literal(LOCATION)+" AND visibility='public' AND owner_id IS NULL AND country='Турция');"]
    for s in result['new_sections'].values():
        lines.append('INSERT INTO sections(id,location_id,type,name) VALUES('+','.join(map(literal,[s['id'],LOCATION,'sector',s['name']]))+') ON CONFLICT(id) DO NOTHING;')
    for r in result['new_routes'].values():
        lines.append('INSERT INTO routes(id,section_id,name,grade) VALUES('+','.join(map(literal,[r['id'],r['section_id'],r['name'],r['grade']]))+') ON CONFLICT(id) DO NOTHING;')
    for r in result['accepted']:
        lines.append('INSERT INTO eighta_guard SELECT EXISTS(SELECT 1 FROM routes r JOIN sections s ON s.id=r.section_id WHERE r.id='+literal(r['target_id'])+' AND r.section_id='+literal(r['section_id'])+' AND s.location_id='+literal(LOCATION)+');')
        if r['action']=='existing':
            lines.append('INSERT INTO eighta_guard SELECT EXISTS(SELECT 1 FROM routes WHERE id='+literal(r['target_id'])+' AND name='+literal(r['existing_name'])+');')
            lines.append('UPDATE routes SET grade='+literal(r['grade_value'])+' WHERE id='+literal(r['target_id'])+' AND grade IS NULL;')
    for kind,url,target in result['refs']:
        ref_id=internal_id('external_ref',kind+':'+url)
        values=[ref_id,SOURCE,kind,external_id(url),url,target]
        lines.append('INSERT INTO external_refs(id,system,entity_type,external_id,url,'+kind+'_id) VALUES('+','.join(map(literal,values))+') ON CONFLICT(system,entity_type,external_id) DO NOTHING;')
        lines.append('INSERT INTO eighta_guard SELECT EXISTS(SELECT 1 FROM external_refs WHERE system='+literal(SOURCE)+' AND entity_type='+literal(kind)+' AND external_id='+literal(external_id(url))+' AND '+kind+'_id='+literal(target)+');')
    lines.append('INSERT INTO eighta_guard SELECT count(*)='+str(len(result['refs']))+' FROM external_refs WHERE system='+literal(SOURCE)+';')
    lines.append('INSERT INTO catalog_import_runs(id,source,status,finished_at,report) VALUES('+','.join(map(literal,[run_id,SOURCE,'partial' if result['pending'] else 'succeeded']))+',now(),'+literal(json.dumps(report,ensure_ascii=False))+'::jsonb) ON CONFLICT(id) DO NOTHING;')
    lines.append('COMMIT;')
    return '\n'.join(lines)+'\n',counts,run_id


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path);p.add_argument('existing',type=Path)
    p.add_argument('--output',type=Path,default=Path('output/catalog/8a-geyikbayiri/import'))
    args=p.parse_args()
    with args.source.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    if len(rows)!=len({r['url'] for r in rows}):raise ValueError('Duplicate source URLs')
    with args.existing.open(encoding='utf-8-sig',newline='') as f:existing=list(csv.DictReader(f))
    result=plan(rows,existing)
    digest=hashlib.sha256(args.source.read_bytes()).hexdigest()
    sql,counts,run_id=sql_for(result,digest)
    args.output.mkdir(parents=True,exist_ok=True)
    (args.output/'import.sql').write_text(sql,encoding='utf-8')
    (args.output/'report.txt').write_text('\n'.join(f'{k}: {v}' for k,v in counts.items())+'\nrun_id: '+run_id+'\n',encoding='utf-8')
    for filename,data in [('pending.csv',result['pending']),('matched.csv',[r for r in result['accepted'] if r['action']=='existing']),('grade-conflicts.csv',result['grade_conflicts'])]:
        if data:
            with (args.output/filename).open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    print(counts);print('run_id:',run_id)


if __name__=='__main__':main()
