import json
from urllib.parse import quote

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

async def request(session, method, url, *, params=None, json_body=None, headers=None):
    async with session.request(method, url, params=params, json=json_body, headers=headers) as r:
        data = await r.json(content_type=None) if r.status != 204 else {}
        if r.status >= 400:
            raise RuntimeError(f"Почтовый сервис вернул HTTP {r.status}: {data}")
        return data, dict(r.headers)

async def hydra_domains(session, base_url):
    result=[]
    for page in range(1,21):
        data,_=await request(session,"GET",base_url+"/domains",params={"page":page})
        items=members(data)
        for item in items:
            if not isinstance(item,dict): continue
            domain=str(item.get("domain") or "").strip().lower().lstrip("@")
            if domain and item.get("isActive",True) and not item.get("isPrivate",False):
                result.append(domain)
        try: total=int(data.get("hydra:totalItems")) if isinstance(data,dict) else None
        except (TypeError,ValueError): total=None
        if not items or (total is not None and len(result)>=total): break
    return list(dict.fromkeys(result))

async def create(provider, name, domain, session):
    name = (name or "").strip().lower()
    if provider in ("mailtm","mailgw"):
        base = "https://api.mail.gw" if provider=="mailgw" else "https://api.mail.tm"
        ds = await hydra_domains(session, base)
        dom = __import__("secrets").choice(ds) if domain in ("", "random") else domain
        if dom not in ds: raise ValueError(f"Домен {provider} недоступен")
        import secrets, string
        local = name or "".join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(13))
        address = local + "@" + dom
        password = secrets.token_urlsafe(28)
        account,_ = await request(session,"POST",base+"/accounts",json_body={"address":address,"password":password})
        auth,_ = await request(session,"POST",base+"/token",json_body={"address":address,"password":password})
        return address, {"token":auth["token"],"api_id":account["id"],"password":password,"base_url":base}, 3600
    if provider == "1secmail":
        import secrets, string
        local = name or "".join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(13))
        ds, _ = await request(session,"GET","https://www.1secmail.com/api/v1/",params={"action":"getDomainList"})
        ds = [x.strip().lower().lstrip("@") for x in ds if isinstance(x,str) and x.strip()]
        dom = secrets.choice(ds) if domain in ("","random") else domain
        if dom not in ds: raise ValueError("Домен 1secmail недоступен")
        return local+"@"+dom, {"login":local,"domain":dom}, 3600
    if provider == "besttempmail":
        body={}
        if name: body["username"]=name
        if domain not in ("","random"): body["domain"]=domain
        data,_=await request(session,"POST","https://api.best-tempmail.com/v1/inboxes",json_body=body)
        return data["address"], {}, min(7200,int(data.get("lifetime_minutes",120)*60))
    if provider == "guerrilla":
        params={"f":"get_email_address","ip":"127.0.0.1","agent":"TEMPMAIL Telegram"}
        data,headers=await request(session,"GET","https://api.guerrillamail.com/ajax.php",params=params)
        cookie=headers.get("Set-Cookie","")
        sid=cookie.split("PHPSESSID=",1)[1].split(";",1)[0] if "PHPSESSID=" in cookie else ""
        if name:
            data,_=await request(session,"GET","https://api.guerrillamail.com/ajax.php",params={"f":"set_email_user","email_user":name,"lang":"en","ip":"127.0.0.1","agent":"TEMPMAIL Telegram"},headers={"Cookie":"PHPSESSID="+sid})
        return data["email_addr"], {"sid":sid,"seq":0}, 3600
    if provider == "catchmail":
        import secrets, string
        local=name or "".join(secrets.choice(string.ascii_lowercase+string.digits) for _ in range(13))
        dom=domain if domain not in ("","random") else "catchmail.io"
        return local+"@"+dom, {}, 7200
    raise ValueError("Неизвестный почтовый сервис")

