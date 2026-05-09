"""
server.py — Spinnaker v5. Self-contained, zero external dependencies.
Run: python server.py
"""
import json, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path

FRONTEND = Path(__file__).parent / "index.html"

# ── FINANCIAL ENGINE — v5 (two-rate, three EIS toggles, 40yr horizon) ─────────

def _ppmt(rate, per, nper, pv):
    """Excel PPMT(rate, per, nper, pv, fv=0, type=0)"""
    if abs(rate) < 1e-10:
        return -pv / nper
    pmt = -pv * rate / (1 - (1 + rate) ** -nper)
    bal = pv*(1+rate)**(per-1) + pmt*((1+rate)**(per-1)-1)/rate
    return pmt - (-bal * rate)

def _irr(cfs, guess=0.10):
    """Excel IRR — Newton-Raphson, 500 iterations"""
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
    """Find monthly rent achieving target IRR by bisection."""
    def get(rent):
        o = _compute({**inp, "input_rent": rent})
        v = o["H23"] if irr_type == "project" else o["H24"]
        return v if (v is not None and -0.99 < v < 2.0) else None
    lo_v = get(lo)
    while lo_v is None and lo < hi - 0.5:
        lo += 0.5; lo_v = get(lo)
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
    Full Spinnaker v5 model — exact port of Spinnakeri mudel worksheet.
    Two-rate loan (D6 dev / D7 inv), three EIS toggles (C13/C18/C23),
    40-year horizon, investment loan starting year 5.
    """
    D = {
        # Base financing (C row)
        "input_equity_share":    0.70,   # C5
        "input_dev_loan_rate":   0.085,  # C6
        "input_inv_loan_rate":   0.055,  # C7
        "input_inv_loan_term":   20,     # C8
        "input_project_horizon": 40,     # C10
        # EIS toggles
        "input_eis_c13": "Ei",
        "input_eis_c18": "Ei",
        "input_eis_c23": "Ei",
        # EIS fixed parameters (D row)
        "D14": 0.20,   "D15": -0.02,  "D16": 0.016,
        "D20": -0.01,  "D21": 0.016,
        "D24": 0.10,   "D25": -0.005, "D26": 15,
        # Physical
        "D29": 2086,   # plot area m²
        "D30": 0.24,   # VAT
        "input_apartments":    40,
        "input_apartment_area": 51.5,
        "input_site_price":    20.0,    # D37 land €/m² plot
        "input_design":        50.0,    # D39
        "input_connections":   10.0,    # D40
        "input_project_management": 20.0, # D41
        "input_sales_customers":  0.0,  # D42
        "input_apartment_cost":  1700.0, # D45
        "input_apartmentarea_share": 0.90, # E45
        "input_mainarea_cost":   1300.0, # D46
        "input_parkingarea_cost": 1000.0, # D47
        # Operations
        "input_vacancy_fromNOI":          0.05,  # D60
        "input_firstyearvacancy_fromNOI": 0.50,  # E60
        "input_maintenance_cost":         30.0,  # D61
        "input_inflation":                0.02,  # D62
        "input_rent":                     14.0,  # D63
        "input_exit_override":            0.0,
    }
    D.update(p)

    # ── EIS overrides ──────────────────────────────────────────────────────
    c13 = D["input_eis_c13"] == "Jah"
    c18 = D["input_eis_c18"] == "Jah"
    c23 = D["input_eis_c23"] == "Jah"

    # D5 = IF(C23,D24, IF(C13,D14, C5))
    D5 = D["D24"] if c23 else (D["D14"] if c13 else D["input_equity_share"])
    # D6 = IF(C13, C6+D15, C6)
    D6 = D["input_dev_loan_rate"] + D["D15"] if c13 else D["input_dev_loan_rate"]
    # D7 = IF(C23, C7+D25, IF(C18, C7+D20, C7))
    D7 = (D["input_inv_loan_rate"] + D["D25"] if c23
          else D["input_inv_loan_rate"] + D["D20"] if c18
          else D["input_inv_loan_rate"])
    # D8 = IF(C23, C8+D26, C8)
    D8 = D["input_inv_loan_term"] + D["D26"] if c23 else D["input_inv_loan_term"]
    D10 = int(D["input_project_horizon"])

    D29 = D["D29"]; D30 = D["D30"]
    D16_rate = D["D16"]; D21_rate = D["D21"]

    # ── Area & cost calculations ───────────────────────────────────────────
    E45 = D["input_apartmentarea_share"]
    E46 = 0.10                        # E46 = common area share (fixed in Excel D46=0.1)
    E47 = max(0.0, 1.0 - E45 - E46)   # E47 = parking = remainder (Excel: =1-(E45+E46))

    D33 = D["input_apartments"] * D["input_apartment_area"]   # D33=D31*D32
    D34 = D33 / E45                                            # D34=D33/E45
    D38 = D["input_site_price"] * D29 / D34                   # D38=D37*D29/D34
    D49 = D38 + D["input_design"] + D["input_connections"] + D["input_project_management"] + D["input_sales_customers"]
    D50 = D["input_apartment_cost"]*E45 + D["input_mainarea_cost"]*E46 + D["input_parkingarea_cost"]*E47
    D52 = D49 / E45    # dev cost per rentable m²
    D53 = D50 / E45    # build cost per rentable m²
    D54 = D52 + D53
    D55 = D54 * D30
    D56 = D54 + D55    # exit value per rentable m² (construction cost basis)

    exit_val = D["input_exit_override"] if D["input_exit_override"] > 0 else D56

    # ── Cash flow arrays (1-indexed, years 1..40) ─────────────────────────
    N = 41
    def z(): return [0.0]*N
    r5,r6,r7,r8 = z(),z(),z(),z()
    r9,r10,r11,r12,r13 = z(),z(),z(),z(),z()
    r14,r15,r16,r17,r18 = z(),z(),z(),z(),z()
    r19,r20,r21 = z(),z(),z()

    D62 = D["input_inflation"]
    D63 = D["input_rent"]

    # Row 5: rent index (years 1-4=1, then compounds at D62)
    for y in range(1,N):
        r5[y] = 1.0 if y<=4 else r5[y-1]*(1+D62)

    # Row 6: occupancy
    for y in range(1,N):
        r6[y] = (0.0 if y<=3
                 else 1.0-D["input_firstyearvacancy_fromNOI"] if y==4
                 else 1.0-D["input_vacancy_fromNOI"])

    # Row 7: CAPEX per rentable m²
    r7[1]=-D52; r7[2]=-D53*0.6; r7[3]=-D53*0.4

    # Row 8: VAT on CAPEX
    for y in [1,2,3]: r8[y]=r7[y]*D30

    # Row 9: rental income
    for y in range(1,N):
        r9[y] = D63*r5[y]*12*r6[y] if y<=D10 else 0.0

    # Row 10: opex per rentable m² (negative)
    # K10=-D61, then compounds each year
    for y in range(1,N):
        if   y<=3:    r10[y]=0.0
        elif y==4:    r10[y]=-D["input_maintenance_cost"]
        elif y<=D10:  r10[y]=r10[y-1]*(1+D62)

    # Row 11: NOI = r9+r10
    for y in range(1,N): r11[y]=r9[y]+r10[y]

    # Row 12: exit at year D10
    r12[D10] = exit_val

    # Row 13: project CF (CAPEX+VAT+NOI+exit)
    for y in range(1,N):
        r13[y]=(r7[y]+r8[y]+r11[y]+r12[y]) if y<=D10 else 0.0

    # Row 14: loan disbursement years 1-3 only
    for y in [1,2,3]: r14[y]=-r13[y]*(1.0-D5)

    # Row 16 years 1-4: build up balance, get K16
    r16[1]=r14[1]; r16[2]=r16[1]+r14[2]
    r16[3]=r16[2]+r14[3]; r16[4]=r16[3]   # K16=J16+K14+K15, K14=K15=0
    K16 = r16[4]

    # Row 15: PPMT starting year 5
    # PPMT(D7, period=y-4, nper=D8, pv=K16)
    for y in range(5,N):
        per = y-4
        r15[y] = _ppmt(D7,per,D8,K16) if per<=D8 else 0.0

    # Row 16 years 5+: balance = prev + r15 (r14=0 for y>=4)
    for y in range(5,N):
        r16[y] = r16[y-1] + r15[y]

    # Row 17: interest — D6 for years 1-4 (dev loan), D7 for years 5+ (inv loan)
    for y in range(1,N):
        r17[y] = -r16[y] * (D6 if y<=4 else D7)

    # Row 18: guarantee fee
    # Years 1-4: C13 toggle, rate D16
    # Years 5+:  C18 toggle, rate D21
    for y in range(1,N):
        if   y<=4: r18[y] = -D16_rate*r16[y] if c13 else 0.0
        else:      r18[y] = -D21_rate*r16[y] if c18 else 0.0

    # Row 19: equity CF = r13+r14+r15+r17+r18
    for y in range(1,N):
        r19[y]=(r13[y]+r14[y]+r15[y]+r17[y]+r18[y]) if y<=D10 else 0.0

    # Row 20: cumulative equity CF
    cum=0.0
    for y in range(1,N):
        if y<=D10: cum+=r19[y]; r20[y]=cum

    # Row 21: annual DSCR = -NOI/(principal+interest+guarantee)
    # L21=IF(K16>0,-L13/(L15+L17+L18),0) i.e. uses prev year balance check
    for y in range(5,N):
        denom = r15[y]+r17[y]+r18[y]
        if r16[y-1] > 1e-6 and abs(denom) > 1e-10:
            r21[y] = -r13[y]/denom

    # ── Key outputs ───────────────────────────────────────────────────────
    H23 = _irr(r13[1:D10+1])
    H24 = _irr(r19[1:D10+1])
    H22 = -min(r20[1:D10+1])
    H27 = H22 * D33

    # H25 = MIN(FILTER(L21:AU21, L21:AU21>0)) = min annual DSCR during repayment
    dscr_vals = [r21[y] for y in range(1,N) if r21[y]>0]
    H25 = round(min(dscr_vals),4) if dscr_vals else None

    # ── Cost totals ───────────────────────────────────────────────────────
    AV7  = sum(r7[1:D10+1]);  AV8  = sum(r8[1:D10+1])
    AV9  = sum(r9[1:D10+1]);  AV10 = sum(r10[1:D10+1])
    AV12 = sum(r12[1:D10+1]); AV17 = sum(r17[1:D10+1])
    AV18 = sum(r18[1:D10+1]); AV19 = sum(r19[1:D10+1])

    H29 = -AV7*D33            # ARENDUSKULU
    H30 = -AV8*D33            # KÄIBEMAKS
    H31 = -AV10*D33           # HALDUSKULU
    H32 = -(AV17+AV18)*D33   # PANGA/EIS TOOTLUS
    H33 = AV19*D33            # OMANIKU TOOTLUS
    H34 = H29+H30+H31+H32+H33 # Kulud kokku
    H35 = AV9*D33             # ÜÜRITULU
    H36 = AV12*D33            # HOONE MÜÜK
    H37 = H35+H36             # Tulud kokku

    # Waterfall: L column = monthly rent allocation per cost component
    J37 = (H34+H36)/H34 if H34!=0 else 1.0
    rent = D63
    def lc(h): return rent*(h/H34)*J37 if H34 else 0
    def lc_exit(): return rent*(-H36/H34) if H34 else 0

    return {
        "D5":D5,"D6":D6,"D7":D7,"D8":D8,"D10":D10,
        "D33":D33,"D34":D34,"E45":E45,
        "D52":D52,"D53":D53,"D54":D54,"D55":D55,"D56":D56,"exit_val":exit_val,
        "K16":K16,
        "H22":H22,"H23":H23,"H24":H24,"H25":H25,"H27":H27,
        "H29":H29,"H30":H30,"H31":H31,"H32":H32,"H33":H33,"H34":H34,
        "H35":H35,"H36":H36,"H37":H37,
        "L29":lc(H29),"L30":lc(H30),"L31":lc(H31),
        "L32":lc(H32),"L33":lc(H33),"L36":lc_exit(),"J37":J37,
        "input_rent":rent,
        "cashflow":{
            "years":list(range(1,D10+1)),
            "row9": r9[1:D10+1], "row11":r11[1:D10+1],
            "row13":r13[1:D10+1],"row19":r19[1:D10+1],"row20":r20[1:D10+1],
        },
    }

# ── HTTP SERVER ───────────────────────────────────────────────────────────────

FIELD_CASTS = {
    "input_equity_share":float, "input_dev_loan_rate":float,
    "input_inv_loan_rate":float, "input_inv_loan_term":int,
    "input_project_horizon":int,
    "input_eis_c13":str,"input_eis_c18":str,"input_eis_c23":str,
    "input_apartments":int,"input_apartment_area":float,
    "input_site_price":float,"input_design":float,
    "input_connections":float,"input_project_management":float,
    "input_sales_customers":float,"input_apartment_cost":float,
    "input_apartmentarea_share":float,"input_mainarea_cost":float,
    "input_parkingarea_cost":float,"input_vacancy_fromNOI":float,
    "input_firstyearvacancy_fromNOI":float,"input_maintenance_cost":float,
    "input_inflation":float,"input_rent":float,"input_exit_override":float,
}

def cast_inputs(d):
    return {k:FIELD_CASTS[k](v) for k,v in d.items() if k in FIELD_CASTS}

class Handler(BaseHTTPRequestHandler):
    def log_message(self,fmt,*a): pass
    def _cors(self):
        self.send_header("Access-Control-Allow-Origin","*")
        self.send_header("Access-Control-Allow-Headers","Content-Type")
        self.send_header("Access-Control-Allow-Methods","GET,POST,OPTIONS")
    def _json(self,code,obj):
        b=json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type","application/json")
        self.send_header("Content-Length",len(b))
        self._cors(); self.end_headers(); self.wfile.write(b)
    def _html(self):
        b=FRONTEND.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type","text/html; charset=utf-8")
        self.send_header("Content-Length",len(b))
        self.end_headers(); self.wfile.write(b)
    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()
    def do_GET(self):
        p=urlparse(self.path).path
        if p in("/","/index.html"): self._html()
        elif p=="/health": self._json(200,{"status":"ok","engine":"v5"})
        elif p=="/defaults": self._json(200,{"outputs":_compute({})})
        else: self._json(404,{"error":"not found"})
    def _body(self):
        raw=self.rfile.read(int(self.headers.get("Content-Length",0)))
        try: return json.loads(raw) if raw else {}
        except: return None
    def do_POST(self):
        p=urlparse(self.path).path
        data=self._body()
        if data is None: self._json(400,{"error":"invalid JSON"}); return
        if p=="/calculate":
            try: self._json(200,{"outputs":_compute(cast_inputs(data))})
            except Exception as e: self._json(500,{"error":str(e)})
        elif p=="/rent-for-irr":
            try:
                inp=cast_inputs(data)
                irr_type=data.get("irr_type","equity")
                target=float(data.get("target_irr",0.05))
                rent=_bisect_rent(target,irr_type,inp)
                if rent is None: self._json(422,{"error":"target IRR outside achievable range"})
                else:
                    out=_compute({**inp,"input_rent":rent})
                    self._json(200,{"rent":rent,
                        "achieved_irr":out["H23"] if irr_type=="project" else out["H24"],
                        "outputs":out})
            except Exception as e: self._json(500,{"error":str(e)})
        else: self._json(404,{"error":"not found"})

if __name__=="__main__":
    port=int(os.environ.get("PORT",8000))
    print(f"Spinnaker v5 on :{port}",flush=True)
    HTTPServer(("0.0.0.0",port),Handler).serve_forever()
