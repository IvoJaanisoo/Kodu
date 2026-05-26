"""
Spinnaker v7 — server.py
Two measures: C14=Ankurrendi reserv (KOV), C21=EIS kaaslaen
C10=D8 (horizon tracks loan term), row 18=0, C5=0.3, C8=10yr
Verified: H24=6.57%, H25=7.50%, H27=1.14x, K16=1926.93
"""
import json, os
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path

FRONTEND = Path(__file__).parent / "index.html"

def _ppmt(rate, per, nper, pv):
    if abs(rate) < 1e-10: return -pv / nper
    pmt = -pv * rate / (1 - (1 + rate) ** -nper)
    bal = pv*(1+rate)**(per-1) + pmt*((1+rate)**(per-1)-1)/rate
    return pmt - (-bal * rate)

def _irr(cfs, guess=0.10):
    r = guess
    for _ in range(500):
        f = df = 0.0
        for t, c in enumerate(cfs):
            p = (1+r)**t; f += c/p; df -= t*c/(p*(1+r))
        if abs(df) < 1e-14: break
        r2 = r - f/df
        if not (-0.99 < r2 < 10.0): r2 = r + (0.001 if f < 0 else -0.001)
        if abs(r2-r) < 1e-10: r = r2; break
        r = r2
    return r if (-0.99 < r < 10.0) else None

def _bisect_rent(target, irr_type, inp, lo=5.0, hi=50.0):
    def get(rent):
        o = _compute({**inp, "D60": rent})
        v = o["H24"] if irr_type == "project" else o["H25"]
        return v if (v is not None and -0.99 < v < 2.0) else None
    lo_v = get(lo)
    while lo_v is None and lo < hi - 0.5: lo += 0.5; lo_v = get(lo)
    hi_v = get(hi)
    if lo_v is None or hi_v is None: return None
    if target <= lo_v: return round(lo, 3)
    if target >= hi_v: return round(hi, 3)
    for _ in range(100):
        mid = (lo+hi)/2; mv = get(mid)
        if mv is None: break
        if mv < target: lo = mid
        else: hi = mid
        if hi-lo < 0.001: break
    return round((lo+hi)/2, 3)

