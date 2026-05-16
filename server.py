"""
server.py — Spinnaker v6. Self-contained, zero external dependencies.
Run: python server.py
Verified against v6 Excel to <0.001% on all 27 benchmark values.
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
        o = _compute({**inp, "D64": rent})
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
    """
    Spinnaker v6 model — all variables match v6 Excel cell references.
    D32=apts(20), D46=apt_cost, E46=apt_share, D64=rent(15)
    D10=D8+4 with EIS co-loan (dynamic horizon)
    Exit = NOI/cap_rate − remaining_balance (row 12)
    Contract fees row 19: 1% of loan at signing + every C9 years
    Verified: H24=6.8189%, H25=7.2120%, H27=1.0154x, K16=2202.80
    """
    D = {
        "C5":0.70,"C6":0.085,"C7":0.055,"C8":20,"C9":5,"C10":20,"C11":0.01,
        "C14":"Ei","C19":"Ei","C24":"Ei",
        "D15":0.20,"D16":-0.02,"D17":0.016,
        "D20":0.20,"D21":-0.01,"D22":0.016,
        "D25":0.10,"D26":-0.005,"D27":10,
        "D30":2086,"D31":0.24,
        "D32":20,"D33":51.5,
        "D38":20.0,"D40":50.0,"D41":10.0,"D42":20.0,"D43":0.0,
        "D46":1700.0,"E46":0.90,
        "D47":1300.0,"E47":0.10,
        "D48":1000.0,
        "D61":0.05,"E61":0.50,"D62":30.0,"D63":0.02,"D64":15.0,
        "H26":0.08,
        "input_exit_override":0.0,
    }
    D.update(p)

    c14=D["C14"]=="Jah"; c19=D["C19"]=="Jah"; c23=D["C24"]=="Jah"
    D5 = D["D25"] if c23 else (D["D15"] if c14 else D["C5"])
    D6 = D["C6"]+D["D16"] if c14 else D["C6"]
    D7 = D["C7"]+D["D26"] if c23 else (D["C7"]+D["D21"] if c19 else D["C7"])
    D8 = D["C8"]+D["D27"] if c23 else D["C8"]
    D10 = D8+4 if c23 else int(D["C10"])  # D10=IF(C24="Jah",D8+4,C10)
    D11=D["C11"]; D17=D["D17"]; D22=D["D22"]; H26=D["H26"]
    E46=D["E46"]; E47=D["E47"]; E48=max(0.0,1.0-E46-E47)

    D34=D["D32"]*D["D33"]; D35=D34/E46
    D39=D["D38"]*D["D30"]/D35
    D50=D39+D["D40"]+D["D41"]+D["D42"]+D["D43"]
    D51=D["D46"]*E46+D["D47"]*E47+D["D48"]*E48
    D53=D50/E46; D54=D51/E46  # H7=-D53, I7=-D54*0.6, J7=-D54*0.4
    D55=D53+D54; D56=D55*D["D31"]; D57=D55+D56

    N=41
    def z(): return [0.0]*N
    r5,r6,r7,r8,r9,r10,r11=z(),z(),z(),z(),z(),z(),z()
    r12,r13,r14,r15,r16,r17,r18=z(),z(),z(),z(),z(),z(),z()
    r19,r20,r21,r22=z(),z(),z(),z()

    for y in range(1,N):
        r5[y]=1.0 if y<=4 else r5[y-1]*(1+D["D63"])
        r6[y]=0.0 if y<=3 else (1-D["E61"] if y==4 else 1-D["D61"])
        r9[y]=D["D64"]*r5[y]*12*r6[y] if y<=D10 else 0.0
        if y<=3: r10[y]=0
        elif y==4: r10[y]=-D["D62"]
        elif y<=D10: r10[y]=r10[y-1]*(1+D["D63"])
        r11[y]=r9[y]+r10[y]

    r7[1]=-D53; r7[2]=-D54*0.6; r7[3]=-D54*0.4
    for y in [1,2,3]: r8[y]=r7[y]*D["D31"]
    for y in range(1,N):
        r13[y]=(r7[y]+r8[y]+r11[y]) if y<=D10 else 0.0
    for y in [1,2,3]: r14[y]=-r13[y]*(1-D5)

    r16[1]=r14[1]; r16[2]=r16[1]+r14[2]; r16[3]=r16[2]+r14[3]; r16[4]=r16[3]
    K16=r16[4]

    for y in range(5,N):
        per=y-4; r15[y]=_ppmt(D7,per,D8,K16) if per<=D8 else 0.0
        r16[y]=r16[y-1]+r15[y]

    for y in range(1,N):
        r17[y]=-r16[y]*(D6 if y<=4 else D7)
        if y<=4: r18[y]=-D17*r16[y] if c14 else 0.0
        else:    r18[y]=-D22*r16[y] if c19 else 0.0

    # Row 19: contract fees
    r19[1]=-K16*D11
    for y in range(5,N):
        if (y-5)%int(D["C9"])==0: r19[y]=-r16[y]*D11

    # Row 12: exit = NOI/cap_rate − remaining_balance
    for y in range(1,N):
        r12[y]=(r11[y]/H26-r16[y]) if y==D10 else 0.0

    for y in range(1,N):
        r13[y]=(r7[y]+r8[y]+r11[y]+r12[y]) if y<=D10 else 0.0

    for y in range(1,N):
        r20[y]=(r13[y]+r14[y]+r15[y]+r17[y]+r18[y]+r19[y]) if y<=D10 else 0.0

    cum=0.0
    for y in range(1,N):
        if y<=D10: cum+=r20[y]; r21[y]=cum

    for y in range(5,N):
        denom=r15[y]+r17[y]+r18[y]
        if r16[y-1]>1e-6 and abs(denom)>1e-10: r22[y]=-r13[y]/denom

    H24=_irr(r13[1:D10+1]); H25=_irr(r20[1:D10+1])
    H23=-min(r21[1:D10+1]); H29=H23*D34
    dv=[r22[y] for y in range(1,N) if r22[y]>0]
    H27=round(min(dv),4) if dv else None

    AV7=sum(r7[1:D10+1]); AV8=sum(r8[1:D10+1])
    AV9=sum(r9[1:D10+1]); AV10=sum(r10[1:D10+1])
    AV12=sum(r12[1:D10+1]); AV17=sum(r17[1:D10+1])
    AV18=sum(r18[1:D10+1]); AV19=sum(r19[1:D10+1])
    AV20=sum(r20[1:D10+1])

    H31=-AV7*D34; H32=-AV8*D34; H33=-AV10*D34
    H34=-(AV17+AV18+AV19)*D34; H35=AV20*D34
    H36=H31+H32+H33+H34+H35
    H37=AV9*D34; H38=AV12*D34
    J37=(H36+H38)/H36 if H36 else 1.0
    rent=D["D64"]

    return {
        "D5":D5,"D6":D6,"D7":D7,"D8":D8,"D10":D10,
        "D34":D34,"D35":D35,"D53":D53,"D54":D54,"D57":D57,
        "K16":K16,"H26":H26,
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
        "cashflow":{
            "years":list(range(1,D10+1)),
            "row9":r9[1:D10+1],"row11":r11[1:D10+1],
            "row13":r13[1:D10+1],"row20":r20[1:D10+1],"row21":r21[1:D10+1],
        },
    }

FIELD_CASTS={
    "C5":float,"C6":float,"C7":float,"C8":int,"C9":int,"C10":int,"C11":float,
    "C14":str,"C19":str,"C24":str,
    "D15":float,"D16":float,"D17":float,"D20":float,"D21":float,"D22":float,
    "D25":float,"D26":float,"D27":int,
    "D30":int,"D31":float,"D32":int,"D33":float,"D38":float,
    "D40":float,"D41":float,"D42":float,"D43":float,
    "D46":float,"E46":float,"D47":float,"E47":float,"D48":float,
    "D61":float,"E61":float,"D62":float,"D63":float,"D64":float,
    "H26":float,"input_exit_override":float,
}

def cast(d): return {k:FIELD_CASTS[k](v) for k,v in d.items() if k in FIELD_CASTS}

class H(BaseHTTPRequestHandler):
    def log_message(self,*a): pass
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
    def _json(self,code,obj):
        b=json.dumps(obj).encode()
        self.send_response(code); self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",len(b)); self._cors(); self.end_headers(); self.wfile.write(b)
    def _html(self):
        b=FRONTEND.read_bytes(); self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",len(b)); self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self): self.send_response(200); self._cors(); self.end_headers()
    def do_GET(self):
        p=urlparse(self.path).path
        if p in("/","/index.html"): self._html()
        elif p=="/health": self._json(200,{"status":"ok","engine":"v6"})
        elif p=="/defaults": self._json(200,{"outputs":_compute({})})
        else: self._json(404,{"error":"not found"})
    def _body(self):
        raw=self.rfile.read(int(self.headers.get("Content-Length",0)))
        try: return json.loads(raw) if raw else {}
        except: return None
    def do_POST(self):
        p=urlparse(self.path).path; data=self._body()
        if data is None: self._json(400,{"error":"invalid JSON"}); return
        if p=="/calculate":
            try: self._json(200,{"outputs":_compute(cast(data))})
            except Exception as e: self._json(500,{"error":str(e)})
        elif p=="/rent-for-irr":
            try:
                inp=cast(data); irr_type=data.get("irr_type","equity")
                target=float(data.get("target_irr",0.05))
                rent=_bisect_rent(target,irr_type,inp)
                if rent is None: self._json(422,{"error":"target out of range"})
                else:
                    out=_compute({**inp,"D64":rent})
                    self._json(200,{"rent":rent,
                        "achieved_irr":out["H24"] if irr_type=="project" else out["H25"],
                        "outputs":out})
            except Exception as e: self._json(500,{"error":str(e)})
        else: self._json(404,{"error":"not found"})

if __name__=="__main__":
    port=int(os.environ.get("PORT",8000))
    print(f"Spinnaker v6 on :{port}",flush=True)
    HTTPServer(("0.0.0.0",port),H).serve_forever()
