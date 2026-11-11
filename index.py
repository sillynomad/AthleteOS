import os, json, datetime, urllib.request, urllib.parse
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
        return 'Athlete OS 🦄\n/today — prescribed workout\n/plan — weekly schedule\n/progress — this week\n/weight 74.8 — log weight\n/knee 0 — pain score 0–10\n/done swim 2800 — log completed swim\n/done gym — log completed gym\n/sync — Garmin integration status\n/help — commands'
    if cmd=='/today': return message_today(today())
    if cmd=='/plan':
        return 'WEEKLY PLAN\n'+'\n'.join(f'{i+1}. {x[0]}' for i,x in enumerate(DAYS))+'\n\nWeeks 1–3: no hard running, cycling or heavy leg training.'
    if cmd=='/sync': return 'Garmin automatic sync is not connected yet. Activities can be logged with /done swim 2800 or /done gym. Do not share Garmin credentials in Telegram.'
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
        return f'THIS WEEK\nSwim: {swim:,} / ~8,200 m\nGym: {gym} / 2 sessions\n\nBased on activities logged in Athlete OS. Garmin auto-import is not yet enabled.'
    return 'Unknown command. Try /help.'

def request_route(raw_path):
    parsed=urlsplit(raw_path)
    route=parse_qs(parsed.query).get("route", [None])[0]
    return "/api/" + route if route in ("health", "daily", "telegram") else parsed.path

class handler(BaseHTTPRequestHandler):
    def reply(self,code,obj):
        b=json.dumps(obj).encode(); self.send_response(code); self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(b)));self.end_headers();self.wfile.write(b)
    def do_GET(self):
        path=request_route(self.path)
        if path=='/api/health': return self.reply(200,{'ok':True,'service':'athlete-os'})
        if path!='/api/daily': return self.reply(404,{'error':'not found'})
        if self.headers.get('Authorization')!='Bearer '+env('CRON_SECRET') or not env('CRON_SECRET'): return self.reply(401,{'error':'unauthorized'})
        if not env('TELEGRAM_CHAT_ID'): return self.reply(500,{'error':'missing chat id'})
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
