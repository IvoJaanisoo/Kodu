"""
server.py — Spinnaker, fully self-contained.
No external dependencies. No subpackages. Just this file + index.html.
Run: python server.py
"""
import json, os, sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from pathlib import Path

FRONTEND = Path(__file__).parent / "index.html"

# ── FINANCIAL ENGINE ──────────────────────────────────────────────────────────

def _ppmt(rate, per, nper, pv):
    """Excel PPMT(rate, per, nper, pv, fv=0, type=0)"""
    if abs(rate) < 1e-10:
        return -pv / nper
    pmt = -pv * rate / (1 - (1 + rate) ** -nper)
    bal = pv * (1 + rate) ** (per - 1) + pmt * ((1 + rate) ** (per - 1) - 1) / rate
    return pmt - (-bal * rate)

def _irr(cfs, guess=0.10):
    """Excel IRR — Newton-Raphson"""
    r = guess
    for _ in range(500):
        f = df = 0.0
        for t, c in enumerate(cfs):
            p = (1 + r) ** t
            f += c / p
            df -= t * c / (p * (1 + r))
        if abs(df) < 1e-14:
            break
        r2 = r - f / df
        if not (-0.99 < r2 < 10.0):
            r2 = r + (0.001 if f < 0 else -0.001)
        if abs(r2 - r) < 1e-10:
            r = r2; break
        r = r2
    return r if (-0.99 < r < 10.0) else None

def _bisect_rent(target, irr_type, inp, lo=5.0, hi=50.0):
    """Find monthly rent that achieves a target IRR using bisection."""
    def get(rent):
        o = _compute({**inp, "input_rent": rent})
        v = o["H23"] if irr_type == "project" else o["H24"]
        # Filter out spurious Newton-Raphson roots (>200% unrealistic, or None)
        return v if (v is not None and -0.99 < v < 2.0) else None

    # Scan upward from lo to find a valid lower bound
    # (needed when low rents cause multiple-sign-change CFs with EIS low equity)
    step = 0.5
    lo_v = get(lo)
    while lo_v is None and lo < hi - step:
        lo += step
        lo_v = get(lo)

    hi_v = get(hi)
    if lo_v is None or hi_v is None:
        return None
    if target <= lo_v:
        return round(lo, 3)
    if target >= hi_v:
        return round(hi, 3)
    for _ in range(100):
        mid = (lo + hi) / 2
        mv = get(mid)
        if mv is None:
            break
        if mv < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 0.001:
            break
    return round((lo + hi) / 2, 3)