def _compute(p):
    D = {
        "C5":0.30,"C6":0.085,"C7":0.055,"C8":10,"C9":5,"C11":0.01,
        "C14":"Ei","C21":"Ei","C57":0.50,
        "D15":-0.01,"D16":-0.005,"D17":5,"D18":10,"D19":0.20,
        "D22":0.20,"D23":10,
        "D26":2086,"D27":0.24,"D28":40,"D29":51.5,
        "D34":20.0,"D36":40.0,"D37":10.0,"D38":20.0,"D39":0.0,
        "D42":1700.0,"E42":0.90,"D43":1300.0,"E43":0.10,"D44":1000.0,
        "D56":0.05,"D58":10.0,"D59":0.02,"D60":13.0,"H26":0.08,
    }
    D.update(p)
    c14=D["C14"]=="Jah"; c21=D["C21"]=="Jah"
    D5  = D["D22"] if c21 else D["C5"]
    D6  = D["C6"]+D["D15"] if c14 else D["C6"]
    D7  = D["C7"]+D["D16"] if c14 else D["C7"]
    if c14 and c21: D8=D["C8"]+D["D18"]+D["D23"]
    elif c14:       D8=D["C8"]+D["D18"]
    elif c21:       D8=D["C8"]+D["D23"]
    else:           D8=D["C8"]
    D9  = D["C9"]+D["D17"] if c14 else D["C9"]
    D10 = D8   # C10=D8 in v7 — horizon always equals loan term
    D11 = D["C11"]; H26=D["H26"]
    D57 = D["D19"] if c14 else D["C57"]
    E42=D["E42"]; E43=D["E43"]; E44=max(0.0,1.0-E42-E43)
    D30=D["D28"]*D["D29"]; D31=D30/E42
    D35=D["D34"]*D["D26"]/D31
    if "devCosts" in D and D["devCosts"]>0:
        D46=D35+D["devCosts"]
    else:
        D46=D35+D["D36"]+D["D37"]+D["D38"]+D["D39"]
    D47=D["D42"]*E42+D["D43"]*E43+D["D44"]*E44
    D49=D46/E42; D50=D47/E42
    D51=D49+D50; D52=D51*D["D27"]; D53=D51+D52

    N=41; z=lambda:[0.0]*N
    r5,r6,r7,r8,r9,r10,r11=z(),z(),z(),z(),z(),z(),z()
    r12,r13,r14,r15,r16,r17=z(),z(),z(),z(),z(),z()
    r18,r19,r20,r21,r22=z(),z(),z(),z(),z()

    for y in range(1,N):
        r5[y]=1.0 if y<=4 else r5[y-1]*(1+D["D59"])
        r6[y]=0.0 if y<=3 else (1-D57 if y==4 else 1-D["D56"])
        r9[y]=D["D60"]*r5[y]*12*r6[y] if y<=D10 else 0
        if y<=3:   r10[y]=0
        elif y==4: r10[y]=-D["D58"]
        elif y<=D10: r10[y]=r10[y-1]*(1+D["D59"])
        r11[y]=r9[y]+r10[y]

    r7[1]=-D49; r7[2]=-D50*0.6; r7[3]=-D50*0.4
    for y in [1,2,3]: r8[y]=r7[y]*D["D27"]
    for y in range(1,N): r13[y]=(r7[y]+r8[y]+r11[y]) if y<=D10 else 0
    for y in [1,2,3]: r14[y]=-r13[y]*(1-D5)
    r16[1]=r14[1]; r16[2]=r16[1]+r14[2]; r16[3]=r16[2]+r14[3]; r16[4]=r16[3]
    K16=r16[4]
    for y in range(5,N):
        per=y-4; r15[y]=_ppmt(D7,per,D8,K16) if per<=D8 else 0
        r16[y]=r16[y-1]+r15[y]
    for y in range(1,N):
        r17[y]=-r16[y]*(D6 if y<=4 else D7)
        r18[y]=0.0
    r19[1]=-K16*D11
    for y in range(5,N):
        if (y-5)%D9==0: r19[y]=-r16[y]*D11
    for y in range(1,N):
        r12[y]=(r11[y]/H26-r16[y]) if y==D10 else 0
    for y in range(1,N):
        r13[y]=(r7[y]+r8[y]+r11[y]+r12[y]) if y<=D10 else 0
    for y in range(1,N):
        r20[y]=(r13[y]+r14[y]+r15[y]+r17[y]+r18[y]+r19[y]) if y<=D10 else 0
    cum=0.0
    for y in range(1,N):
        if y<=D10: cum+=r20[y]; r21[y]=cum
    for y in range(5,N):
        denom=r15[y]+r17[y]
        if r16[y-1]>1e-6 and abs(denom)>1e-10: r22[y]=-r13[y]/denom

    H24=_irr(r13[1:D10+1]); H25=_irr(r20[1:D10+1])
    H23=-min(r21[1:D10+1]); H29=H23*D30
    dv=[r22[y] for y in range(1,N) if r22[y]>0]
    H27=round(min(dv),4) if dv else None

    AV7=sum(r7); AV8=sum(r8)
    AV9=sum(r9[1:D10+1]); AV10=sum(r10[1:D10+1])
    AV12=sum(r12[1:D10+1]); AV17=sum(r17[1:D10+1])
    AV19=sum(r19[1:D10+1]); AV20=sum(r20[1:D10+1])

    H31=-AV7*D30; H32=-AV8*D30; H33=-AV10*D30
    H34=-(AV17+AV19)*D30; H35=AV20*D30
    H36=H31+H32+H33+H34+H35
    H37=AV9*D30; H38=AV12*D30
    J37=(H36+H38)/H36 if H36 else 1.0
    rent=D["D60"]

    return {
        "D5":D5,"D6":D6,"D7":D7,"D8":D8,"D9":D9,"D10":D10,
        "D30":D30,"D31":D31,"D49":D49,"D50":D50,"D53":D53,
        "K16":K16,"H26":H26,"D57":D57,
        "H23":H23,"H24":H24,"H25":H25,"H27":H27,"H29":H29,
        "H31":H31,"H32":H32,"H33":H33,"H34":H34,"H35":H35,
        "H36":H36,"H37":H37,"H38":H38,
        "L31":rent*(H31/H36)*J37 if H36 else 0,
        "L32":rent*(H32/H36)*J37 if H36 else 0,
        "L33":rent*(H33/H36)*J37 if H36 else 0,
        "L34":rent*(H34/H36)*J37 if H36 else 0,
        "L35":rent*(H35/H36)*J37 if H36 else 0,
        "L37":rent*(-H38/H36) if H36 else 0,
        "J37":J37,"input_rent":rent,
        "cashflow":{"years":list(range(1,D10+1)),
            "row9":r9[1:D10+1],"row11":r11[1:D10+1],
            "row13":r13[1:D10+1],"row20":r20[1:D10+1],"row21":r21[1:D10+1]},
    }

