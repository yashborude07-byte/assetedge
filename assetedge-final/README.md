# AssetEdge — Finance Intelligence

Full-stack personal finance app with:
- **Flask** backend (SQLite database, JWT auth)
- **Real-time stocks** via Yahoo Finance (no API key needed)
- **Portfolio tracker** with live price refresh + pie chart
- **OpenAI GPT-4o-mini** AI advisor with streaming chat
- Dashboard, Salary, Budget, Goals, EMI Calculator, Payments

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Add your OpenAI key (optional but recommended)
Edit `.env`:
```
OPENAI_API_KEY=sk-your-key-here
```
Get key at: https://platform.openai.com/api-keys

### 3. Run backend
```bash
python backend.py
```
Backend starts on **http://localhost:8000**

### 4. Open the app
Open `index.html` in your browser directly (double-click it).

---

## Features
| Feature | Details |
|---|---|
| Auth | Register / Login with JWT tokens |
| Dashboard | Income, EMI, Portfolio, Savings overview |
| Salary | Track gross salary and all deductions |
| Budget | Expense tracking with category pie chart |
| Portfolio | Holdings + live prices + sector allocation chart |
| Goals | Financial goals with progress tracking |
| EMI Loans | EMI calculator + amortization chart + loan tracker |
| Stocks | Live BSE/NSE prices + intraday chart + search |
| Payments | Payment history and transaction log |
| Cleo AI | GPT-4o-mini streaming chat with your real financial data |

---

## API Endpoints
All endpoints at `http://localhost:8000`

- `POST /api/auth/register` — Create account
- `POST /api/auth/login` — Sign in
- `GET  /api/dashboard` — Financial overview
- `GET  /api/stocks/market` — Live BSE blue chips
- `GET  /api/stocks/quote/<symbol>` — Single stock quote
- `GET  /api/stocks/intraday/<symbol>` — Intraday chart data
- `GET  /api/stocks/search/<keyword>` — Search stocks
- `POST /api/portfolio/live-prices` — Refresh portfolio prices
- `POST /api/advisor/chat` — AI chat (non-streaming)
- `GET  /api/advisor/stream?message=...` — AI chat (streaming)
