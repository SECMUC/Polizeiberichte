import requests, time, json, pathlib, re
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36","Accept-Language":"de-DE,de;q=0.9"}
U={
 "pm_index":"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/index.html",
 "home":"https://www.polizei.bayern.de/",
 "robots":"https://www.polizei.bayern.de/robots.txt",
 "sitemap":"https://www.polizei.bayern.de/sitemap.xml",
 "art_muc":"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/109953/index.html",
 "art_obn":"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/103055/index.html",
 "art_swn":"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/103208/index.html",
 "tg_muc":"https://t.me/s/PressePolizeiMuenchen",
 "pp_muc":"https://www.polizei.bayern.de/wir/organisation/dienststellen/ppmuc/index.html",
}
out=pathlib.Path("debug"); out.mkdir(exist_ok=True); log=[]
for k,u in U.items():
    t=time.time()
    try:
        r=requests.get(u,headers=H,timeout=25)
        log.append({"k":k,"url":u,"status":r.status_code,"sec":round(time.time()-t,2),"len":len(r.content),"final":r.url,"ct":r.headers.get("content-type")})
        (out/f"{k}.html").write_bytes(r.content[:3_000_000])
    except Exception as e:
        log.append({"k":k,"url":u,"err":repr(e),"sec":round(time.time()-t,2)})
    time.sleep(1)
(out/"log.json").write_text(json.dumps(log,indent=1))
print(json.dumps(log,indent=1))