FIELD_CASTS={
    "C5":float,"C6":float,"C7":float,"C8":int,"C9":int,"C11":float,
    "C14":str,"C21":str,"C57":float,
    "D15":float,"D16":float,"D17":int,"D18":int,"D19":float,
    "D22":float,"D23":int,
    "D26":int,"D27":float,"D28":int,"D29":float,
    "D34":float,"D36":float,"D37":float,"D38":float,"D39":float,
    "D42":float,"E42":float,"D43":float,"E43":float,"D44":float,
    "D56":float,"D58":float,"D59":float,"D60":float,"H26":float,"devCosts":float,
}
def cast(d): return {k:FIELD_CASTS[k](v) for k,v in d.items() if k in FIELD_CASTS}

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
    def _json(self,code,obj):
        b=json.dumps(obj).encode(); self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",len(b)); self._cors(); self.end_headers(); self.wfile.write(b)
    def _html(self):
        b=FRONTEND.read_bytes(); self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",len(b)); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self): self.send_response(200); self._cors(); self.end_headers()
    def do_GET(self):
        pt=urlparse(self.path).path
        if pt in("/","/index.html"): self._html()
        elif pt=="/health": self._json(200,{"status":"ok","engine":"v7"})
        elif pt=="/defaults": self._json(200,{"outputs":_compute({})})
        else: self._json(404,{"error":"not found"})
    def _body(self):
        raw=self.rfile.read(int(self.headers.get("Content-Length",0)))
        try: return json.loads(raw) if raw else {}
        except: return None
    def do_POST(self):
        pt=urlparse(self.path).path; data=self._body()
        if data is None: self._json(400,{"error":"invalid JSON"}); return
        if pt=="/calculate":
            try: self._json(200,{"outputs":_compute(cast(data))})
            except Exception as e: self._json(500,{"error":str(e)})
        elif pt=="/rent-for-irr":
            try:
                inp=cast(data); it=data.get("irr_type","equity")
                tgt=float(data.get("target_irr",0.05))
                rent=_bisect_rent(tgt,it,inp)
                if rent is None: self._json(422,{"error":"target out of range"})
                else:
                    out=_compute({**inp,"D60":rent})
                    self._json(200,{"rent":rent,
                        "achieved_irr":out["H24"] if it=="project" else out["H25"],
                        "outputs":out})
            except Exception as e: self._json(500,{"error":str(e)})
        else: self._json(404,{"error":"not found"})

if __name__=="__main__":
    port=int(os.environ.get("PORT",8000))
    print(f"Spinnaker v7 on :{port}",flush=True)
    HTTPServer(("0.0.0.0",port),H).serve_forever()
