import os, asyncio, secrets, string, time, json, html
import providers
import aiohttp, aiosqlite
from aiogram import Bot,Dispatcher,F
from aiogram.filters import CommandStart,Command
from aiogram.types import Message,InlineKeyboardMarkup,InlineKeyboardButton,WebAppInfo
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dotenv import load_dotenv
load_dotenv()
TOKEN=os.getenv("BOT_TOKEN","").strip(); URL=os.getenv("WEBAPP_URL","").strip(); URL=("https://"+URL if URL and not URL.startswith(("https://","http://")) else URL);
if URL and URL.startswith("https://") and "." not in URL.split("://",1)[1].split("/",1)[0]: URL=URL.rstrip("/")+".onrender.com/";
URL=URL.rstrip("/")+"/" if URL else URL; DB=os.getenv("DB_PATH","data/tempmail.sqlite3")
if not TOKEN: raise RuntimeError("Set BOT_TOKEN in .env")
API="https://api.mail.tm"; bot=Bot(TOKEN); dp=Dispatcher(); session=None
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
def home():
    rows=[]
    if URL.startswith("https://"): rows.append([InlineKeyboardButton(text="Открыть Mini App",web_app=WebAppInfo(url=URL))])
    rows += [[InlineKeyboardButton(text="＋ Создать почту",callback_data="new")],[InlineKeyboardButton(text="▤ Мои почты",callback_data="mails")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)
async def req(method,path,token=None,payload=None,params=None):
    h={"Accept":"application/json"}
    if token:h["Authorization"]="Bearer "+token
    async with session.request(method,API+path,json=payload,params=params,headers=h) as r:
        d=await r.json(content_type=None) if r.status!=204 else {}
        if r.status>=400:raise RuntimeError(str((d.get("detail") or d.get("message")) if isinstance(d,dict) else d or "Mail.tm error"))
        return d
async def domains():
    found=[]
    for provider,base in (("mailtm","https://api.mail.tm"),("mailgw","https://api.mail.gw")):
        try:
            found.extend((domain,provider) for domain in await providers.hydra_domains(session,base))
        except Exception as e:
            print(f"{provider} domains error: {e}",flush=True)
    try:
        data,_=await providers.request(session,"GET","https://www.1secmail.com/api/v1/",params={"action":"getDomainList"})
        if isinstance(data,list):
            found.extend((str(domain).strip().lower().lstrip("@"),"1secmail") for domain in data if isinstance(domain,str) and domain.strip())
    except Exception as e:
        print(f"1secmail domains error: {e}",flush=True)
    unique={}
    for domain,provider in found:
        unique.setdefault(domain,provider)
    return list(unique.items())

async def create(uid,username,provider,domain):
    address,meta,lifetime=await providers.create(provider,"",domain,session)
    now=int(time.time())
    async with aiosqlite.connect(DB) as d:
        c=await d.execute("INSERT INTO inboxes(user_id,username,address,password,token,api_id,expires,created,provider,provider_data) VALUES(?,?,?,?,?,?,?,?,?,?)",(uid,username,address,meta.get("password",""),meta.get("token",""),meta.get("api_id",""),now+lifetime,now,provider,json.dumps(meta)))
        await d.commit()
        return c.lastrowid,address,lifetime
async def getboxes(uid):
    async with aiosqlite.connect(DB) as d:
        d.row_factory=aiosqlite.Row;c=await d.execute("SELECT id,address,expires FROM inboxes WHERE user_id=? AND expires>?",(uid,int(time.time())));return [dict(x) for x in await c.fetchall()]
async def getbox(bid,uid):
    async with aiosqlite.connect(DB) as d:
        d.row_factory=aiosqlite.Row;c=await d.execute("SELECT * FROM inboxes WHERE id=? AND user_id=?",(bid,uid));x=await c.fetchone();return dict(x) if x else None
async def show_domains(m):
    try:
        available=(await domains())[:30]
        b=InlineKeyboardBuilder()
        b.button(text="🎲 Случайный домен",callback_data="domain:random")
        b.button(text="🟠 Guerrilla Mail · случайный адрес",callback_data="service:guerrilla")
        for domain,provider in available:b.button(text="@"+domain+" · "+provider,callback_data="domain:"+domain)
        b.adjust(1)
        if not available: await m.answer("Домены Mail.tm/Mail.gw/1secmail сейчас недоступны. Но можно попробовать Guerrilla Mail.",reply_markup=b.as_markup())
        else: await m.answer("Выберите сервис или домен:",reply_markup=b.as_markup())
    except Exception as e:await m.answer("Ошибка: "+str(e))
async def show_boxes(chat,uid):
    xs=await getboxes(uid)
    if not xs:await bot.send_message(chat,"Активных почт пока нет.",reply_markup=home());return
    for x in xs:
        left=max(0,x["expires"]-int(time.time()))
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Входящие",callback_data=f"open:{x['id']}"),InlineKeyboardButton(text="Обновить таймер",callback_data=f"timer:{x['id']}")],[InlineKeyboardButton(text="Удалить",callback_data=f"del:{x['id']}")]])
        await bot.send_message(chat,f"📮 <code>{html.escape(x['address'])}</code>\nОсталось: <b>{left//60:02d}:{left%60:02d}</b>",parse_mode="HTML",reply_markup=kb)
@dp.message(CommandStart())
async def start(m:Message):await m.answer("✉️ <b>TEMPMAIL</b>\nВременная почта на 60 минут.",parse_mode="HTML",reply_markup=home())
@dp.message(Command("app"))
async def app_cmd(m:Message):await m.answer("Откройте TEMPMAIL:",reply_markup=home())
@dp.message(Command("new"))
async def new_cmd(m:Message):await show_domains(m)
@dp.message(Command("mails"))
async def mails_cmd(m:Message):await show_boxes(m.chat.id,m.from_user.id)
@dp.message(Command("help"))
async def help_cmd(m:Message):await m.answer("/start — меню\n/new — создать адрес\n/mails — мои адреса\n/app — открыть Mini App")
@dp.callback_query(F.data=="new")
async def new_cb(c):await show_domains(c.message);await c.answer()
@dp.callback_query(F.data=="mails")
async def mails_cb(c):await show_boxes(c.message.chat.id,c.from_user.id);await c.answer()
@dp.callback_query(F.data.startswith("service:"))
async def service_cb(c):
    try:
        provider=c.data.split(":",1)[1]
        if provider!="guerrilla": raise ValueError("Неизвестный сервис")
        bid,address,lifetime=await create(c.from_user.id,c.from_user.username,provider,"")
        await c.message.answer(f"✅ <b>Почта создана через Guerrilla Mail</b>\\n<code>{html.escape(address)}</code>\\nСрок: {lifetime//60} мин.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Входящие",callback_data=f"open:{bid}")],[InlineKeyboardButton(text="Мои почты",callback_data="mails")]]))
    except Exception as e: await c.message.answer("Ошибка: "+html.escape(str(e)))
    await c.answer()