def _compute(p):
    """
    Full Spinnaker model — exact port of Spinnakeri mudel worksheet.
    p: dict of input_* fields (uses defaults for missing keys).
    """
    D = {  # defaults matching Excel green cells
        "input_equity_share": 0.50, "input_loan_interest": 0.05,
        "input_payment_schedule": 30, "input_project_duration": 30,
        "input_VAT": 0.24, "input_apartments": 40,
        "input_apartment_area": 51.5, "input_site_price": 20.0,
        "input_design": 80.0, "input_connections": 10.0,
        "input_project_management": 20.0, "input_sales_customers": 0.0,
        "input_apartment_cost": 1700.0, "input_apartmentarea_share": 0.80,
        "input_mainarea_cost": 1300.0, "input_mainarea_share": 0.20,
        "input_parkingarea_cost": 1000.0,
        "input_vacancy_fromNOI": 0.05, "input_firstyearvacancy_fromNOI": 0.50,
        "input_maintenance_cost": 50.0, "input_inflation": 0.02,
        "input_rent": 15.0, "input_yes_no": "Ei",
        "input_EISequity_share": 0.10, "input_EISinterestchange": -0.01,
        "input_EISpaymentchange": 5,
    }
    D.update(p)

    eis = D["input_yes_no"] == "Jah"
    D5  = D["input_EISequity_share"] if eis else D["input_equity_share"]
    D6  = D["input_loan_interest"] + D["input_EISinterestchange"] if eis else D["input_loan_interest"]
    D7  = D["input_payment_schedule"] + D["input_EISpaymentchange"] if eis else D["input_payment_schedule"]
    D8  = int(D["input_project_duration"])
    D11 = 2086  # plot area m² (fixed)

    E27 = D["input_apartmentarea_share"]
    E28 = D["input_mainarea_share"]
    E29 = 1.0 - E27 - E28

    D15 = D["input_apartments"] * D["input_apartment_area"]
    D16 = D15 / E27
    D20 = D["input_site_price"] * D11 / D16
    D31 = D20 + D["input_design"] + D["input_connections"] + D["input_project_management"] + D["input_sales_customers"]
    D32 = D["input_apartment_cost"] * E27 + D["input_mainarea_cost"] * E28 + D["input_parkingarea_cost"] * E29
    D34 = D31 / E27
    D35 = D32 / E27
    D36 = D34 + D35
    D37 = D36 * D["input_VAT"]
    D38 = D36 + D37

    N = 41
    r5 = [0.0] * N; r6 = [0.0] * N; r7 = [0.0] * N; r8 = [0.0] * N
    r9 = [0.0] * N; r10 = [0.0] * N; r11 = [0.0] * N; r12 = [0.0] * N
    r13= [0.0] * N; r14= [0.0] * N; r16= [0.0] * N; r17= [0.0] * N
    r18= [0.0] * N; r19= [0.0] * N; r20= [0.0] * N

    inf = D["input_inflation"]
    for y in range(1, N):
        r5[y] = 1.0 if y <= 4 else r5[y-1] * (1 + inf)
        r6[y] = 0.0 if y <= 3 else (1 - D["input_firstyearvacancy_fromNOI"] if y == 4 else 1 - D["input_vacancy_fromNOI"])
        r9[y] = D["input_rent"] * r5[y] * 12.0 * r6[y] if y <= D8 else 0.0
        if y <= 3:    r10[y] = 0.0
        elif y == 4:  r10[y] = -D["input_maintenance_cost"]
        elif y <= D8: r10[y] = r10[y-1] * (1 + inf)
        r11[y] = r9[y] + r10[y]
        r12[y] = D38 if y == D8 else 0.0

    r7[1] = -D34; r7[2] = -D35 * 0.6; r7[3] = -D35 * 0.4
    for y in [1, 2, 3]:
        r8[y] = r7[y] * D["input_VAT"]

    for y in range(1, N):
        r13[y] = (r7[y] + r8[y] + r11[y] + r12[y]) if y <= D8 else 0.0
    for y in [1, 2, 3]:
        r14[y] = -r13[y] * (1.0 - D5)

    r17[1] = r14[1]; r17[2] = r17[1] + r14[2]; r17[3] = r17[2] + r14[3]
    J17 = r17[3]
    nper = int(D7) - 3

    for y in range(4, N):
        if   y > D8:       r16[y] = 0.0
        elif y == D8:      r16[y] = -r17[y-1]
        elif y <= D7 and nper > 0: r16[y] = _ppmt(D6, y - 3, nper, J17)
        else:              r16[y] = 0.0
        r17[y] = r17[y-1] + r14[y] + r16[y]

    for y in range(1, N):
        r18[y] = -r17[y] * D6
    for y in range(1, N):
        r19[y] = (r13[y] + r14[y] + r16[y] + r18[y]) if y <= D8 else 0.0

    cum = 0.0
    for y in range(1, N):
        if y <= D8:
            cum += r19[y]; r20[y] = cum

    H23 = _irr(r13[1:D8+1])
    H24 = _irr(r19[1:D8+1])
    minCum = min(r20[1:D8+1]) if D8 >= 1 else 0.0
    H22 = -minCum
    H26 = H22 * D15
    H28 = -sum(r7[1:D8+1]) * D15
    H29 = -sum(r8[1:D8+1]) * D15
    H30 = -sum(r10[1:D8+1]) * D15
    H31 = -sum(r18[1:D8+1]) * D15
    H32 =  sum(r19[1:D8+1]) * D15
    H33 = H28 + H29 + H30 + H31 + H32
    H34 =  sum(r9[1:D8+1])  * D15
    H35 =  sum(r12[1:D8+1]) * D15
    H36 = H34 + H35

    J37 = (H33 + H35) / H33 if H33 != 0 else 1.0
    rent = D["input_rent"]

    return {
        "D5": D5, "D6": D6, "D7": D7, "D8": D8,
        "D15": D15, "D16": D16, "D20": D20,
        "D31": D31, "D32": D32, "D34": D34, "D35": D35,
        "D36": D36, "D37": D37, "D38": D38, "D39": D38,
        "J17": J17,
        "H22": H22, "H23": H23, "H24": H24,
        "H26": H26, "H28": H28, "H29": H29,
        "H30": H30, "H31": H31, "H32": H32,
        "H33": H33, "H34": H34, "H35": H35, "H36": H36,
        "L28": rent * (H28/H33) * J37 if H33 else 0,
        "L29": rent * (H29/H33) * J37 if H33 else 0,
        "L30": rent * (H30/H33) * J37 if H33 else 0,
        "L31": rent * (H31/H33) * J37 if H33 else 0,
        "L32": rent * (H32/H33) * J37 if H33 else 0,
        "L35": rent * (-H35/H33) if H33 else 0,
        "J37": J37,
        "input_rent": rent,
        "cashflow": {
            "years": list(range(1, D8 + 1)),
            "row9":  r9[1:D8+1],  "row11": r11[1:D8+1],
            "row13": r13[1:D8+1], "row19": r19[1:D8+1],
            "row20": r20[1:D8+1],
        },
    }

