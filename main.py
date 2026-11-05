import os, time, json, hmac, hashlib, secrets, string, asyncio, re
from urllib.parse import parse_qsl
from contextlib import asynccontextmanager, suppress
import aiohttp, aiosqlite
import providers
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

BOT_TOKEN=os.getenv("BOT_TOKEN","").strip()
ADMIN_IDS={int(x) for x in os.getenv("ADMIN_IDS","8907694476").split(",") if x.strip().isdigit()}
DB=os.getenv("DB_PATH","data/tempmail.sqlite3")
POLL=int(os.getenv("POLL_INTERVAL","15"))
os.makedirs(os.path.dirname(DB) or ".",exist_ok=True)
http=None

def members(data):
    if isinstance(data,list): return data
    if isinstance(data,dict):
        for key in ("hydra:member","member","items","data"):
            value=data.get(key)
            if isinstance(value,list): return value
    return []
def sender_address(value):
    if isinstance(value,dict): return value.get("address","?")
    if isinstance(value,list) and value and isinstance(value[0],dict): return value[0].get("address","?")
    return "?"

async def mail(method,path,token=None,payload=None):
    headers={"Accept":"application/json"}
    if token: headers["Authorization"]="Bearer "+token
    async with http.request(method,"https://api.mail.tm"+path,json=payload,headers=headers) as r:
        data=await r.json(content_type=None) if r.status!=204 else {}
        if r.status>=400: raise RuntimeError(str((data.get("detail") or data.get("message")) if isinstance(data,dict) else data or "Mail.tm error"))
        return data

async def init_db():
    async with aiosqlite.connect(DB) as d:
        await d.execute("""CREATE TABLE IF NOT EXISTS inboxes(id INTEGER PRIMARY KEY,user_id INTEGER,username TEXT,address TEXT,password TEXT,token TEXT,api_id TEXT,expires INTEGER,created INTEGER,provider TEXT DEFAULT 'mailtm',provider_data TEXT DEFAULT '{}')""")
        cols={r[1] for r in await (await d.execute("PRAGMA table_info(inboxes)")).fetchall()}
        if "provider" not in cols: await d.execute("ALTER TABLE inboxes ADD COLUMN provider TEXT DEFAULT 'mailtm'")
        if "provider_data" not in cols: await d.execute("ALTER TABLE inboxes ADD COLUMN provider_data TEXT DEFAULT '{}'")
        await d.execute("""CREATE TABLE IF NOT EXISTS seen(inbox_id INTEGER,message_id TEXT,PRIMARY KEY(inbox_id,message_id))""")
        await d.commit()

def verify(raw):
    if not BOT_TOKEN or not raw: raise HTTPException(401,"Telegram authorization required")
    try:
        p=dict(parse_qsl(raw,keep_blank_values=True)); received=p.pop("hash")
        stamp=int(p.get("auth_date","0"))
        if abs(int(time.time())-stamp)>86400: raise ValueError()
        check="\n".join(f"{k}={v}" for k,v in sorted(p.items()))
        secret=hmac.new(b"WebAppData",BOT_TOKEN.encode(),hashlib.sha256).digest()
        expected=hmac.new(secret,check.encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,received): raise ValueError()
        u=json.loads(p["user"])
        return {"id":int(u["id"]),"username":u.get("username","")}
    except Exception: raise HTTPException(401,"Invalid Telegram session")

def user(authorization):
    if not authorization or not authorization.startswith("tma "): raise HTTPException(401,"Missing Telegram initData")
    return verify(authorization[4:])

async def domains():
    d=await mail("GET","/domains")
    return [x["domain"] for x in members(d) if isinstance(x,dict) and x.get("domain") and x.get("isActive",True) and not x.get("isPrivate",False)]

async def box_for(box_id,uid):
    async with aiosqlite.connect(DB) as d:
        d.row_factory=aiosqlite.Row
        c=await d.execute("SELECT * FROM inboxes WHERE id=? AND user_id=? AND expires>?",(box_id,uid,int(time.time())))
        x=await c.fetchone()
        if not x: raise HTTPException(404,"Почта не найдена или истекла")
        return dict(x)

