import os, json, datetime, urllib.request, urllib.parse, urllib.error, hmac, hashlib, secrets, time, re, io, statistics
from zoneinfo import ZoneInfo
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs

TZ=ZoneInfo('Asia/Singapore')
DAYS=[('Swim — Threshold','swim','400 easy + 4x100 drill/build + 5x300 steady-hard (20s rest) + 4x100 pull + 100 easy = 2800m'),('Gym A — Upper body','gym','Lat pulldown 3x6-10; chest-supported row 3x8-12; incline press 3x8-12; lateral raise 3x12-15; dead bug 3x10/side; prescribed knee rehab'),('Recovery','rest','Rest, mobility and prescribed knee rehab'),('Swim — Speed','swim','400 easy + 8x50 drills/build + 12x50 fast (30-45s rest) + 8x100 controlled + 200 easy = 2400m'),('Gym B — Upper body + core','gym','Cable row 3x10-12; seated neutral-grip shoulder press 3x8-10; chest press 3x8-12; reverse fly 3x12-15; Pallof press 3x12/side; prescribed knee rehab'),('Swim — Aerobic','swim','400 easy + 3x800 steady (30s rest) + 200 easy = 3000m'),('Recovery / optional easy movement','rest','Rest; no hard running, cycling or leg sessions during restriction period')]

def env(k): return os.environ.get(k,'')
def req(url, payload=None, headers=None, method=None):
    data=json.dumps(payload).encode() if payload is not None else None
    h={'Content-Type':'application/json',**(headers or {})}
    with urllib.request.urlopen(urllib.request.Request(url,data=data,headers=h,method=method),timeout=12) as r: return json.loads(r.read() or b'{}')
def db(table,method='GET',data=None,query=''):
    url=env('SUPABASE_URL').rstrip('/')+'/rest/v1/'+table+query
    return req(url,data,{'apikey':env('SUPABASE_SERVICE_ROLE_KEY'),'Authorization':'Bearer '+env('SUPABASE_SERVICE_ROLE_KEY'),'Prefer':'return=representation,resolution=merge-duplicates' if table in ('coaching_recommendations','garmin_activities','garmin_swim_lengths','workout_overrides') and method=='POST' else 'return=representation'},method)
def send(chat_id,message):
    return req('https://api.telegram.org/bot'+env('TELEGRAM_BOT_TOKEN')+'/sendMessage',{'chat_id':chat_id,'text':message[:3900]})

# Garmin Connect Personal API (read-only, single-user).
GARMIN_BASE='https://personal.connectapi.garmin.com'
def garmin_token():
    key=env('GARMIN_PERSONAL_API_KEY').strip()
    if not key:return None
    request=urllib.request.Request(
        GARMIN_BASE+'/personalapitoken-service/personal-api/personal-api-key/token',
        data=b'',method='POST',
        headers={'Authorization':'ApiKey '+key,'Accept':'*/*'})
    with urllib.request.urlopen(request,timeout=12) as response:
        raw=response.read().decode('utf-8').strip()
    # Garmin returns a plain bearer token; some clients may wrap it in JSON.
    if raw.startswith('{'):
        obj=json.loads(raw)
        raw=obj.get('access_token') or obj.get('token') or ''
    if not raw or len(raw)>8192:raise ValueError('Invalid Garmin token response')
    return raw

def garmin_api(path,token):
    if not path.startswith('/') or '://' in path:raise ValueError('Invalid Garmin API path')
    request=urllib.request.Request(GARMIN_BASE+path,headers={'Authorization':'Bearer '+token,'Accept':'application/json'})
    with urllib.request.urlopen(request,timeout=15) as response:return json.loads(response.read())


# v5.4: Garmin is a read-only enrichment source; never insert Garmin duplicates into activities.
def garmin_download_fit(activity_id, token):
    import zipfile
    if not str(activity_id).isdigit():raise ValueError('Invalid Garmin activity ID')
    url=GARMIN_BASE+'/download-service/files/activity/'+str(activity_id)
    request=urllib.request.Request(url,headers={'Authorization':'Bearer '+token,'Accept':'*/*'})
    with urllib.request.urlopen(request,timeout=18) as response:
        if response.headers.get('Content-Length') and int(response.headers['Content-Length'])>8_000_000:
            raise ValueError('Garmin archive exceeds 8MB limit')
        payload=response.read(8_000_001)
    if len(payload)>8_000_000:raise ValueError('Garmin archive exceeds 8MB limit')
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        files=[info for info in archive.infolist() if info.filename.lower().endswith('.fit') and not info.is_dir()]
        if len(files)!=1:raise ValueError('Expected exactly one FIT file')
        if files[0].file_size>12_000_000:raise ValueError('FIT file exceeds size limit')
        return archive.read(files[0])

def garmin_parse_swim(fit_bytes):
    from fitparse import FitFile
    fit=FitFile(io.BytesIO(fit_bytes));fit.parse()
    sessions=[{f.name:f.value for f in m} for m in fit.get_messages('session')]
    session=sessions[0] if sessions else {}
    pool=session.get('pool_length')
    if not isinstance(pool,(int,float)) or not 10<=pool<=100:
        raise ValueError('No valid pool length in FIT session')
    result=[]
    for msg in fit.get_messages('length'):
        data={f.name:f.value for f in msg}
        if str(data.get('length_type')).lower() in ('idle','1'):continue
        seconds=data.get('total_timer_time')
        if not isinstance(seconds,(int,float)) or not 3<=seconds<=600:continue
        strokes=data.get('total_strokes')
        if not isinstance(strokes,int) or strokes<0:strokes=None
        hr=data.get('avg_heart_rate')
        if not isinstance(hr,int) or not 30<=hr<=230:hr=None
        result.append({'length_index':len(result)+1,'start_time':str(data.get('start_time') or ''),
                       'distance_m':round(float(pool),2),'timer_s':round(float(seconds),3),
                       'strokes':strokes,'stroke_type':str(data.get('swim_stroke') or ''),
                       'avg_hr':hr})
        if len(result)>1500:raise ValueError('Excessive FIT length count')
    return result

def garmin_match_strava(a,chat):
    """Conservative matching: date + kind + close distance, unique candidate only.
    Does not create or modify workout totals in public.activities."""
    typ=((a.get('activityType') or {}).get('typeKey') or '').lower()
    kind=('swim' if typ in ('lap_swimming','open_water_swimming') else
          'gym' if typ=='strength_training' else
          'run' if 'running' in typ else
          'bike' if 'cycling' in typ else None)
    if not kind:return None,'unmatched'
    date=(a.get('startTimeLocal') or a.get('startTimeGMT') or '')[:10]
    if not date:return None,'unmatched'
    rows=db('strava_imports',query='?activity_date=eq.'+date+'&select=activity_id,sport_type,distance_m')
    distance=a.get('distance')
    candidates=[]
    for row in rows:
        sport=str(row.get('sport_type') or '').lower()
        same=(kind=='swim' and sport=='swim') or (kind=='gym' and sport in ('weighttraining','workout','functionalstrengthtraining')) or (kind=='run' and 'run' in sport) or (kind=='bike' and ('ride' in sport or 'cycling' in sport))
        if not same:continue
        other=row.get('distance_m')
        if kind in ('swim','run','bike') and isinstance(distance,(int,float)) and isinstance(other,(int,float)):
            if abs(float(distance)-float(other))>max(30,0.03*float(distance)):continue
        candidates.append(str(row['activity_id']))
    if len(candidates)==1:return candidates[0],'matched'
    return None,'ambiguous' if len(candidates)>1 else 'unmatched'

def garmin_sync(limit=10):
    if not env('GARMIN_PERSONAL_API_KEY'):return 'Garmin key missing.'
    token=garmin_token()
    items=garmin_api('/activitylist-service/activities/search/activities?'+urllib.parse.urlencode({'start':0,'limit':limit}),token)
    if not isinstance(items,list):raise ValueError('Garmin activities response was not a list')
    seen=0;new=0;swims=0;skipped=0;errors=[]
    chat=env('TELEGRAM_CHAT_ID')
    for a in items:
        aid=a.get('activityId')
        if not isinstance(aid,int) or aid<=0:continue
        seen+=1
        old=db('garmin_activities',query='?activity_id=eq.'+str(aid)+'&select=activity_id,swim_length_count')
        if old and (old[0].get('swim_length_count') or 0)>0:skipped+=1;continue
        typ=((a.get('activityType') or {}).get('typeKey') or 'unknown')
        date=(a.get('startTimeLocal') or a.get('startTimeGMT') or '')[:10]
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date):continue
        match,status=garmin_match_strava(a,chat)
        row={'activity_id':aid,'chat_id':chat,'activity_date':date,'start_time_local':str(a.get('startTimeLocal') or '')[:40],
             'activity_type':typ,'name':str(a.get('activityName') or '')[:200],
             'distance_m':a.get('distance'),'duration_s':a.get('duration'),
             'strava_activity_id':match,'match_status':status}
        if not old:
            db('garmin_activities','POST',row,'?on_conflict=activity_id');new+=1
        else:
            db('garmin_activities','PATCH',row,'?activity_id=eq.'+str(aid))
        if typ!='lap_swimming':continue
        try:
            lengths=garmin_parse_swim(garmin_download_fit(aid,token))
            if not lengths:raise ValueError('No active pool lengths')
            for i in range(0,len(lengths),100):
                chunk=[{'activity_id':aid,**length} for length in lengths[i:i+100]]
                db('garmin_swim_lengths','POST',chunk,'?on_conflict=activity_id,length_index')
            db('garmin_activities','PATCH',{'swim_length_count':len(lengths)},'?activity_id=eq.'+str(aid))
            swims+=1
        except Exception as exc:
            print('Garmin FIT import error',aid,type(exc).__name__)
            errors.append(str(aid))
    return f'GARMIN SYNC: {seen} checked, {new} new metadata records, {swims} swims with FIT lengths, {skipped} already imported.'+((' FIT import failed for IDs: '+', '.join(errors[:5])) if errors else '')+'\nGarmin enriches Strava workouts; it does not add duplicate workout totals.'

