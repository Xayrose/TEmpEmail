import os, asyncio, secrets, string, time
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
def home():
    rows=[]
    if URL.startswith("https://"): rows.append([InlineKeyboardButton(text="Открыть Mini App",web_app=WebAppInfo(url=URL))])
    rows += [[InlineKeyboardButton(text="＋ Создать почту",callback_data="new")],[InlineKeyboardButton(text="▤ Мои почты",callback_data="mails")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)
async def req(method,path,token=None,payload=None):
    h={"Accept":"application/json"}
    if token:h["Authorization"]="Bearer "+token
    async with session.request(method,API+path,json=payload,headers=h) as r:
        d=await r.json(content_type=None) if r.status!=204 else {}
        if r.status>=400:raise RuntimeError(str(d.get("detail") or d.get("message") or "Mail.tm error"))
        return d
async def domains():
    d=await req("GET","/domains");return [x["domain"] for x in d.get("hydra:member",[]) if x.get("isActive") and not x.get("isPrivate")]
async def create(uid,username,domain):
    ds=await domains();domain=secrets.choice(ds) if domain=="random" else domain
    if domain not in ds:raise RuntimeError("Домен недоступен")
    address="".join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(13))+"@"+domain; password=secrets.token_urlsafe(28)
    account=await req("POST","/accounts",payload={"address":address,"password":password}); auth=await req("POST","/token",payload={"address":address,"password":password}); now=int(time.time())
    async with aiosqlite.connect(DB) as d:
        c=await d.execute("INSERT INTO inboxes(user_id,username,address,password,token,api_id,expires,created) VALUES(?,?,?,?,?,?,?,?)",(uid,username,address,password,auth["token"],account["id"],now+3600,now));await d.commit();return c.lastrowid,address
async def getboxes(uid):
    async with aiosqlite.connect(DB) as d:
        d.row_factory=aiosqlite.Row;c=await d.execute("SELECT id,address,expires FROM inboxes WHERE user_id=? AND expires>?",(uid,int(time.time())));return [dict(x) for x in await c.fetchall()]
async def getbox(bid,uid):
    async with aiosqlite.connect(DB) as d:
        d.row_factory=aiosqlite.Row;c=await d.execute("SELECT * FROM inboxes WHERE id=? AND user_id=?",(bid,uid));x=await c.fetchone();return dict(x) if x else None
async def show_domains(m):
    try:
        b=InlineKeyboardBuilder();b.button(text="🎲 Случайный домен",callback_data="domain:random")
        for x in (await domains())[:30]:b.button(text="@"+x,callback_data="domain:"+x)
        b.adjust(1);await m.answer("Выберите домен:",reply_markup=b.as_markup())
    except Exception as e:await m.answer("Ошибка: "+str(e))
async def show_boxes(chat,uid):
    xs=await getboxes(uid)
    if not xs:await bot.send_message(chat,"Активных почт пока нет.",reply_markup=home());return
    for x in xs:
        left=max(0,x["expires"]-int(time.time()))
        kb=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Входящие",callback_data=f"open:{x['id']}"),InlineKeyboardButton(text="Удалить",callback_data=f"del:{x['id']}")]])
        await bot.send_message(chat,f"📮 <code>{x['address']}</code>\nОсталось: <b>{left//60:02d}:{left%60:02d}</b>",parse_mode="HTML",reply_markup=kb)
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
@dp.callback_query(F.data.startswith("domain:"))
async def domain_cb(c):
    try:
        bid,address=await create(c.from_user.id,c.from_user.username,c.data.split(":",1)[1])
        await c.message.answer(f"✅ <b>Почта создана</b>\n<code>{address}</code>\nСрок действия: 60 минут.",parse_mode="HTML",reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Входящие",callback_data=f"open:{bid}")],[InlineKeyboardButton(text="Мои почты",callback_data="mails")]]))
    except Exception as e:await c.message.answer("Ошибка: "+str(e))
    await c.answer()
@dp.callback_query(F.data.startswith("open:"))
async def open_cb(c):
    b=await getbox(int(c.data.split(":")[1]),c.from_user.id)
    if not b or b["expires"]<=int(time.time()):await c.answer("Почта истекла",show_alert=True);return
    try:
        d=await req("GET","/messages",b["token"]);items=d.get("hydra:member",[])
        if not items:await c.message.answer("📭 Входящих пока нет.")
        for x in items[:10]:await c.message.answer(f"✉️ <b>{x.get('subject') or '(без темы)'}</b>\nОт: {x.get('from',{}).get('address','?')}\n\n{x.get('intro','')[:250]}",parse_mode="HTML")
    except Exception as e:await c.message.answer("Ошибка: "+str(e))
    await c.answer()
@dp.callback_query(F.data.startswith("del:"))
async def del_cb(c):
    b=await getbox(int(c.data.split(":")[1]),c.from_user.id)
    if b:
        try:await req("DELETE",f"/accounts/{b['api_id']}",b["token"])
        except Exception:pass
        async with aiosqlite.connect(DB) as d:await d.execute("DELETE FROM seen WHERE inbox_id=?",(b["id"],));await d.execute("DELETE FROM inboxes WHERE id=?",(b["id"],));await d.commit()
    await c.answer("Удалено");await show_boxes(c.message.chat.id,c.from_user.id)
async def main():
    global session
    os.makedirs(os.path.dirname(DB) or ".",exist_ok=True)
    async with aiosqlite.connect(DB) as d:
        await d.execute("CREATE TABLE IF NOT EXISTS inboxes(id INTEGER PRIMARY KEY,user_id INTEGER,username TEXT,address TEXT,password TEXT,token TEXT,api_id TEXT,expires INTEGER,created INTEGER)")
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
