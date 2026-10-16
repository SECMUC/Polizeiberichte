import requests, json, pathlib
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
   "Accept-Language":"de-DE,de;q=0.9","Content-Type":"application/json","Accept":"*/*",
   "Origin":"https://www.polizei.bayern.de","Referer":"https://www.polizei.bayern.de/suche/presse/index.html"}
out=pathlib.Path("debug"); out.mkdir(exist_ok=True); res={}
cases={
 "noauthor":{"queryStr":False,"datefr":"10.10.2026","dateto":"16.10.2026","author":""},
 "obn_og2":{"queryStr":False,"datefr":"01.06.2026","dateto":"16.10.2026","author":"0900100000000"},
 "obn_name":{"queryStr":False,"datefr":"01.06.2026","dateto":"16.10.2026","author":"Polizeipräsidium Oberbayern Nord"},
 "muc_og2_long":{"queryStr":False,"datefr":"01.01.2025","dateto":"16.10.2026","author":"0900800000000"},
}
s=requests.Session(); s.get("https://www.polizei.bayern.de/suche/presse/index.html",headers=H,timeout=20)
for k,q in cases.items():
    try:
        r=s.post("https://www.polizei.bayern.de/es/search",headers=H,data=json.dumps({"type":"presse","q":json.dumps(q)}),timeout=40)
        (out/f"es_{k}.json").write_text(r.text[:4_000_000])
        try:
            j=r.json(); hits=j.get("hits",{}); res[k]={"status":r.status_code,"total":hits.get("total"),"n":len(hits.get("hits",[]))}
        except Exception as e: res[k]={"status":r.status_code,"body":r.text[:300]}
    except Exception as e: res[k]={"err":repr(e)}
(out/"es_log.json").write_text(json.dumps(res,indent=1)); print(json.dumps(res,indent=1))