def garmin_swim_report():
    rows=db('garmin_activities',query='?chat_id=eq.'+urllib.parse.quote(env('TELEGRAM_CHAT_ID'))+'&activity_type=eq.lap_swimming&swim_length_count=gt.0&order=activity_date.desc,start_time_local.desc&limit=1&select=activity_id,activity_date,name,swim_length_count,strava_activity_id,match_status')
    if not rows:return None
    a=rows[0];aid=a['activity_id']
    lengths=db('garmin_swim_lengths',query='?activity_id=eq.'+str(aid)+'&order=length_index.asc&select=length_index,distance_m,timer_s,strokes,avg_hr')
    if not lengths:return None
    total=sum(float(x['distance_m']) for x in lengths)
    timer=sum(float(x['timer_s']) for x in lengths)
    counts=[int(x['strokes']) for x in lengths if x.get('strokes') is not None]
    times=[float(x['timer_s']) for x in lengths]
    pace=pace_per_100(timer,total)
    lines=['GARMIN SWIM ANALYSIS — '+str(a['activity_date']),str(a['name']),
           f'{total:g}m | {len(lengths)} actual pool lengths | swim timer {int(timer//60)}:{int(round(timer%60)):02d} | {pace}',
           'Garmin original FIT length records (not estimated Strava crossings).']
    if counts:
        lines.append(f'Strokes: {sum(counts)} total; {statistics.mean(counts):.1f}/length; range {min(counts)}–{max(counts)}')
        swolf=[float(x['timer_s'])+int(x['strokes']) for x in lengths if x.get('strokes') is not None]
        lines.append(f'Calculated SWOLF: {statistics.mean(swolf):.1f} (length seconds + recorded strokes)')
    lines.append('500M BLOCKS')
    for start in range(0,len(lengths),1):
        if start and sum(float(x['distance_m']) for x in lengths[:start])%500!=0:continue
        segment=[];metres=0
        for x in lengths[start:]:
            if metres>=500:break
            segment.append(x);metres+=float(x['distance_m'])
        if abs(metres-500)>0.1:continue
        secs=sum(float(x['timer_s']) for x in segment)
        strokes=[int(x['strokes']) for x in segment if x.get('strokes') is not None]
        lines.append(f'{int(sum(float(x["distance_m"]) for x in lengths[:start]))}–{int(sum(float(x["distance_m"]) for x in lengths[:start])+500)}m: {pace_per_100(secs,500)}; strokes/length {statistics.mean(strokes):.1f}' if strokes else f'{start}: {pace_per_100(secs,500)}')
    lines.append(f'Strava match: {a["match_status"]}'+(f' (ID {a["strava_activity_id"]})' if a.get('strava_activity_id') else ''))
    lines.append('FIT stroke counts and length times depend on watch recording accuracy.')
    return '\n'.join(lines)


# v5.5: Read-only longitudinal Garmin pool swim coaching. No new tables required.
def swim_history(max_swims=12):
    q='?chat_id=eq.'+urllib.parse.quote(env('TELEGRAM_CHAT_ID'))+'&activity_type=eq.lap_swimming&swim_length_count=gt.0&order=activity_date.desc,start_time_local.desc&limit='+str(max_swims)+'&select=activity_id,activity_date,name,swim_length_count'
    rows=db('garmin_activities',query=q) or []
    history=[]
    for a in rows:
        lengths=db('garmin_swim_lengths',query='?activity_id=eq.'+str(a['activity_id'])+'&order=length_index.asc&select=distance_m,timer_s,strokes,avg_hr') or []
        if not lengths:continue
        total=sum(float(x['distance_m']) for x in lengths)
        secs=sum(float(x['timer_s']) for x in lengths)
        if total<=0 or secs<=0:continue
        strokes=[x for x in lengths if isinstance(x.get('strokes'),int)]
        stroke_rate=(sum(x['strokes'] for x in strokes)/len(strokes)) if strokes else None
        swolf=(sum(float(x['timer_s'])+x['strokes'] for x in strokes)/len(strokes)) if strokes else None
        half=total/2;covered=0;first=[];second=[]
        for x in lengths:
            mid=covered+float(x['distance_m'])/2
            (first if mid<=half else second).append(x)
            covered+=float(x['distance_m'])
        def segment_pace(group):
            dist=sum(float(x['distance_m']) for x in group)
            return sum(float(x['timer_s']) for x in group)*100/dist if dist else None
        first_pace=segment_pace(first);last_pace=segment_pace(second)
        drift=(last_pace-first_pace)/first_pace*100 if first_pace and last_pace else None
        history.append({'id':a['activity_id'],'date':a['activity_date'],'distance':total,'seconds':secs,
                        'pace':secs*100/total,'stroke':stroke_rate,'swolf':swolf,'drift':drift,
                        'lengths':len(lengths)})
    return history