# ── HTTP SERVER ───────────────────────────────────────────────────────────────

FIELD_CASTS = {
    "input_equity_share": float, "input_loan_interest": float,
    "input_payment_schedule": int, "input_project_duration": int,
    "input_VAT": float, "input_apartments": int,
    "input_apartment_area": float, "input_site_price": float,
    "input_design": float, "input_connections": float,
    "input_project_management": float, "input_sales_customers": float,
    "input_apartment_cost": float, "input_apartmentarea_share": float,
    "input_mainarea_cost": float, "input_mainarea_share": float,
    "input_parkingarea_cost": float, "input_vacancy_fromNOI": float,
    "input_firstyearvacancy_fromNOI": float, "input_maintenance_cost": float,
    "input_inflation": float, "input_rent": float, "input_yes_no": str,
    "input_EISequity_share": float, "input_EISinterestchange": float,
    "input_EISpaymentchange": int,
}

def cast_inputs(d):
    return {k: FIELD_CASTS[k](v) for k, v in d.items() if k in FIELD_CASTS}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", len(body))
        self._cors(); self.end_headers()
        self.wfile.write(body)

    def _html(self):
        body = FRONTEND.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers(); self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200); self._cors(); self.end_headers()

    def do_GET(self):
        p = urlparse(self.path).path
        if p in ("/", "/index.html"):
            self._html()
        elif p == "/health":
            self._json(200, {"status": "ok", "engine": "pure-python"})
        elif p == "/defaults":
            self._json(200, {"outputs": _compute({})})
        else:
            self._json(404, {"error": "not found"})

    def _body(self):
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try: return json.loads(raw) if raw else {}
        except Exception: return None

    def do_POST(self):
        p = urlparse(self.path).path
        data = self._body()
        if data is None:
            self._json(400, {"error": "invalid JSON"}); return

        if p == "/calculate":
            try:
                self._json(200, {"outputs": _compute(cast_inputs(data))})
            except Exception as e:
                self._json(500, {"error": str(e)})

        elif p == "/rent-for-irr":
            try:
                inp = cast_inputs(data)
                irr_type = data.get("irr_type", "project")
                target   = float(data.get("target_irr", 0.05))
                rent = _bisect_rent(target, irr_type, inp)
                if rent is None:
                    self._json(422, {"error": "target IRR outside achievable range"})
                else:
                    out = _compute({**inp, "input_rent": rent})
                    self._json(200, {
                        "rent": rent,
                        "achieved_irr": out["H23"] if irr_type == "project" else out["H24"],
                        "outputs": out,
                    })
            except Exception as e:
                self._json(500, {"error": str(e)})
        else:
            self._json(404, {"error": "not found"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    print(f"Spinnaker on :{port}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