async def poller():
    while True:
        try:
            async with aiosqlite.connect(DB) as d:
                d.row_factory=aiosqlite.Row
                c=await d.execute("SELECT * FROM inboxes WHERE expires>?",(int(time.time()),)); boxes=[dict(x) for x in await c.fetchall()]
            for b in boxes:
                try:
                    meta=json.loads(b.get("provider_data") or "{}")
                    items=await providers.messages(b.get("provider") or "mailtm",b["address"],meta,http)
                    async with aiosqlite.connect(DB) as d:
                        await d.execute("UPDATE inboxes SET provider_data=? WHERE id=?",(json.dumps(meta),b["id"])); await d.commit()
                    for m in items:
                        async with aiosqlite.connect(DB) as d:
                            c=await d.execute("INSERT OR IGNORE INTO seen VALUES(?,?)",(b["id"],m["id"])); await d.commit()
                            fresh=c.rowcount==1
                        if fresh:
                            msg=(f"✉️ Новое письмо\n{b['address']}\nОт: {sender_address(m.get('from'))}\nТема: {m.get('subject') or '(без темы)'}\n\n{m.get('intro','')[:600]}\nОткройте Mini App для чтения.")
                            async with http.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":b["user_id"],"text":msg}) as r: await r.read()
                except Exception as e: print("poll:",e)
                await asyncio.sleep(.12)
        except Exception as e: print("poller:",e)
        await asyncio.sleep(POLL)

async def cleanup():
    while True:
        try:
            async with aiosqlite.connect(DB) as d:
                d.row_factory=aiosqlite.Row
                c=await d.execute("SELECT * FROM inboxes WHERE expires<=?",(int(time.time()),)); rows=[dict(x) for x in await c.fetchall()]
            for b in rows:
                with suppress(Exception): await mail("DELETE",f"/accounts/{b['api_id']}",b["token"])
                async with aiosqlite.connect(DB) as d:
                    await d.execute("DELETE FROM seen WHERE inbox_id=?",(b["id"],)); await d.execute("DELETE FROM inboxes WHERE id=?",(b["id"],)); await d.commit()
                with suppress(Exception):
                    async with http.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",json={"chat_id":b["user_id"],"text":f"⌛ Срок действия {b['address']} истёк. Ящик удалён."}) as r: await r.read()
        except Exception as e: print("cleanup:",e)
        await asyncio.sleep(25)

@asynccontextmanager
async def lifespan(app):
    global http
    await init_db()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as s:
        http=s; tasks=[asyncio.create_task(poller()),asyncio.create_task(cleanup())]
        yield
        for t in tasks: t.cancel()
        for t in tasks:
            with suppress(asyncio.CancelledError): await t

app=FastAPI(title="TEMPMAIL API",docs_url=None,redoc_url=None,lifespan=lifespan)
app.mount("/static",StaticFiles(directory="static"),name="static")
@app.get("/")
async def index(): return FileResponse("static/index.html")
@app.get("/health")
async def health(): return {"status":"ok"}
@app.get("/api/me")
async def me(authorization:str|None=Header(default=None)):
    u=user(authorization); return {"user":u,"is_admin":u["id"] in ADMIN_IDS}
@app.get("/api/providers")
async def get_providers(authorization:str|None=Header(default=None)):
    user(authorization)
    return {"providers":[{"id":"mailtm","name":"Mail.tm"},{"id":"1secmail","name":"1secmail"},{"id":"besttempmail","name":"Best-TempMail"},{"id":"guerrilla","name":"Guerrilla Mail"},{"id":"catchmail","name":"Catchmail"}]}
@app.get("/api/domains")
async def get_domains(provider:str="mailtm",authorization:str|None=Header(default=None)):
    user(authorization)
    try:
        if provider=="mailtm": ds=await domains()
        elif provider=="1secmail":
            data,_=await providers.request(http,"GET","https://www.1secmail.com/api/v1/",params={"action":"getDomainList"}); ds=[x.lstrip("@") for x in data if isinstance(x,str)]
        elif provider=="catchmail": ds=["catchmail.io"]
        elif provider in ("besttempmail","guerrilla"): ds=["random"]
        else: raise ValueError("Неизвестный сервис")
        return {"domains":ds}
    except Exception as e: raise HTTPException(502,str(e))
class Create(BaseModel):
    domain:str="random"
    name:str=""
    provider:str="mailtm"