@dp.callback_query(F.data.startswith("domain:"))
async def domain_cb(c):
    try:
        selected=c.data.split(":",1)[1]
        available=await domains()
        if selected=="random":
            if not available: raise RuntimeError("Сейчас нет доступных доменов")
            domain,provider=secrets.choice(available)
        else:
            match=next(((domain,provider) for domain,provider in available if domain==selected),None)
            if not match: raise RuntimeError("Домен больше недоступен. Повторите /new.")
            domain,provider=match
        bid,address,lifetime=await create(c.from_user.id,c.from_user.username,provider,domain)
        await c.message.answer(f"✅ <b>Почта создана</b>\n<code>{html.escape(address)}</code>\nСервис: {html.escape(provider)} · Срок: {lifetime//60} мин.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Входящие",callback_data=f"open:{bid}")],[InlineKeyboardButton(text="Мои почты",callback_data="mails")]]))
    except Exception as e:await c.message.answer("Ошибка: "+str(e))
    await c.answer()
@dp.callback_query(F.data.startswith("timer:"))
async def timer_cb(c):
    b=await getbox(int(c.data.split(":")[1]),c.from_user.id)
    if not b or b["expires"]<=int(time.time()):
        await c.answer("Срок почты истёк",show_alert=True)
        return
    left=max(0,b["expires"]-int(time.time()))
    text=f"📮 <code>{html.escape(b['address'])}</code>\nОсталось: <b>{left//60:02d}:{left%60:02d}</b>"
    kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Входящие",callback_data=f"open:{b['id']}"),InlineKeyboardButton(text="Обновить таймер",callback_data=f"timer:{b['id']}")],[InlineKeyboardButton(text="Удалить",callback_data=f"del:{b['id']}")]])
    await c.message.edit_text(text,parse_mode="HTML",reply_markup=kb)
    await c.answer("Таймер обновлён")