def swim_trends():
    history=swim_history()
    if not history:return 'No Garmin pool lengths found. Run /garminsync first.'
    latest=history[0]
    def pace_str(v):
        n=round(v)
        return str(n//60)+':'+str(n%60).zfill(2)+'/100m'
    def fmt(v,unit=''):
        return f'{v:.1f}{unit}' if v is not None else 'n/a'
    lines=['SWIM TRENDS — Garmin FIT','Imported pool swims: '+str(len(history))+' (up to 12 most recent)',
           'LATEST: '+str(latest['date'])+' | '+str(round(latest['distance']))+'m | '+pace_str(latest['pace']),
           'Strokes/length '+fmt(latest['stroke'])+' | SWOLF '+fmt(latest['swolf'])+
           ' | second-half pace change '+fmt(latest['drift'],'%')]
    if len(history)<3:
        lines.append('Baseline building: at least 3 pool swims needed for trends. These are not enough to establish improvement.')
    else:
        recent=history[:min(4,len(history))]
        older=history[min(4,len(history)):]
        lines.append('RECENT SESSIONS')
        for x in recent:
            lines.append(str(x['date'])+' '+str(round(x['distance']))+'m | '+pace_str(x['pace'])+' | strokes '+fmt(x['stroke'])+' | SWOLF '+fmt(x['swolf']))
        if older:
            # Compare at similar paces and same pool length, to reduce misleading SWOLF comparisons.
            similar=[x for x in older if abs(x['pace']-latest['pace'])/latest['pace']<=0.05 and
                     abs(x['distance']-latest['distance'])/latest['distance']<=0.25 and x['stroke'] is not None]
            if similar and latest['stroke'] is not None:
                baseline=statistics.median(x['stroke'] for x in similar)
                lines.append('MATCHED-SESSION BENCHMARK ('+str(len(similar))+' older swim(s), pace within 5%, distance within 25%):')
                lines.append('Strokes/length '+fmt(latest['stroke'])+' vs baseline '+fmt(baseline)+
                             ' ('+fmt(latest['stroke']-baseline,' strokes')+'). Lower may indicate more distance per stroke at similar pace.')
            else:lines.append('No comparable older swims yet (pace ±5%, distance ±25%); avoiding misleading efficiency comparisons.')
        else:lines.append('More history needed for a matched-session baseline.')
    lines.append('COACHING NOTE')
    if latest['drift'] is not None and latest['drift']>5:
        lines.append('Second half >5% slower. Consider even-paced aerobic repeats with generous recovery; assess fatigue, technique and rests before changing intensity.')
    elif latest['drift'] is not None and latest['drift']<-5:
        lines.append('Second half >5% faster. Review pacing: a steadier first half may help on continuous swims.')
    else:lines.append('Pacing looks reasonably consistent by recorded active-length times. Maintain technique and gradually build comparable sessions.')
    lines.append('These are descriptive trends, not fatigue diagnoses. FIT active-length times exclude rest; pool size, drills and stroke type affect SWOLF.')
    return '\n'.join(lines)[:3800]

def garmin_recent():
    if not env('GARMIN_PERSONAL_API_KEY'):return 'Garmin not configured. Add GARMIN_PERSONAL_API_KEY in Vercel Production settings.'
    try:
        token=garmin_token()
        path='/activitylist-service/activities/search/activities?'+urllib.parse.urlencode({'start':0,'limit':5})
        data=garmin_api(path,token)
        if not isinstance(data,list):return 'Garmin connected, but activity list format was unexpected.'
        lines=['GARMIN CONNECTED — latest activities']
        for a in data:
            typ=a.get('activityType') or {}
            typ=typ.get('typeKey','unknown') if isinstance(typ,dict) else str(typ)
            name=str(a.get('activityName') or 'Activity').replace('\n',' ')[:65]
            lines.append(str(a.get('startTimeLocal') or a.get('startTimeGMT') or 'Unknown date')[:16]+' · '+name+' · '+typ+' · ID '+str(a.get('activityId')))
        return '\n'.join(lines) if data else 'Garmin connected. No activities returned.'
    except urllib.error.HTTPError as exc:
        print('Garmin API HTTP error',exc.code)
        return 'Garmin connection failed (HTTP '+str(exc.code)+'). Check the API key and Vercel logs.'
    except Exception as exc:
        print('Garmin connection failed',type(exc).__name__)
        return 'Garmin connection test failed. Check Vercel logs.'

# Strava single-user OAuth and scheduled import. Tokens remain server-side in Supabase.
BASE='https://www.strava.com'
def strava_api(path, token=None, payload=None):
    headers={'Authorization':'Bearer '+token} if token else {}
    if payload is not None:
        body=urllib.parse.urlencode(payload).encode()
        request=urllib.request.Request(BASE+path,data=body,headers={'Content-Type':'application/x-www-form-urlencoded',**headers})
    else: request=urllib.request.Request(BASE+path,headers=headers)
    with urllib.request.urlopen(request,timeout=15) as r:return json.loads(r.read())
def strava_token():
    rows=db('strava_connections',query='?id=eq.1&select=*')
    if not rows:return None
    row=rows[0]
    if int(row['expires_at'])>int(time.time())+120:return row['access_token']
    fresh=strava_api('/oauth/token',payload={'client_id':env('STRAVA_CLIENT_ID'),'client_secret':env('STRAVA_CLIENT_SECRET'),'grant_type':'refresh_token','refresh_token':row['refresh_token']})
    db('strava_connections','PATCH',{'access_token':fresh['access_token'],'refresh_token':fresh['refresh_token'],'expires_at':fresh['expires_at']},'?id=eq.1')
    return fresh['access_token']
def kind_of(a):
    typ=(a.get('sport_type') or a.get('type') or 'Workout').lower()
    if typ=='swim':return 'swim'
    if typ in ('weighttraining','workout','crossfit','highintensityintervaltraining','functionalstrengthtraining'):return 'gym'
    if typ in ('run','trailrun','virtualrun'):return 'run'
    if typ in ('ride','virtualride','gravelride','mountainbikeride','ebikeride','emountainbikeride'):return 'bike'
    return 'other'  # Soccer, Elliptical, Yoga, Walking, etc: never silently discard

def parse_swim(description):
    """Conservative distance/intent parser. + is simultaneous, commas sequential."""
    if not description:return {'total_m':None,'sets':[],'unparsed':[]}
    sets=[];unparsed=[]
    for raw in description.splitlines():
        line=raw.strip().strip('•- ')
        if not line:continue
        line=re.sub(r'\s+', ' ',line)
        count=1; body=line
        m=re.match(r'^(\d+)\s*[x×]\s*(.*)$',body,re.I)
        if m:count=int(m.group(1));body=m.group(2).strip()
        if body.startswith('(') and body.endswith(')'):body=body[1:-1]
        pieces=[x.strip() for x in body.split(',') if x.strip()]
        parts=[];valid=True
        for piece in pieces:
            # A distance with descriptors, e.g. '200 fist + pull' means 200m combined.
            pm=re.match(r'^(\d+)\s*(?:m\b)?\s*(.*)$',piece,re.I)
            if not pm:valid=False;break
            distance=int(pm.group(1)); label=pm.group(2).strip().lower()
            if distance<1 or distance>20000:valid=False;break
            if 'skps' in label:focus='warmup/technique'
            elif any(x in label for x in ('warmup','warm-up','wu')):focus='warmup'
            elif any(x in label for x in ('cooldown','cool-down','cd')):focus='cooldown'
            elif any(x in label for x in ('sprint','hard')):focus='speed/hard'
            elif any(x in label for x in ('fist','pull','kick','drill')):focus='technique'
            elif any(x in label for x in ('mod','steady','easy')):focus='aerobic'
            else:focus='unspecified'
            parts.append({'distance_m':distance,'description':label,'focus':focus,'simultaneous':('+' in label)})
        if not valid or not parts:unparsed.append(raw);continue
        sets.append({'original':raw,'repetitions':count,'components':parts,'total_m':count*sum(x['distance_m'] for x in parts)})
    return {'total_m':sum(x['total_m'] for x in sets) if sets else None,'sets':sets,'unparsed':unparsed}

def sync_strava():
    token=strava_token()
    if not token:return None
    since=int(time.time())-45*86400
    imported=0;seen=0;updated=0;swims=0
    # Fetch all pages; the API can return short pages before the end.
    for page in range(1,11):
        acts=strava_api('/api/v3/athlete/activities?'+urllib.parse.urlencode({'after':since,'per_page':100,'page':page}),token)
        if not acts:break
        for a in acts:
            seen+=1;aid=str(a['id']);kind=kind_of(a)
            old=db('strava_imports',query='?activity_id=eq.'+aid+'&select=activity_id,description')
            if old and (kind!='swim' or old[0].get('description') is not None):continue
            date=(a.get('start_date_local') or a.get('start_date') or '')[:10]
            if not date:continue
            distance=round(a.get('distance') or 0) if kind in ('swim','run','bike') else None
            description=None;parsed=None
            if kind=='swim':
                # Summary activities do not reliably contain descriptions.
                detail=strava_api('/api/v3/activities/'+aid,token)
                description=detail.get('description') or ''
                parsed=parse_swim(description)
                swims+=1
            if old:
                db('strava_imports','PATCH',{'description':description,'swim_analysis':parsed},'?activity_id=eq.'+aid)
                updated+=1
                continue
            db('activities','POST',{'chat_id':env('TELEGRAM_CHAT_ID'),'kind':kind,'distance_m':distance,'activity_date':date,'source':'strava'})
            db('strava_imports','POST',{'activity_id':aid,'name':a.get('name','')[:500],'description':description,'swim_analysis':parsed,'sport_type':a.get('sport_type') or a.get('type'),'moving_time_s':a.get('moving_time'),'elapsed_time_s':a.get('elapsed_time'),'average_heartrate':a.get('average_heartrate'),'distance_m':distance,'activity_date':date})
            imported+=1
    return {'imported':imported,'recognized':seen,'updated':updated,'swims':swims}


# V5: on-demand lap-level Strava analytics. Fetch once, cache in Supabase.
# Strava laps are not guaranteed to correspond to pool lengths or written sets.
def pace_per_100(seconds, metres):
    if not seconds or not metres or metres<=0:return None
    pace=round(float(seconds)*100/float(metres))
    return f'{pace//60}:{pace%60:02d}/100m'

def swim_lap_analysis(activity_id, token):
    laps=strava_api('/api/v3/activities/'+urllib.parse.quote(str(activity_id),safe='')+'/laps',token)
    if not isinstance(laps,list):return {'laps':[], 'message':'No lap data returned by Strava.'}
    results=[]
    for idx,lap in enumerate(laps[:250],1):
        distance=lap.get('distance') or 0
        duration=lap.get('moving_time') or lap.get('elapsed_time') or 0
        hr=lap.get('average_heartrate')
        results.append({'lap':idx,'name':str(lap.get('name') or '')[:100], 'distance_m':round(distance,1),
            'duration_s':duration,'pace_100m':pace_per_100(duration,distance),
            'average_heartrate':round(hr) if isinstance(hr,(int,float)) else None,
            'max_heartrate':round(lap['max_heartrate']) if isinstance(lap.get('max_heartrate'),(int,float)) else None})
    paces=[float(x['duration_s'])*100/x['distance_m'] for x in results if x['distance_m']>=25 and x['duration_s']]
    hrs=[x['average_heartrate'] for x in results if x['average_heartrate'] is not None]
    return {'laps':results,'lap_count':len(laps),'pace_range': [pace_per_100(min(paces),100),pace_per_100(max(paces),100)] if paces else None,
            'hr_range':[min(hrs),max(hrs)] if hrs else None,
            'message':'Strava lap boundaries may differ from your described sets. HR is shown only where provided.'}

def swim_performance_report():
    rows=db('strava_imports',query='?sport_type=eq.Swim&order=activity_date.desc&limit=1&select=activity_id,name,activity_date,distance_m,moving_time_s,average_heartrate,lap_analysis')
    if not rows:return 'No swims imported. Send /sync first.'
    r=rows[0]; report=r.get('lap_analysis')
    if report is None:
        token=strava_token()
        if not token:return 'Strava is not connected. Send /connect.'
        try:
            report=swim_lap_analysis(r['activity_id'],token)
        except urllib.error.HTTPError as exc:
            if exc.code in (401,403):return 'Strava did not authorize lap access. Reconnect with /connect if necessary.'
            if exc.code==404:return 'Strava does not expose lap details for this swim.'
            print('Swim laps HTTP status',exc.code)
            return 'Could not retrieve swim laps right now. Try again later.'
        db('strava_imports','PATCH',{'lap_analysis':report},'?activity_id=eq.'+str(r['activity_id']))
    total=r.get('distance_m') or 0
    avg=pace_per_100(r.get('moving_time_s'),total)
    hr=r.get('average_heartrate')
    lines=[f"SWIM PERFORMANCE — {r['activity_date']}",str(r.get('name') or 'Swim'),
           f"Distance: {total:g}m | Overall moving pace: {avg or 'unavailable'} | Avg HR: {round(hr) if isinstance(hr,(int,float)) else 'unavailable'} bpm",
           f"Strava laps: {report.get('lap_count',0)}"]
    laps=report.get('laps') or []
    for lap in laps[:15]:
        lines.append(f"{lap['lap']:>2}. {lap['distance_m']:g}m · {lap['pace_100m'] or 'pace n/a'} · HR {lap['average_heartrate'] if lap['average_heartrate'] is not None else 'n/a'} bpm")
    if len(laps)>15:lines.append(f'… plus {len(laps)-15} more laps (showing first 15).')
    if not laps:lines.append('No lap-level data available for this swim.')
    lines.append('Note: pool lap boundaries and written intervals may differ; HR is not always available or reliable in water.')
    return '\n'.join(lines)

def swim_streams_diagnostic():
    """Report only stream availability and sampling resolution; never expose tokens or raw HR."""
    rows=db('strava_imports',query='?sport_type=eq.Swim&order=activity_date.desc&limit=1&select=activity_id,name,activity_date,distance_m')
    if not rows:return 'No swim found. Send /sync first.'
    r=rows[0]
    token=strava_token()
    if not token:return 'Strava is not connected. Send /connect.'
    activity_id=urllib.parse.quote(str(r['activity_id']),safe='')
    path='/api/v3/activities/'+activity_id+'/streams?'+urllib.parse.urlencode({'keys':'time,distance,velocity_smooth,heartrate,cadence','key_by_type':'true'})
    try:
        streams=strava_api(path,token)
    except urllib.error.HTTPError as exc:
        if exc.code in (401,403):return 'Strava denied stream access (HTTP '+str(exc.code)+'). Check permissions or reconnect.'
        if exc.code==404:return 'Strava returned 404: streams are unavailable for this swim.'
        if exc.code==429:return 'Strava API rate limit reached. Try again later.'
        return 'Strava stream request failed (HTTP '+str(exc.code)+').'
    except Exception as exc:
        print('Swim streams diagnostic error',type(exc).__name__)
        return 'Could not fetch Strava streams right now.'
    if not isinstance(streams,dict):return 'Strava returned no keyed stream data for this swim.'
    lines=['SWIM STREAMS DIAGNOSTIC — '+str(r['activity_date']),str(r.get('name') or 'Swim'),
           'Available streams: '+(', '.join(sorted(streams.keys())) if streams else 'none')]
    for key in ('time','distance','velocity_smooth','heartrate','cadence'):
        item=streams.get(key)
        if not isinstance(item,dict):
            lines.append(key+': unavailable')
            continue
        values=item.get('data')
        if not isinstance(values,list):
            lines.append(key+': no samples')
            continue
        desc=key+': '+str(len(values))+' samples'
        if key=='time' and len(values)>1:
            try:
                diffs=[float(b)-float(a) for a,b in zip(values,values[1:]) if isinstance(a,(int,float)) and isinstance(b,(int,float)) and b>a]
                if diffs:desc+='; median interval '+str(round(statistics.median(diffs),1))+'s'
            except (TypeError,ValueError):pass
        if key=='distance' and len(values)>1:
            try:
                diffs=[float(b)-float(a) for a,b in zip(values,values[1:]) if isinstance(a,(int,float)) and isinstance(b,(int,float)) and b>a]
                if diffs:desc+='; median positive step '+str(round(statistics.median(diffs),1))+'m'
            except (TypeError,ValueError):pass
        lines.append(desc)
    lines.append('This checks stream availability, not Garmin pool-length boundaries, stroke counts or SWOLF.')
    return '\n'.join(lines)


# v5.2: Strava stream-based estimated splits (not Garmin pool lengths).
def swim_analysis():
    rows=db('strava_imports',query='?sport_type=eq.Swim&order=activity_date.desc&limit=1&select=activity_id,name,activity_date,distance_m')
    if not rows:return 'No swim found. Send /sync first.'
    r=rows[0];token=strava_token()
    if not token:return 'Strava is not connected. Send /connect.'
    path='/api/v3/activities/'+urllib.parse.quote(str(r['activity_id']),safe='')+'/streams?'+urllib.parse.urlencode({'keys':'time,distance,heartrate','key_by_type':'true'})
    try: streams=strava_api(path,token)
    except urllib.error.HTTPError as exc:
        if exc.code==429:return 'Strava rate limit reached. Try again later.'
        return 'Could not retrieve swim streams (HTTP '+str(exc.code)+').'
    except Exception:return 'Could not retrieve swim streams right now.'
    if not isinstance(streams,dict):return 'No usable Strava stream data.'
    t=(streams.get('time') or {}).get('data') or []
    d=(streams.get('distance') or {}).get('data') or []
    h=(streams.get('heartrate') or {}).get('data') or []
    if len(t)<2 or len(t)!=len(d):return 'Time/distance streams are missing or misaligned.'
    try:
        samples=[(float(x),float(y)) for x,y in zip(t,d)]
    except (TypeError,ValueError):return 'Streams contain nonnumeric samples.'
    if any(samples[i][0]<=samples[i-1][0] or samples[i][1]<samples[i-1][1]-0.01 for i in range(1,len(samples))):
        return 'Stream timing or distance is non-monotonic; refusing unreliable splits.'
    total=samples[-1][1]-samples[0][1]
    if total<50:return 'Not enough distance to estimate 50 m splits.'
    # Interpolate time at each distance crossing; stationary distance includes rests.
    crossings=[samples[0][0]];target=samples[0][1]+50;idx=1
    while target<=samples[-1][1]+1e-6 and idx<len(samples):
        while idx<len(samples) and samples[idx][1]<target:idx+=1
        if idx>=len(samples):break
        t0,d0=samples[idx-1];t1,d1=samples[idx]
        if d1>d0:crossings.append(t0+(target-d0)*(t1-t0)/(d1-d0))
        target+=50
    if len(crossings)<2:return 'Unable to estimate any 50 m segments.'
    durations=[crossings[i+1]-crossings[i] for i in range(len(crossings)-1)]
    plausible=[30<=x<=180 for x in durations]
    hrs=[]
    for i in range(len(durations)):
        vals=[float(h[j]) for j,(tm,_) in enumerate(samples) if j<len(h) and isinstance(h[j],(int,float)) and h[j]>0 and crossings[i]<=tm<crossings[i+1]]
        hrs.append(round(statistics.mean(vals)) if vals else None)
    valid_durations=[v for v,ok in zip(durations,plausible) if ok]
    lines=['SWIM ANALYSIS — '+str(r['activity_date']),str(r.get('name') or 'Swim'),
           f'Estimated 50m segments: {len(durations)} | plausible durations: {sum(plausible)}/{len(plausible)}',
           'Strava distance crossings are estimates, not Garmin pool lengths. Rest periods may be included.']
    if valid_durations:
        mean=statistics.mean(valid_durations)
        lines.append('Overall estimated pace: '+str(pace_per_100(sum(valid_durations),50*len(valid_durations))))
        if len(valid_durations)>=3:
            lines.append(f'50m variability: {statistics.pstdev(valid_durations):.1f}s standard deviation; range {min(valid_durations):.1f}-{max(valid_durations):.1f}s')
    lines.append('500M BLOCKS (estimated)')
    for block in range(0,len(durations),10):
        chunk=durations[block:block+10];flags=plausible[block:block+10];heart=[x for x in hrs[block:block+10] if x is not None]
        if len(chunk)<10:continue
        pace=pace_per_100(sum(chunk),500) if all(flags) else 'unreliable'
        lines.append(f'{block*50:>4}-{(block+10)*50}m: {pace}; HR {round(statistics.mean(heart)) if heart else "n/a"} bpm')
    # Early optical HR often locks on late in water; avoid presenting it as a clinical metric.
    hr_valid=[x for x in hrs[6:] if x is not None and 90<=x<=210]
    if len(hr_valid)>=10:
        half=len(hr_valid)//2
        lines.append(f'HR trend after first 300m: {round(statistics.mean(hr_valid[:half]))} to {round(statistics.mean(hr_valid[half:]))} bpm (descriptive, not cardiac drift)')
    else:lines.append('HR trend: insufficient reliable post-warmup readings.')
    lines.append('50M SEGMENTS (estimated)')
    for i,(duration,ok,hr) in enumerate(zip(durations,plausible,hrs)):
        pace=pace_per_100(duration,50) if ok else 'unreliable'
        lines.append(f'{i+1:>2}. {pace} · HR {hr if hr is not None else "n/a"}')
    if len(durations)>=20 and all(plausible[:10]) and all(plausible[-10:]):
        lines.append('First 500m: '+str(pace_per_100(sum(durations[:10]),500))+' | Last 500m: '+str(pace_per_100(sum(durations[-10:]),500)))
    else:lines.append('First/last 500m comparison withheld due to insufficient or implausible splits.')
    lines.append('Caution: HR artefacts, rests, and distance smoothing can affect these estimates. Stroke counts and SWOLF require Garmin FIT data.')
    return '\n'.join(lines)

# Explicit daily overrides are stored separately from the original schedule.
def workout_override(chat,date):
    rows=db('workout_overrides',query='?chat_id=eq.'+qchat(chat)+'&workout_date=eq.'+date.isoformat()+'&select=kind,name,details,reason&limit=1')
    return rows[0] if rows else None

def change_workout(chat,parts,reason=''):
    if len(parts)<2:return 'Usage: /change gym a | /change gym b | /change swim | /change rest | /change reset'
    choice=' '.join(parts[1:]).strip().lower()
    if choice=='reset':
        db('workout_overrides','DELETE',query='?chat_id=eq.'+qchat(chat)+'&workout_date=eq.'+today().isoformat())
        return 'Today’s override cleared. /coach shows the original plan.'
    options={'gym a':DAYS[1],'gym b':DAYS[4],'swim':DAYS[5],'rest':DAYS[2]}
    if choice not in options:return 'Choose /change gym a, /change gym b, /change swim, /change rest or /change reset.'
    name,kind,details=options[choice]
    db('workout_overrides','POST',{'chat_id':str(chat),'workout_date':today().isoformat(),'kind':kind,'name':name,'details':details,'reason':reason[:300]},'?on_conflict=chat_id,workout_date')
    return 'Today changed to '+name+'. Original schedule retained. Use /coach for the updated recommendation or /change reset to undo. This does not automatically reschedule a missed swim.'

def swim_report():
    rows=db('strava_imports',query='?sport_type=eq.Swim&order=activity_date.desc&limit=5&select=name,activity_date,distance_m,swim_analysis')
    if not rows:return 'No imported swims yet. Send /sync first.'
    lines=['RECENT SWIMS — parsed descriptions']
    for r in rows:
        parsed=r.get('swim_analysis') or {}
        parts=parsed.get('sets') or []
        distance=parsed.get('total_m')
        focus={}
        for group in parts:
            for part in group['components']:
                category=part['focus'];focus[category]=focus.get(category,0)+part['distance_m']*group['repetitions']
        summary=', '.join(f'{k} {v}m' for k,v in focus.items()) or 'No structured description'
        lines.append(f"{r.get('activity_date')}: {r.get('name') or 'Swim'} | Strava {r.get('distance_m') or 0}m | notes {distance if distance is not None else '?'}m\n{summary}"+(f" | {len(parsed.get('unparsed',[]))} lines need review" if parsed.get('unparsed') else ''))
    return '\n\n'.join(lines)
def oauth_state():
    stamp=str(int(time.time())); sig=hmac.new(env('TELEGRAM_WEBHOOK_SECRET').encode(),stamp.encode(),hashlib.sha256).hexdigest()
    return stamp+'.'+sig
def valid_state(value):
    try:
        stamp,sig=value.split('.',1)
        if abs(time.time()-int(stamp))>900:return False
        expected=hmac.new(env('TELEGRAM_WEBHOOK_SECRET').encode(),stamp.encode(),hashlib.sha256).hexdigest()
        return hmac.compare_digest(sig,expected)
    except (ValueError,AttributeError):return False

def today(): return datetime.datetime.now(TZ).date()
def plan(date):
    start=datetime.date.fromisoformat(env('PROGRAM_START_DATE') or '2026-11-16')
    week=max(1,(date-start).days//7+1)
    name,kind,details=DAYS[date.weekday()]
    if week<=3:
        restriction='Knee protection: avoid hard runs, rides and heavy leg work. Stop/scale back if symptoms increase or persist next day.'
    else:
        restriction='Reintroduce lower-body training only if symptoms and clinician guidance allow; no automatic clearance.'
    return week,name,kind,details,restriction

def message_today(date):
    week,name,kind,details,restriction=plan(date)
    return f'🏊 ATHLETE OS | Week {week}/12\n{date:%a %d %b}\n\nTODAY: {name}\n{details}\n\n{restriction}\n\nNutrition: ~145g protein; initial calorie trial ~2200–2400 kcal/day, adjust by trends and recovery.\n\nLog: /done swim 2800 | /done gym | /weight 75.0 | /knee 0'

def bar(value,target,width=10):
    n=max(0,min(width,round(width*value/target))) if target else 0
    return '█'*n+'░'*(width-n)+f' {round(100*value/target) if target else 0}%'

def training_context(date):
    monday=date-datetime.timedelta(days=date.weekday())
    recent=date-datetime.timedelta(days=7)
    rows=db('activities',query='?chat_id=eq.'+urllib.parse.quote(env('TELEGRAM_CHAT_ID'))+'&activity_date=gte.'+recent.isoformat()+'&activity_date=lte.'+date.isoformat()+'&select=kind,distance_m,activity_date,source')
    week=[r for r in rows if r['activity_date']>=monday.isoformat()]
    swim=sum(r.get('distance_m') or 0 for r in week if r['kind']=='swim')
    gym=sum(1 for r in week if r['kind']=='gym')
    today_rows=[r for r in rows if r['activity_date']==date.isoformat()]
    knee=db('recovery_logs',query='?chat_id=eq.'+urllib.parse.quote(env('TELEGRAM_CHAT_ID'))+'&logged_on=lte.'+date.isoformat()+'&order=logged_on.desc&limit=1&select=pain_score,logged_on')
    return {'swim':swim,'gym':gym,'today_rows':today_rows,'recent':rows,'knee':knee[0] if knee else None}

def recommend(date):
    week,name,kind,details,restriction=plan(date)
    override=workout_override(env('TELEGRAM_CHAT_ID'),date)
    if override:name,kind,details=override['name'],override['kind'],override['details']
    ctx=training_context(date)
    reasons=[];adjustment='Follow the scheduled session, adjusting effort to how you feel.'
    knee=ctx['knee']; score=knee.get('pain_score') if knee else None
    age=(date-datetime.date.fromisoformat(knee['logged_on'])).days if knee else None
    if kind=='rest':
        adjustment='Keep today as recovery; do not add intensity to chase weekly targets.'
        reasons.append('Recovery is scheduled today.')
    elif ctx['today_rows']:
        adjustment='A workout is already logged today. Prioritize recovery rather than repeating the scheduled session.'
        reasons.append('Activity already recorded today.')
    elif score is not None and age is not None and age<=3 and score>=3:
        adjustment='Knee pain was recently elevated. Avoid provoking activities; choose symptom-tolerated recovery and check with your clinician if it persists.'
        reasons.append(f'Last knee score: {score}/10 ({age} day(s) ago).')
    elif kind=='swim':
        if ctx['swim']>=8200:
            adjustment='Weekly swim target already reached. Consider a short easy technique session or recovery instead of adding volume.'
            reasons.append(f'{ctx["swim"]:,} m swimming already logged this week.')
        elif ctx['swim']>=6500:
            adjustment='You are close to your swim target. Keep the session controlled and shorten it if fatigued.'
            reasons.append(f'{ctx["swim"]:,} m swimming logged this week.')
        else:
            reasons.append(f'{ctx["swim"]:,} / 8,200 m swimming logged this week.')
    elif kind=='gym':
        if ctx['gym']>=2:
            adjustment='Two gym sessions already recorded this week. Consider mobility or an easy recovery session instead.'
        reasons.append(f'{ctx["gym"]} / 2 gym sessions logged this week.')
    if override:reasons.append('You changed today’s workout'+(': '+override['reason'] if override.get('reason') else '')+'.')
    safety=recovery_guidance(date,kind)
    if safety:
        adjustment=safety['adjustment'];reasons.extend(safety['reasons'])
    if not knee:reasons.append('No knee pain score logged yet; use /knee 0–10 to improve safety checks.')
    elif age is not None and age>3:reasons.append(f'Last knee score is {age} days old; log an updated score if symptoms changed.')
    return {'week':week,'name':name,'kind':kind,'details':details,'restriction':restriction,'adjustment':adjustment,'reasons':reasons,'context':ctx,'override':override}

def coach_message(date):
    rec=recommend(date); ctx=rec['context']
    return (f'🦄 ATHLETE OS | Week {rec["week"]}/12 | {date:%a %d %b}\n\n'
      f'PLAN: {rec["name"]}\n{rec["details"]}\n\n'
      f'COACH RECOMMENDS\n{rec["adjustment"]}\n\n'
      f'WHY\n'+'\n'.join('• '+r for r in rec['reasons'])+'\n\n'
      f'WEEKLY PROGRESS\n🏊 {ctx["swim"]:,} / 8,200 m\n{bar(ctx["swim"],8200)}\n'
      f'🏋️ {ctx["gym"]} / 2 gym\n{bar(ctx["gym"],2)}\n\n'
      f'{rec["restriction"]}\n\nYour actual workout will be read from Strava after sync. /coach refreshes this recommendation.')

def save_recommendation(date, message):
    # Persist exactly what was recommended for later comparison with actual workouts.
    rec=recommend(date)
    db('coaching_recommendations','POST',{'chat_id':env('TELEGRAM_CHAT_ID'),'recommendation_date':date.isoformat(),
       'planned_kind':rec['kind'],'planned_name':rec['name'],'planned_details':rec['details'],
       'recommendation':rec['adjustment'],'reasoning':rec['reasons'],'message':message},
       '?on_conflict=chat_id,recommendation_date')

def daily_coach(date):
    message=coach_message(date)
    save_recommendation(date,message)
    return message

def handle(text,chat_id):
    text=(text or '').strip(); parts=text.split(); cmd=parts[0].split('@')[0].lower() if parts else ''
    if cmd in ('/start','/help'):
        return 'Athlete OS 🦄\n/today — prescribed workout\n/plan — weekly schedule\n/progress — this week\n/weight 74.8 — log weight\n/knee 0 — pain score 0–10\n/done swim 2800 — log completed swim\n/done gym — log completed gym\n/sync — import Strava workouts\n/swims — analyze recent swim sets\n/swimdetail — latest swim laps, pace and HR\n/swimstreams — check Strava stream resolution\n/swimanalysis — Garmin FIT swim metrics (Strava fallback)\n/swimtrends — Garmin efficiency and pacing trends\n/change gym a | gym b | swim | rest | reset — override today\n/coach — adaptive recommendation + progress bars\n/connect — authorize Strava\n/checkin fatigue 3 sleep 7 knee 1 achilles 0 — recovery\n/waist 82 — waist in cm\n/trend — weight and waist trend\n/compare — planned vs actual\n/dashboard — weekly PNG\n/runstatus — return-to-run status\n/clearance yes — record clinician clearance\n/clearance no — revoke clearance\n/help — commands'
    extra=handle_v4(text,chat_id,cmd,parts)
    if extra is not None:return extra
    if cmd=='/today': return coach_message(today())
    if cmd=='/coach': return daily_coach(today())
    if cmd=='/change':return change_workout(chat_id,parts)
    if cmd=='/swimtrends':return swim_trends()
    if cmd=='/garminsync':return garmin_sync(5)
    if cmd=='/swimanalysis':return garmin_swim_report() or swim_analysis()
    if cmd=='/garmin':return garmin_recent()
    if cmd=='/plan':
        return 'WEEKLY PLAN\n'+'\n'.join(f'{i+1}. {x[0]}' for i,x in enumerate(DAYS))+'\n\nWeeks 1–3: no hard running, cycling or heavy leg training.'
    if cmd=='/connect':
        if not all(env(k) for k in ('STRAVA_CLIENT_ID','STRAVA_CLIENT_SECRET','TELEGRAM_WEBHOOK_SECRET')):return 'Strava credentials are missing in Vercel.'
        url=BASE+'/oauth/authorize?'+urllib.parse.urlencode({'client_id':env('STRAVA_CLIENT_ID'),'redirect_uri':'https://'+env('APP_DOMAIN')+'/api/strava/callback','response_type':'code','approval_prompt':'auto','scope':'read,activity:read_all','state':oauth_state()})
        return 'Open this private authorization link to connect Strava (expires in 15 minutes):\n'+url
    if cmd=='/sync':
        try:
            result=sync_strava()
            if result is None:return 'Strava is not connected. Send /connect first.'
            return f"Strava synced: {result['imported']} new workouts; {result['recognized']} total activities found in the last 45 days; {result['updated']} existing swim descriptions backfilled. Try /swims and /progress."
        except Exception as e:
            print('Strava sync failed',type(e).__name__)
            return 'Strava sync failed. Check Vercel logs and Strava configuration.'
    if cmd=='/swims':
        return swim_report()
    if cmd=='/swimstreams':
        return swim_streams_diagnostic()
    if cmd in ('/swimdetail','/laps'):
        return swim_performance_report()
    if cmd=='/weight':
        if len(parts)!=2: return 'Usage: /weight 74.8'
        try: value=float(parts[1]); assert 35<=value<=250
        except (ValueError,AssertionError): return 'Please enter a plausible weight in kg, e.g. /weight 75.0'
        db('body_metrics','POST',{'chat_id':str(chat_id),'weight_kg':value,'logged_on':today().isoformat()})
        return f'Weight logged: {value:.1f} kg. Compare weekly averages rather than single days.'
    if cmd=='/knee':
        if len(parts)!=2: return 'Usage: /knee 0 (0–10 pain score)'
        try: value=int(parts[1]); assert 0<=value<=10
        except (ValueError,AssertionError): return 'Use a whole number from 0 to 10.'
        db('recovery_logs','POST',{'chat_id':str(chat_id),'pain_score':value,'logged_on':today().isoformat()})
        return ('Knee score logged. Reduce activity and contact your clinician if pain is increasing, swelling or instability develops.' if value>=3 else 'Knee score logged. Continue cautiously and monitor the following day.')
    if cmd=='/done':
        if len(parts)<2 or parts[1].lower() not in ('swim','gym','run','bike'): return 'Usage: /done swim 2800 OR /done gym'
        kind=parts[1].lower(); distance=None
        if kind=='swim':
            if len(parts)<3: return 'Usage: /done swim 2800 (metres)'
            try: distance=int(parts[2]); assert 100<=distance<=20000
            except (ValueError,AssertionError): return 'Use a plausible swim distance in metres.'
        db('activities','POST',{'chat_id':str(chat_id),'kind':kind,'distance_m':distance,'activity_date':today().isoformat(),'source':'telegram'})
        return f'Logged {kind}'+(f' — {distance}m' if distance else '')+'. Great work.'
    if cmd=='/progress':
        start=today()-datetime.timedelta(days=today().weekday())
        rows=db('activities',query='?chat_id=eq.'+urllib.parse.quote(str(chat_id))+'&activity_date=gte.'+start.isoformat()+'&select=kind,distance_m')
        swim=sum((r.get('distance_m') or 0) for r in rows if r['kind']=='swim')
        gym=sum(1 for r in rows if r['kind']=='gym')
        return f'THIS WEEK\nSwim: {swim:,} / ~8,200 m\nGym: {gym} / 2 sessions\n\nBased on activities logged in Athlete OS. Strava activities are included after /sync or the daily scheduled import.'
    if not text.startswith('/') and re.search(r'\b(?:can.t swim|cannot swim|pool (?:is )?closed|rather (?:do|go to) (?:the )?gym|switch to (?:the )?gym)\b',text.lower()):
        return change_workout(chat_id,['/change','gym','a'],'Swim unavailable; requested gym')
    return natural_recovery(text,chat_id) if not text.startswith('/') else 'Unknown command. Try /help.'


# V4: no public access; all records remain private in service-role Supabase tables.
def qchat(chat):return urllib.parse.quote(str(chat),safe='')
def latest_checkin(date=None):
    date=date or today()
    rows=db('wellness_checkins',query='?chat_id=eq.'+qchat(env('TELEGRAM_CHAT_ID'))+'&logged_on=lte.'+date.isoformat()+'&order=logged_on.desc,created_at.desc&limit=1&select=*')
    return rows[0] if rows else None

def recovery_guidance(date,kind):
    r=latest_checkin(date)
    if not r:return None
    age=(date-datetime.date.fromisoformat(r['logged_on'])).days
    if age>2:return None
    reasons=[]
    if r.get('fatigue') is not None and r['fatigue']>=4:reasons.append('Recent fatigue '+str(r['fatigue'])+'/5.')
    if r.get('sleep_hours') is not None and float(r['sleep_hours'])<6:reasons.append('Recent sleep under six hours.')
    if r.get('knee_pain') is not None and r['knee_pain']>=3:reasons.append('Knee symptoms elevated ('+str(r['knee_pain'])+'/10).')
    if r.get('achilles_pain') is not None and r['achilles_pain']>=3:reasons.append('Achilles symptoms elevated ('+str(r['achilles_pain'])+'/10).')
    if r.get('injury_note'):reasons.append('An injury/symptom report was logged; do not increase impact loading without assessment.')
    if reasons:return {'adjustment':'Prioritize rest or easy symptom-tolerated movement today. Avoid intensity or impact progression; seek clinical advice for new or worsening symptoms.','reasons':reasons}
    return None

def log_checkin(chat,values):
    payload={'chat_id':str(chat),'logged_on':today().isoformat(),**values}
    db('wellness_checkins','POST',payload)
    return 'Recovery check-in saved. /coach will consider this report. For new, severe, worsening or persistent symptoms, consult a clinician; urgent symptoms need prompt medical care.'

def natural_recovery(text,chat):
    t=text.lower()
    injury_words=('injur','hurt','pain','swollen','swelling','sprain','tendon','achilles','knee','limp','sore')
    fatigue_words=('fatigue','exhaust','tired','poor sleep','slept','sleepy','drained')
    if not any(w in t for w in injury_words+fatigue_words):return 'I can log fatigue, sleep or injury symptoms. Try /checkin fatigue 4 sleep 5 knee 2 achilles 1, or describe how you feel.'
    values={'injury_note':text[:1000]}
    m=re.search(r'(?:slept|sleep)\s*(?:for\s*)?(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|h)\b',t)
    if m:values['sleep_hours']=min(24,float(m.group(1)))
    m=re.search(r'(?:fatigue|tiredness)\s*(?:is|:|=)?\s*(\d)\s*(?:/5)?',t)
    if m and 1<=int(m.group(1))<=5:values['fatigue']=int(m.group(1))
    for label,col in (('knee','knee_pain'),('achilles','achilles_pain')):
        m=re.search(label+r'\s*(?:pain|is|:|=)?\s*(\d{1,2})\s*(?:/10)?',t)
        if m and int(m.group(1))<=10:values[col]=int(m.group(1))
    log_checkin(chat,values)
    if any(w in t for w in injury_words):
        return 'I logged your symptom report. Please tell me the location, pain 0–10, whether there is swelling, and what movements trigger it. I will recommend avoiding aggravating loads; I cannot diagnose or clear you to run. Sudden severe pain, inability to bear weight, fever with a hot swollen joint, or significant calf swelling warrants prompt medical assessment.'
    return 'I logged your fatigue/sleep report. Today, prioritize recovery and avoid hard training if you feel unusually exhausted. Use /coach for an adjusted recommendation; /checkin can record precise scores.'

def weight_trend(chat):
    rows=db('body_metrics',query='?chat_id=eq.'+qchat(chat)+'&order=logged_on.desc,created_at.desc&limit=90&select=weight_kg,logged_on')
    cutoff=today()-datetime.timedelta(days=7)
    recent=[float(r['weight_kg']) for r in rows if datetime.date.fromisoformat(r['logged_on'])>=cutoff]
    older=[float(r['weight_kg']) for r in rows if cutoff-datetime.timedelta(days=7)<=datetime.date.fromisoformat(r['logged_on'])<cutoff]
    w=db('waist_measurements',query='?chat_id=eq.'+qchat(chat)+'&order=logged_on.desc,created_at.desc&limit=2&select=waist_cm,logged_on')
    msg='BODY COMPOSITION\n'
    msg+='Weight 7-day average: '+(f'{statistics.mean(recent):.2f} kg' if recent else 'not enough recent entries')+'\n'
    if older and recent:msg+=f'Change vs previous 7 days: {statistics.mean(recent)-statistics.mean(older):+.2f} kg\n'
    msg+='Waist: '+(f"{float(w[0]['waist_cm']):.1f} cm ({w[0]['logged_on']})" if w else 'not logged')
    if len(w)>1:msg+=f"; change {float(w[0]['waist_cm'])-float(w[1]['waist_cm']):+.1f} cm"
    return msg+'\nLog weight 3 mornings/week and waist every 2 weeks, consistently.'

def run_status(chat):
    rows=db('running_clearance',query='?chat_id=eq.'+qchat(chat)+'&select=*')
    r=rows[0] if rows else None
    if not r or not r.get('clinician_cleared'):
        return 'RETURN TO RUN: ON HOLD. Record clinician guidance with /clearance yes only after your clinician explicitly clears impact running. HA injection does not automatically establish readiness. Continue prescribed rehab and symptom monitoring.'
    latest=latest_checkin()
    if not latest:return 'Clinician clearance recorded, but a current knee/Achilles check-in is needed before planning run/walk. Use /checkin knee 0 achilles 0 fatigue 2 sleep 7.'
    age=(today()-datetime.date.fromisoformat(latest['logged_on'])).days
    if age>1:return 'Please log a current knee/Achilles check-in before considering run/walk.'
    if latest.get('knee_pain') is None or latest.get('achilles_pain') is None:return 'Please record both knee and Achilles scores before run/walk.'
    if latest['knee_pain']>1 or latest['achilles_pain']>1 or latest.get('injury_note'):
        return 'Running progression paused because symptoms were reported. Discuss return-to-run readiness with your clinician.'
    return 'Clinician clearance recorded and current symptoms low. If your clinician also approved a graded progression, discuss an easy run/walk starting point; do not add speed work, and reassess symptoms during and the next morning. /runcheck knee 0 achilles 0 logs next-morning response.'

def compare_day(chat,date):
    d=date.isoformat()
    plans=db('coaching_recommendations',query='?chat_id=eq.'+qchat(chat)+'&recommendation_date=eq.'+d+'&limit=1&select=planned_kind,planned_name,planned_details,recommendation')
    acts=db('activities',query='?chat_id=eq.'+qchat(chat)+'&activity_date=eq.'+d+'&select=kind,distance_m,source')
    swims=db('strava_imports',query='?activity_date=eq.'+d+'&sport_type=eq.Swim&select=distance_m,swim_analysis,name')
    if not plans:return 'No saved recommendation for '+d+'. Use /coach to save today’s recommendation.'
    p=plans[0]; out=['PLAN VS ACTUAL — '+d,'Prescribed: '+p['planned_name'],'Coach: '+p['recommendation']]
    if not acts:out.append('Actual: no activities imported/logged for this date (not proof of rest).')
    else:
        out.append('Actual: '+', '.join(a['kind']+(f" {a['distance_m']}m" if a.get('distance_m') else '') for a in acts))
        planned_kind=p['planned_kind']
        if planned_kind=='rest':out.append('Difference: activity logged on a planned recovery day.' )
        elif not any(a['kind']==planned_kind for a in acts):out.append('Difference: planned activity type not observed.')
        else:out.append('Activity type matched. Workout details may differ from the prescription.')
    for sw in swims:
        parsed=sw.get('swim_analysis') or {}
        if parsed.get('total_m') is not None:
            out.append(f"Swim notes: {parsed['total_m']}m vs Strava {sw.get('distance_m') or 0}m; see /swims for intensity breakdown.")
    return '\n'.join(out)+'\nComparison is descriptive, not a compliance score; missing notes remain unknown.'

def handle_v4(text,chat,cmd,parts):
    if cmd=='/waist':
        if len(parts)!=2:return 'Usage: /waist 82.5 (cm)'
        try:v=float(parts[1]);assert 40<=v<=200
        except (ValueError,AssertionError):return 'Enter waist in cm, e.g. /waist 82.5'
        db('waist_measurements','POST',{'chat_id':str(chat),'waist_cm':v,'logged_on':today().isoformat()})
        return f'Waist logged: {v:.1f} cm. Repeat in two weeks under similar conditions.'
    if cmd=='/trend':return weight_trend(chat)
    if cmd=='/checkin' or cmd=='/runcheck':
        if len(parts)<3 or len(parts)%2!=1:return 'Usage: /checkin fatigue 3 sleep 7 knee 1 achilles 0 (fatigue 1–5, pain 0–10, sleep hours)'
        cols={'fatigue':'fatigue','sleep':'sleep_hours','knee':'knee_pain','achilles':'achilles_pain'};values={}
        try:
            for i in range(1,len(parts),2):
                key=parts[i].lower();assert key in cols
                val=float(parts[i+1]);assert (1<=val<=5 if key=='fatigue' else 0<=val<=24 if key=='sleep' else 0<=val<=10)
                values[cols[key]]=val if key=='sleep' else int(val)
        except (ValueError,AssertionError):return 'Invalid check-in. Try /checkin fatigue 3 sleep 7 knee 1 achilles 0.'
        return log_checkin(chat,values)
    if cmd=='/runstatus':return run_status(chat)
    if cmd=='/clearance':
        if len(parts)!=2 or parts[1].lower() not in ('yes','no'):return 'Usage: /clearance yes (only after clinician approval) or /clearance no'
        cleared=parts[1].lower()=='yes'
        db('running_clearance','POST',{'chat_id':str(chat),'clinician_cleared':cleared,'cleared_on':today().isoformat() if cleared else None},'?on_conflict=chat_id')
        return ('Clinician clearance recorded. This is not automatic running authorization; use /runstatus and follow clinician restrictions.' if cleared else 'Running clearance revoked; running progression on hold.')
    if cmd=='/compare':
        if len(parts)>1:
            try:d=datetime.date.fromisoformat(parts[1])
            except ValueError:return 'Usage: /compare 2026-11-11'
        else:d=today()
        return compare_day(chat,d)
    if cmd=='/dashboard':
        send_weekly_dashboard(today(),chat)
        return 'Weekly dashboard sent as an image.'
    return None

def dashboard_png(date,chat):
    from PIL import Image,ImageDraw,ImageFont
    monday=date-datetime.timedelta(days=date.weekday());start=monday-datetime.timedelta(days=21)
    rows=db('activities',query='?chat_id=eq.'+qchat(chat)+'&activity_date=gte.'+start.isoformat()+'&activity_date=lte.'+date.isoformat()+'&select=kind,distance_m,activity_date')
    weeks=[]
    for i in range(4):
        d=start+datetime.timedelta(days=7*i)
        w=[r for r in rows if d.isoformat()<=r['activity_date']<(d+datetime.timedelta(days=7)).isoformat()]
        weeks.append((d,sum(r.get('distance_m') or 0 for r in w if r['kind']=='swim'),sum(r['kind']=='gym' for r in w)))
    img=Image.new('RGB',(1000,760),'#101827');draw=ImageDraw.Draw(img)
    def font(size,bold=False):
        path='/usr/share/fonts/truetype/dejavu/DejaVuSans'+('-Bold' if bold else '')+'.ttf'
        try:return ImageFont.truetype(path,size)
        except OSError:return ImageFont.load_default()
    white='#f1f5f9';muted='#a7b3c7';teal='#2dd4bf';purple='#a78bfa'
    draw.text((56,42),'ATHLETE OS  /  WEEKLY PULSE',font=font(30,True),fill=white)
    draw.text((56,90),f'Week of {monday:%d %b %Y}  |  Singapore time',font=font(20),fill=muted)
    swim=weeks[-1][1];gym=weeks[-1][2]
    def progress(y,label,value,target,color):
        draw.text((56,y),label,font=font(25,True),fill=white)
        draw.text((690,y),f'{value:,} / {target:,}',font=font(23),fill=muted)
        draw.rounded_rectangle((56,y+44,944,y+69),radius=12,fill='#334155')
        draw.rounded_rectangle((56,y+44,56+max(1,int(888*min(1,value/target))),y+69),radius=12,fill=color)
    progress(154,'SWIM (m)',swim,8200,teal);progress(269,'GYM (sessions)',gym,2,purple)
    draw.text((56,396),'SWIM VOLUME — LAST 4 WEEKS',font=font(24,True),fill=white)
    for i,(d,m,g) in enumerate(weeks):
        x=95+i*220;h=int(min(200,m/10000*200))
        draw.rounded_rectangle((x,650-h,x+108,650),radius=9,fill=teal if i==3 else '#377e87')
        draw.text((x,665),d.strftime('%d %b'),font=font(18),fill=muted)
        draw.text((x,625-h),f'{m/1000:.1f} km',font=font(19,True),fill=white)
    draw.text((56,722),'Based on logged activities; not a medical readiness assessment.',font=font(16),fill=muted)
    buf=io.BytesIO();img.save(buf,format='PNG');return buf.getvalue()

def send_photo(chat,png,caption):
    boundary='----athleteos'+secrets.token_hex(12)
    def field(name,value):return (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n').encode()
    body=field('chat_id',str(chat))+field('caption',caption)
    body+=(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="athlete-os-weekly.png"\r\nContent-Type: image/png\r\n\r\n').encode()+png+b'\r\n'+(f'--{boundary}--\r\n').encode()
    url='https://api.telegram.org/bot'+env('TELEGRAM_BOT_TOKEN')+'/sendPhoto'
    request=urllib.request.Request(url,data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    with urllib.request.urlopen(request,timeout=20) as r:return json.loads(r.read())

def send_weekly_dashboard(date,chat=None):
    chat=chat or env('TELEGRAM_CHAT_ID')
    send_photo(chat,dashboard_png(date,chat),'Athlete OS weekly progress · /trend for body composition')

def request_route(raw_path):
    parsed=urlsplit(raw_path)
    route=parse_qs(parsed.query).get("route", [None])[0]
    return "/api/" + route if route in ("health", "daily", "telegram", "strava_callback") else parsed.path

class handler(BaseHTTPRequestHandler):
    def reply(self,code,obj):
        b=json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        path=request_route(self.path)
        if path=='/api/health': return self.reply(200,{'ok':True,'service':'athlete-os'})
        if path=='/api/strava_callback':
            q=parse_qs(urlsplit(self.path).query)
            # Vercel may pass query parameters through its rewrite alongside route.
            if not valid_state((q.get('state') or [''])[0]):return self.reply(403,{'error':'invalid or expired state; send /connect again'})
            code=(q.get('code') or [''])[0]
            if not code:return self.reply(400,{'error':'authorization denied or missing code'})
            try:
                token=strava_api('/oauth/token',payload={'client_id':env('STRAVA_CLIENT_ID'),'client_secret':env('STRAVA_CLIENT_SECRET'),'grant_type':'authorization_code','code':code})
                db('strava_connections','POST',{'id':1,'access_token':token['access_token'],'refresh_token':token['refresh_token'],'expires_at':token['expires_at'],'athlete_id':str(token.get('athlete',{}).get('id',''))})
                send(env('TELEGRAM_CHAT_ID'),'Strava connected! Send /sync to import your recent workouts.')
                return self.reply(200,{'ok':True,'message':'Strava connected. Return to Telegram and send /sync.'})
            except Exception as e:
                print('Strava OAuth callback failed',type(e).__name__)
                return self.reply(500,{'error':'connection failed; check Vercel logs'})
        if path!='/api/daily': return self.reply(404,{'error':'not found'})
        if self.headers.get('Authorization')!='Bearer '+env('CRON_SECRET') or not env('CRON_SECRET'): return self.reply(401,{'error':'unauthorized'})
        if not env('TELEGRAM_CHAT_ID'): return self.reply(500,{'error':'missing chat id'})
        try:
            sync_strava()
        except Exception as e: print('Scheduled Strava sync failed',type(e).__name__)
        try:
            if env('GARMIN_PERSONAL_API_KEY'): garmin_sync(2)
        except Exception as e: print('Scheduled Garmin sync failed',type(e).__name__)
        date=today(); key='daily:'+date.isoformat()
        prior=db('notifications',query='?notification_key=eq.'+key+'&select=id')
        if prior: return self.reply(200,{'ok':True,'status':'already sent'})
        send(env('TELEGRAM_CHAT_ID'),daily_coach(date))
        db('notifications','POST',{'notification_key':key})
        if date.weekday()==0:
            try: send_weekly_dashboard(date)
            except Exception as e: print('Weekly dashboard failed',type(e).__name__)
        return self.reply(200,{'ok':True,'status':'sent'})
    def do_POST(self):
        if request_route(self.path)!='/api/telegram': return self.reply(404,{'error':'not found'})
        if not env('TELEGRAM_WEBHOOK_SECRET') or self.headers.get('X-Telegram-Bot-Api-Secret-Token')!=env('TELEGRAM_WEBHOOK_SECRET'): return self.reply(403,{'error':'forbidden'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if size>100000: return self.reply(413,{'error':'too large'})
            update=json.loads(self.rfile.read(size)); msg=update.get('message') or {}; chat=str((msg.get('chat') or {}).get('id',''))
            if chat!=env('TELEGRAM_CHAT_ID'): return self.reply(200,{'ok':True})
            update_id=update.get('update_id')
            if update_id is None: return self.reply(200,{'ok':True})
            prior=db('processed_updates',query='?update_id=eq.'+str(int(update_id))+'&select=update_id')
            if prior: return self.reply(200,{'ok':True})
            response=handle(msg.get('text',''),chat)
            db('processed_updates','POST',{'update_id':int(update_id)})
            if response: send(chat,response)
            return self.reply(200,{'ok':True})
        except Exception as e:
            print('Webhook error',type(e).__name__,str(e)[:200]); return self.reply(500,{'error':'processing failed'})
