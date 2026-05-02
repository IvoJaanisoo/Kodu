# Spinnaker Rental Model — Deployment Guide

## Folder structure
```
spinnaker/
├── backend/
│   ├── main.py                          ← FastAPI backend (provided)
│   └── Spinnaker.xlsx     ← Your Excel model (place here)
├── frontend/
│   └── index.html                       ← UI (open in browser or serve)
├── scripts/
│   └── recalc.py                        ← LibreOffice recalculation script
└── README.md
```

## Requirements
```bash
pip install fastapi uvicorn openpyxl python-multipart
# LibreOffice must be installed:
# Ubuntu: sudo apt install libreoffice
# macOS:  brew install --cask libreoffice
```

## Start backend
```bash
cd spinnaker
uvicorn backend.main:app --reload --port 8000
```

## Open frontend
```
Open frontend/index.html in your browser.
Or serve: python -m http.server 3000 --directory frontend
```

## API endpoints
- GET  http://localhost:8000/health        — health check
- GET  http://localhost:8000/defaults      — all green cell values
- POST http://localhost:8000/calculate     — run calculation

## How it works
1. Frontend collects slider values (UI fields)
2. POST /calculate sends JSON payload
3. Backend copies Excel to /tmp, writes ONLY green cells
4. LibreOffice recalculates all formulas
5. Output cells are read and returned as JSON
6. Frontend displays results — nothing is calculated outside Excel

## Cell reference map
See architecture.md for the full input/output cell mapping table.