@dp.callback_query(F.data.startswith("open:"))
async def open_cb(c):
    b=await getbox(int(c.data.split(":")[1]),c.from_user.id)
    if not b or b["expires"]<=int(time.time()):await c.answer("Почта истекла",show_alert=True);return
    try:
        meta={}
        try: meta=json.loads(b.get("provider_data") or "{}")
        except (TypeError,ValueError): pass
        if b.get("token"): meta.setdefault("token",b["token"])
        if b.get("api_id"): meta.setdefault("api_id",b["api_id"])
        items=await providers.messages(b.get("provider") or "mailtm",b["address"],meta,session)
        async with aiosqlite.connect(DB) as d:
            await d.execute("UPDATE inboxes SET provider_data=? WHERE id=?",(json.dumps(meta),b["id"]))
            await d.commit()
        if not items: await c.message.answer("📭 Входящих пока нет.")
        for x in items[:10]:
            subject=html.escape(str(x.get("subject") or "(без темы)"))
            sender=html.escape(str(x.get("from") or "?"))
            intro=html.escape(str(x.get("intro") or "")[:250])
            await c.message.answer(f"✉️ <b>{subject}</b>\nОт: {sender}\n\n{intro}",parse_mode="HTML")
    except Exception as e: await c.message.answer("Ошибка: "+html.escape(str(e)))
    await c.answer()
@dp.callback_query(F.data.startswith("del:"))
async def del_cb(c):
    b=await getbox(int(c.data.split(":")[1]),c.from_user.id)
    if b:
        meta={}
        try: meta=json.loads(b.get("provider_data") or "{}")
        except (TypeError,ValueError): pass
        if b.get("token"): meta.setdefault("token",b["token"])
        if b.get("api_id"): meta.setdefault("api_id",b["api_id"])
        try: await providers.delete(b.get("provider") or "mailtm",meta,session)
        except Exception: pass
        async with aiosqlite.connect(DB) as d:await d.execute("DELETE FROM seen WHERE inbox_id=?",(b["id"],));await d.execute("DELETE FROM inboxes WHERE id=?",(b["id"],));await d.commit()
    await c.answer("Удалено");await show_boxes(c.message.chat.id,c.from_user.id)
async def main():
    global session
    os.makedirs(os.path.dirname(DB) or ".",exist_ok=True)
    async with aiosqlite.connect(DB) as d:
        await d.execute("CREATE TABLE IF NOT EXISTS inboxes(id INTEGER PRIMARY KEY,user_id INTEGER,username TEXT,address TEXT,password TEXT,token TEXT,api_id TEXT,expires INTEGER,created INTEGER,provider TEXT DEFAULT 'mailtm',provider_data TEXT DEFAULT '{}')")
        cols={r[1] for r in await (await d.execute("PRAGMA table_info(inboxes)")).fetchall()}
        if "provider" not in cols: await d.execute("ALTER TABLE inboxes ADD COLUMN provider TEXT DEFAULT 'mailtm'")
        if "provider_data" not in cols: await d.execute("ALTER TABLE inboxes ADD COLUMN provider_data TEXT DEFAULT '{}'")
        await d.execute("CREATE TABLE IF NOT EXISTS seen(inbox_id INTEGER,message_id TEXT,PRIMARY KEY(inbox_id,message_id))");await d.commit()
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=25)) as s:
        session=s
        me=await bot.get_me()
        print(f"Telegram bot authenticated: @{me.username}",flush=True)
        await bot.delete_webhook(drop_pending_updates=False)
        print("Telegram polling starting",flush=True)
        await dp.start_polling(bot)
if __name__=="__main__":
    import logging
    logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        asyncio.run(main())
    except Exception:
        logging.exception("Telegram bot stopped unexpectedly")
        raise
