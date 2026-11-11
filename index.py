import os, json, datetime, urllib.request, urllib.parse, urllib.error, hmac, hashlib, secrets, time
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
    return req(url,data,{'apikey':env('SUPABASE_SERVICE_ROLE_KEY'),'Authorization':'Bearer '+env('SUPABASE_SERVICE_ROLE_KEY'),'Prefer':'return=representation'},method)
def send(chat_id,message):
    return req('https://api.telegram.org/bot'+env('TELEGRAM_BOT_TOKEN')+'/sendMessage',{'chat_id':chat_id,'text':message[:3900]})

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
    typ=(a.get('sport_type') or a.get('type') or '').lower()
    if typ=='swim':return 'swim'
    if typ in ('weighttraining','workout','crossfit'):return 'gym'
    if typ in ('run','trailrun','virtualrun'):return 'run'
    if typ in ('ride','virtualride','gravelride','mountainbikeride','ebikeride'):return 'bike'
    return None
def sync_strava():
    token=strava_token()
    if not token:return None
    since=int(time.time())-45*86400
    imported=0;seen=0
    for page in range(1,5):
        acts=strava_api('/api/v3/athlete/activities?'+urllib.parse.urlencode({'after':since,'per_page':100,'page':page}),token)
        if not acts:break
        for a in acts:
            kind=kind_of(a)
            if not kind:continue
            seen+=1;aid=str(a['id'])
            old=db('strava_imports',query='?activity_id=eq.'+aid+'&select=activity_id')
            if old:continue
            date=(a.get('start_date_local') or a.get('start_date') or '')[:10]
            if not date:continue
            distance=round(a.get('distance') or 0) if kind in ('swim','run','bike') else None
            db('activities','POST',{'chat_id':env('TELEGRAM_CHAT_ID'),'kind':kind,'distance_m':distance,'activity_date':date,'source':'strava'})
            db('strava_imports','POST',{'activity_id':aid,'name':a.get('name','')[:500],'description':None,'sport_type':a.get('sport_type') or a.get('type'),'moving_time_s':a.get('moving_time'),'elapsed_time_s':a.get('elapsed_time'),'average_heartrate':a.get('average_heartrate'),'distance_m':distance,'activity_date':date})
            imported+=1
        if len(acts)<100:break
    return {'imported':imported,'recognized':seen}
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

def handle(text,chat_id):
    text=(text or '').strip(); parts=text.split(); cmd=parts[0].split('@')[0].lower() if parts else ''
    if cmd in ('/start','/help'):
        return 'Athlete OS 🦄\n/today — prescribed workout\n/plan — weekly schedule\n/progress — this week\n/weight 74.8 — log weight\n/knee 0 — pain score 0–10\n/done swim 2800 — log completed swim\n/done gym — log completed gym\n/sync — import Strava workouts\n/connect — authorize Strava\n/help — commands'
    if cmd=='/today': return message_today(today())
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
            return f"Strava synced: {result['imported']} new workouts imported; {result['recognized']} recognized in the past 45 days. /progress shows your updated totals."
        except Exception as e:
            print('Strava sync failed',type(e).__name__)
            return 'Strava sync failed. Check Vercel logs and Strava configuration.'
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
    return 'Unknown command. Try /help.'

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
        date=today(); key='daily:'+date.isoformat()
        prior=db('notifications',query='?notification_key=eq.'+key+'&select=id')
        if prior: return self.reply(200,{'ok':True,'status':'already sent'})
        send(env('TELEGRAM_CHAT_ID'),message_today(date))
        db('notifications','POST',{'notification_key':key})
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