@app.post("/api/inboxes")
async def create(req:Create,authorization:str|None=Header(default=None)):
    u=user(authorization); ds=await domains()
    if not ds: raise HTTPException(502,"Нет доступных доменов")
    provider=req.provider if req.provider in ("mailtm","1secmail","besttempmail","guerrilla","catchmail") else "mailtm"
    address,meta,lifetime=await providers.create(provider,req.name,req.domain,http)
    now=int(time.time())
    async with aiosqlite.connect(DB) as d:
        c=await d.execute("INSERT INTO inboxes(user_id,username,address,password,token,api_id,expires,created,provider,provider_data) VALUES(?,?,?,?,?,?,?,?,?,?)",(u["id"],u["username"],address,"",meta.get("token",""),meta.get("api_id",""),now+lifetime,now,provider,json.dumps(meta))); await d.commit()
        return {"id":c.lastrowid,"address":address,"expires":now+lifetime,"provider":provider}
    domain=secrets.choice(ds) if req.domain=="random" else req.domain
    if domain not in ds: raise HTTPException(400,"Домен недоступен")
    name=req.name.strip().lower() or "".join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(13))
    if not re.fullmatch(r"[a-z0-9._-]{1,40}",name): raise HTTPException(400,"Имя: 1–40 символов, латинские буквы, цифры, точка, дефис или подчёркивание")
    address=name+"@"+domain
    password=secrets.token_urlsafe(28)
    account=await mail("POST","/accounts",payload={"address":address,"password":password})
    auth=await mail("POST","/token",payload={"address":address,"password":password})
    now=int(time.time())
    async with aiosqlite.connect(DB) as d:
        c=await d.execute("INSERT INTO inboxes(user_id,username,address,password,token,api_id,expires,created) VALUES(?,?,?,?,?,?,?,?)",(u["id"],u["username"],address,password,auth["token"],account["id"],now+3600,now)); await d.commit()
        return {"id":c.lastrowid,"address":address,"expires":now+3600}
@app.get("/api/inboxes")
async def list_boxes(authorization:str|None=Header(default=None)):
    u=user(authorization)
    async with aiosqlite.connect(DB) as d:
        d.row_factory=aiosqlite.Row
        c=await d.execute("SELECT id,address,expires,created FROM inboxes WHERE user_id=? AND expires>? ORDER BY id DESC",(u["id"],int(time.time())))
        return {"inboxes":[dict(x) for x in await c.fetchall()]}
@app.delete("/api/inboxes/{box_id}")
async def delete_box(box_id:int,authorization:str|None=Header(default=None)):
    u=user(authorization); b=await box_for(box_id,u["id"])
    with suppress(Exception): await mail("DELETE",f"/accounts/{b['api_id']}",b["token"])
    async with aiosqlite.connect(DB) as d:
        await d.execute("DELETE FROM seen WHERE inbox_id=?",(box_id,)); await d.execute("DELETE FROM inboxes WHERE id=?",(box_id,)); await d.commit()
    return {"ok":True}
@app.get("/api/inboxes/{box_id}/messages")
async def messages(box_id:int,authorization:str|None=Header(default=None)):
    u=user(authorization); b=await box_for(box_id,u["id"]); meta=json.loads(b.get("provider_data") or "{}"); items=await providers.messages(b.get("provider") or "mailtm",b["address"],meta,http)
    async with aiosqlite.connect(DB) as d: await d.execute("UPDATE inboxes SET provider_data=? WHERE id=?",(json.dumps(meta),box_id)); await d.commit()
    return {"messages":items[:40]}
@app.get("/api/inboxes/{box_id}/messages/{message_id}")
async def read(box_id:int,message_id:str,authorization:str|None=Header(default=None)):
    u=user(authorization); b=await box_for(box_id,u["id"]); meta=json.loads(b.get("provider_data") or "{}"); return await providers.read(b.get("provider") or "mailtm",b["address"],meta,message_id,http)
@app.get("/api/admin/stats")
async def stats(authorization:str|None=Header(default=None)):
    u=user(authorization)
    if u["id"] not in ADMIN_IDS: raise HTTPException(403,"Доступ запрещён")
    async with aiosqlite.connect(DB) as d:
        c=await d.execute("SELECT COUNT(*),COUNT(DISTINCT user_id) FROM inboxes WHERE expires>?",(int(time.time()),)); a,b=await c.fetchone()
        c=await d.execute("SELECT COUNT(*) FROM inboxes"); total=(await c.fetchone())[0]
        c=await d.execute("SELECT COUNT(*) FROM seen"); seen=(await c.fetchone())[0]
        c=await d.execute("SELECT user_id,username,COUNT(*) FROM inboxes GROUP BY user_id ORDER BY MAX(created) DESC LIMIT 30")
        users=[{"telegram_id":r[0],"username":r[1],"boxes_created":r[2]} for r in await c.fetchall()]
    return {"active_boxes":a,"active_users":b,"total_created":total,"messages_seen":seen,"users":users}
