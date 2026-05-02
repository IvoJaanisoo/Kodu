# Spinnaker Rental Model — System Architecture

## Principle
The Excel workbook `Spinnakeri_üürimudel_v3.xlsx` is the **single source of truth** for all calculations.
The system adds a UI layer and API wrapper around it. No formulas are reimplemented outside Excel.

---

## 1. Input Mapping — UI Field → Excel Green Cell

| UI Label (EN) | Excel Label (ET) | Cell | Default | Type | Notes |
|---|---|---|---|---|---|
| Equity share | Omakapitali osakaal | C5 | 0.50 | % | Base column |
| Loan interest rate | Laenuintress | C6 | 0.05 | % | Base column |
| Repayment schedule (yr) | Tagasimakse graafik | C7 | 30 | int | Base column |
| Project duration (yr) | Projekti kestvus | C8 | 30 | int | Shared |
| VAT rate | Käibemaks | D12 | 0.24 | % | — |
| Number of apartments | Korterite arv | D13 | 40 | int | — |
| Avg apartment size (m²) | Keskmine korteri pind | D14 | 51.5 | float | — |
| Land price (€/m² plot) | Maa hind | D19 | 20 | float | Per plot m² |
| Planning & design (€/m²) | Planeering ja projekteerimine | D21 | 80 | float | Per net m² |
| Connections & infra (€/m²) | Liitumistasud ja sotsiaalinfra | D22 | 10 | float | Per net m² |
| PM & supervision (€/m²) | Projektijuhtimine, järelevalve | D23 | 20 | float | Per net m² |
| Sales / client service (€/m²) | Müük/klienditeenindus | D24 | 0 | float | Per net m² |
| Apartments build cost (€/m²) | Korterid ehituskulu | D27 | 1700 | float | Per m² rentable |
| Apt area ratio | Korterite osakaal | E27 | 0.80 | % | Must sum to ≤1 with E28+E29 |
| Common areas build cost (€/m²) | Üldkasutatavad pinnad | D28 | 1300 | float | Per m² common |
| Common area ratio | Üldkasutatavate pindade osakaal | E28 | 0.20 | % | — |
| Parking floor (€/m²) | Parkimiskorrus | D29 | 1000 | float | E29 = 1−E27−E28 (formula) |
| Vacancy + credit risk | Vakants + makserisk | D42 | 0.05 | % | Applied to NOI |
| First-year vacancy | Esimene aasta vakants | E42 | 0.50 | % | Year 4 ramp-up |
| OpEx first year (€/m²/yr) | Halduskulu esimesel aastal | D43 | 50 | float | Grows 2%/yr |
| Annual rent increase | Üürihinna tõus | D44 | 0.02 | % | = inflation |
| **Monthly rent (€/m²)** | **Esimese aasta kuuüür m2 kohta** | **D45** | **15** | **float** | **Primary pricing lever — adjust to hit target IRR** |
| EIS co-loan | EISi kaaslaen | D48 | "Ei" | "Jah"/"Ei" | Toggle — activates D5/D6/D7 overrides |

### EIS Co-Loan Effect (when D48 = "Jah")
| Parameter | Base | With EIS | Delta |
|---|---|---|---|
| Equity share (D5) | C5 = 50% | 10% | −40pp |
| Interest rate (D6) | C6 = 5% | 4% | −1pp (C50 = −0.01) |
| Repayment years (D7) | C7 = 30 | 35 | +5yr (C51 = 5) |

---

## 2. Output Mapping — Excel Cell → UI Display

| UI Display Label | Excel Label (ET) | Cell | Current Value (base case) |
|---|---|---|---|
| **Project IRR (unlevered)** | Projekti IRR | H23 | 5.08% |
| **Equity IRR (levered)** | Omakapitali IRR | H24 | 4.99% |
| Monthly rent (€/m²) | Esimese aasta kuuüür | D45 | €15.00 (input) |
| Max equity required (€/m²) | Omakapitali vajadus max m2 kohta | H22 | €1,520/m² |
| Max equity required (€ total) | Omakapitali vajadus max | H26 | €3,130,375 |
| Development cost total | ARENDUSKULU | H28 | €4,496,470 |
| VAT amount | KÄIBEMAKS | H29 | €1,079,153 |
| Total OpEx over project | HALDUSKULU | H30 | €3,640,465 |
| Bank return | PANGA TOOTLUS | H31 | €2,450,317 |
| Owner return | OMANIKU TOOTLUS | H32 | €6,192,749 |
| Total costs | Kulud kokku | H33 | €17,859,154 |
| Total rental income | ÜÜRITULU | H34 | €12,283,532 |
| Building exit/sale | HOONE MÜÜK | H35 | €5,575,623 |
| Total revenues | Tulud kokku | H36 | €17,859,154 |
| Rentable area (m²) | Üüritav pind kokku | D15 | 2,060 m² |
| Total net area (m²) | Kogu suletud netopind | D16 | 2,575 m² |
| Dev cost / net m² | Arenduskulud kokku /m² | D31 | €126.20/m² |
| Build cost / net m² | Ehituskulud kokku /m² | D32 | €1,620/m² |
| Total cost / net m² (excl VAT) | Kokku /m² km-ta | D33 | €1,746.20/m² |
| Total cost / rentable m² (incl VAT) | Kokku korteri m2 KM-ga | D38 | €2,706.61/m² |
| Exit value / rentable m² | Exit väärtus | D39 | €2,706.61/m² |

---

## 3. Backend Interaction Design

### Architecture
```
[Browser UI]
     │  POST /calculate  { inputs: {...} }
     ▼
[FastAPI — main.py]
     │  1. Copy Excel template to /tmp/calc_xxxx.xlsx
     │  2. Write ONLY green cells (INPUT_CELLS map)
     │  3. Save workbook
     │  4. subprocess → scripts/recalc.py (LibreOffice headless)
     │  5. Load data_only=True
     │  6. Read OUTPUT_CELLS map
     │  7. Delete temp file
     └─► Return JSON { inputs, outputs }

[Excel Template — read-only, never modified]
```

### Endpoints
| Method | Path | Purpose |
|---|---|---|
| GET | /defaults | Return all green cell current values |
| POST | /calculate | Write inputs, recalculate, return outputs |
| GET | /health | Confirm API and Excel template are reachable |

### Recalculation
- LibreOffice Calc headless is invoked via `scripts/recalc.py`
- All formulas in all sheets are recalculated
- Any `#REF!`, `#DIV/0!` etc. are reported as errors before returning

### Deployment
```bash
pip install fastapi uvicorn openpyxl
# Place Excel model at: backend/Spinnakeri_üürimudel_v3.xlsx
uvicorn backend.main:app --reload --port 8000
```

---

## 4. Proposal: Future-State Code Replacement (Optional)

If Excel is ever retired, the calculation logic maps to this sequence:

1. **Area calculations**: `rentable_m2 = num_apts × avg_size; total_m2 = rentable_m2 / apt_ratio`
2. **CAPEX**: Spread Y1 (dev costs + land), Y2 (60% build), Y3 (40% build), each × (1 + VAT)
3. **Loan**: Proportional drawdown in Y1-3; annuity payments from Y4
4. **Cash flows**: Rent index × occupancy × (1 − vacancy) − OpEx − interest − principal
5. **IRRs**: Newton-Raphson on unlevered (project) and levered (equity) series
6. **Exit**: At project end = total CAPEX incl VAT (renovation cost = inflation)

**Constraint**: Any code replacement must be validated cell-by-cell against Excel outputs
before the Excel is decommissioned.

---

*Document generated from live Excel inspection. Cell references are exact.*
