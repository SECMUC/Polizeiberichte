import requests, json, pathlib, time
H={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36","Accept-Language":"de-DE,de;q=0.9"}
ids=["079822","084481","090393","097747","105117","110020","109981","109684","109652","109561","109976","109796","109622","110030","079373","081162","109437"]
out=pathlib.Path("debug/samples"); out.mkdir(parents=True,exist_ok=True)
for i in ids:
    r=requests.get(f"https://www.polizei.bayern.de/aktuelles/pressemitteilungen/{i}/index.html",headers=H,timeout=25)
    (out/f"{i}.html").write_bytes(r.content); print(i,r.status_code,len(r.content)); time.sleep(1)
for ch in ["PressePolizeiMuenchen","polizeioberbayernnord","polizeioberbayernsued","PolizeiOBN","PolizeiOBS","polizeibayern"]:
    r=requests.get(f"https://t.me/s/{ch}",headers=H,timeout=25)
    ok = 'tgme_widget_message' in r.text
    print("tg",ch,r.status_code,ok); 
    if ok: (out/f"tg_{ch}.html").write_bytes(r.content)
    time.sleep(1)