async def messages(provider,address,meta,session):
    if provider in ("mailtm","mailgw"):
        base=meta.get("base_url","https://api.mail.gw" if provider=="mailgw" else "https://api.mail.tm")
        data,_=await request(session,"GET",base+"/messages",headers={"Authorization":"Bearer "+meta["token"]})
        return [{"id":str(m["id"]),"subject":m.get("subject") or "(без темы)","from":sender_address(m.get("from")),"intro":m.get("intro",""),"created":m.get("createdAt","")} for m in members(data)]
    if provider=="1secmail":
        data,_=await request(session,"GET","https://www.1secmail.com/api/v1/",params={"action":"getMessages","login":meta["login"],"domain":meta["domain"]})
        return [{"id":str(m["id"]),"subject":m.get("subject") or "(без темы)","from":m.get("from","?"),"intro":m.get("subject",""),"created":m.get("date","")} for m in data]
    if provider=="besttempmail":
        data,_=await request(session,"GET","https://api.best-tempmail.com/v1/inboxes/"+quote(address,safe="")+"/messages")
        return [{"id":str(m["id"]),"subject":m.get("subject") or "(без темы)","from":m.get("from","?"),"intro":m.get("subject",""),"created":m.get("date","")} for m in data.get("messages",[])]
    if provider=="catchmail":
        data,_=await request(session,"GET","https://api.catchmail.io/api/v1/mailbox",params={"address":address})
        return [{"id":str(m["id"]),"subject":m.get("subject") or "(без темы)","from":m.get("from","?"),"intro":m.get("subject",""),"created":m.get("date","")} for m in data.get("messages",[])]
    if provider=="guerrilla":
        data,_=await request(session,"GET","https://api.guerrillamail.com/ajax.php",params={"f":"check_email","seq":meta.get("seq",0),"ip":"127.0.0.1","agent":"TEMPMAIL Telegram"},headers={"Cookie":"PHPSESSID="+meta["sid"]})
        items=data.get("list",[])
        if items: meta["seq"]=max(meta.get("seq",0),max(int(x.get("mail_id",0)) for x in items))
        return [{"id":str(m.get("mail_id")),"subject":m.get("mail_subject") or "(без темы)","from":m.get("mail_from","?"),"intro":m.get("mail_excerpt",""),"created":m.get("mail_timestamp","")} for m in items]
    return []

async def read(provider,address,meta,message_id,session):
    if provider in ("mailtm","mailgw"):
        base=meta.get("base_url","https://api.mail.gw" if provider=="mailgw" else "https://api.mail.tm")
        m,_=await request(session,"GET",base+f"/messages/{quote(str(message_id),safe='')}",headers={"Authorization":"Bearer "+meta["token"]})
        return {"id":str(m["id"]),"subject":m.get("subject") or "(без темы)","from":sender_address(m.get("from")),"created":m.get("createdAt",""),"text":m.get("text") or m.get("intro") or "Нет текстовой версии письма."}
    if provider=="1secmail":
        m,_=await request(session,"GET","https://www.1secmail.com/api/v1/",params={"action":"readMessage","login":meta["login"],"domain":meta["domain"],"id":message_id})
        return {"id":str(m["id"]),"subject":m.get("subject") or "(без темы)","from":m.get("from","?"),"created":m.get("date",""),"text":m.get("textBody") or m.get("body") or "Нет текстовой версии письма."}
    if provider=="besttempmail":
        d,_=await request(session,"GET","https://api.best-tempmail.com/v1/inboxes/"+quote(address,safe="")+"/messages/"+quote(message_id,safe=""))
        m=d.get("message",d)
        return {"id":str(m["id"]),"subject":m.get("subject") or "(без темы)","from":m.get("from","?"),"created":m.get("date",""),"text":m.get("text") or "Нет текстовой версии письма."}
    if provider=="catchmail":
        m,_=await request(session,"GET","https://api.catchmail.io/api/v1/message/"+quote(message_id,safe=""),params={"mailbox":address})
        body=m.get("body") or {}
        return {"id":str(m["id"]),"subject":m.get("subject") or "(без темы)","from":m.get("from","?"),"created":m.get("date",""),"text":body.get("text") or "Нет текстовой версии письма."}
    if provider=="guerrilla":
        m,_=await request(session,"GET","https://api.guerrillamail.com/ajax.php",params={"f":"fetch_email","email_id":message_id,"ip":"127.0.0.1","agent":"TEMPMAIL Telegram"},headers={"Cookie":"PHPSESSID="+meta["sid"]})
        return {"id":str(message_id),"subject":m.get("mail_subject") or "(без темы)","from":m.get("mail_from","?"),"created":m.get("mail_timestamp",""),"text":m.get("mail_body") or m.get("mail_excerpt","")}
    raise ValueError("Неизвестный сервис")

async def delete(provider, meta, session):
    if provider in ("mailtm","mailgw"):
        base=meta.get("base_url","https://api.mail.gw" if provider=="mailgw" else "https://api.mail.tm")
        await request(session,"DELETE",base+f"/accounts/{quote(str(meta['api_id']),safe='')}",headers={"Authorization":"Bearer "+meta["token"]})
