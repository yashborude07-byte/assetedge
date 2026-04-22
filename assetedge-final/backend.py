"""
AssetEdge — Flask Backend
  • SQLite database
  • JWT authentication
  • Yahoo Finance (real-time stocks & portfolio prices)
  • OpenAI GPT-4o-mini AI advisor with streaming
  • Full CORS support

Run:
    pip install -r requirements.txt
    python backend.py
"""


"""
AssetEdge Flask Backend v4.0

SQLite database with WAL mode, JWT authentication, 
Yahoo Finance integration for Indian stocks (.BO/.NS),
OpenAI GPT-4o-mini AI financial advisor with streaming SSE.

Endpoints:
- /api/auth/* - User registration/login
- /api/dashboard - Financial overview
- /api/portfolio - Holdings & live prices
- /api/advisor/chat - AI advisor
"""


import os
import time
import json
import sqlite3
from datetime import datetime, timedelta
from contextlib import contextmanager
from functools import wraps

import bcrypt
import requests
from flask import Flask, request, jsonify, Response, g
from flask_cors import CORS
import jwt as pyjwt
from dotenv import load_dotenv

load_dotenv()

# ── Config ─────────────────────────────────────────────────────
DB_PATH        = os.getenv("DB_PATH",    "assetedge.db")
JWT_SECRET     = os.getenv("JWT_SECRET", "AssetEdge2024SuperSecretKey!!")
JWT_ALGO       = "HS256"
JWT_HOURS      = 168
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*"}})

# ── Database ───────────────────────────────────────────────────
def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

@contextmanager
def db():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as c:
        c.executescript("""
        -- Users table
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL DEFAULT '',
            monthly_income REAL DEFAULT 0,
            occupation TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Salary entries
        CREATE TABLE IF NOT EXISTS salary_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            month TEXT DEFAULT '',
            gross_amount REAL DEFAULT 0,
            tax_deducted REAL DEFAULT 0,
            pf_contribution REAL DEFAULT 0,
            professional_tax REAL DEFAULT 0,
            other_deductions REAL DEFAULT 0,
            net_in_hand REAL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Budgets
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT DEFAULT 'Other',
            planned_amount REAL DEFAULT 0,
            actual_amount REAL DEFAULT 0,
            month TEXT DEFAULT '',
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Holdings
        CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            symbol TEXT DEFAULT '',
            name TEXT DEFAULT '',
            type TEXT DEFAULT 'STOCK',
            sector TEXT DEFAULT 'Other',
            quantity REAL DEFAULT 0,
            buy_price REAL DEFAULT 0,
            current_price REAL DEFAULT 0,
            invested_value REAL DEFAULT 0,
            current_value REAL DEFAULT 0,
            pnl REAL DEFAULT 0,
            pnl_percent REAL DEFAULT 0,
            buy_date TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Goals
        CREATE TABLE IF NOT EXISTS goals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT DEFAULT '',
            target_amount REAL DEFAULT 0,
            saved_amount REAL DEFAULT 0,
            deadline_months INTEGER DEFAULT 12,
            icon TEXT DEFAULT '🎯',
            color TEXT DEFAULT '#634ef2',
            feasibility TEXT DEFAULT 'feasible',
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Loans
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT DEFAULT '',
            bank TEXT DEFAULT '',
            type TEXT DEFAULT 'PERSONAL',
            principal REAL DEFAULT 0,
            interest_rate REAL DEFAULT 0,
            tenure_months INTEGER DEFAULT 12,
            emi_amount REAL DEFAULT 0,
            total_interest REAL DEFAULT 0,
            total_payment REAL DEFAULT 0,
            paid_months INTEGER DEFAULT 0,
            status TEXT DEFAULT 'ACTIVE',
            created_at TEXT DEFAULT (datetime('now'))
        );

        -- Transactions
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            amount REAL DEFAULT 0,
            type TEXT DEFAULT 'DEBIT',
            category TEXT DEFAULT 'Other',
            note TEXT DEFAULT '',
            date TEXT DEFAULT (datetime('now'))
        );
        """)
    print(f"✅ AssetEdge Flask started. DB: {DB_PATH}")

# ── Auth helpers ───────────────────────────────────────────────
def hash_pw(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def verify_pw(pw, h):
    try:
        return bcrypt.checkpw(pw.encode(), h.encode())
    except Exception:
        return False

def make_token(uid):
    payload = {"sub": str(uid), "exp": datetime.utcnow() + timedelta(hours=JWT_HOURS)}
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)

def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"detail": "Missing token"}), 401
        try:
            payload = pyjwt.decode(auth[7:].strip(), JWT_SECRET, algorithms=[JWT_ALGO])
            g.uid = str(payload["sub"])
        except pyjwt.ExpiredSignatureError:
            return jsonify({"detail": "Token expired"}), 401
        except Exception:
            return jsonify({"detail": "Invalid token"}), 401
        return f(*args, **kwargs)
    return decorated

def row_dict(r):
    return dict(r) if r else None

def rows_list(rs):
    return [dict(r) for r in rs]

def err(msg, code=400):
    return jsonify({"detail": msg}), code

# ── Business logic ─────────────────────────────────────────────
def latest_income(uid):
    with db() as c:
        r = c.execute(
            "SELECT net_in_hand FROM salary_entries WHERE user_id=? ORDER BY created_at DESC LIMIT 1",
            (uid,)
        ).fetchone()
        if r:
            return float(r[0])
        u = c.execute("SELECT monthly_income FROM users WHERE id=?", (uid,)).fetchone()
        return float(u[0]) if u else 0.0

def calc_emi(p, r, m):
    if r == 0 or m == 0:
        emi = p / m if m else 0
    else:
        rv = r / 100 / 12
        emi = p * rv * (1 + rv) ** m / ((1 + rv) ** m - 1)
    total = round(emi * m, 2)
    return round(emi, 2), round(total - p, 2), total

def apply_pl(h):
    inv = round(float(h.get("buy_price", 0)) * float(h.get("quantity", 0)), 2)
    cur = round(float(h.get("current_price", 0)) * float(h.get("quantity", 0)), 2)
    pnl = round(cur - inv, 2)
    pct = round(pnl / inv * 100, 2) if inv > 0 else 0.0
    h.update({"invested_value": inv, "current_value": cur, "pnl": pnl, "pnl_percent": pct})
    return h

def check_feasibility(income, target, saved, months):
    rem = float(target) - float(saved)
    if rem <= 0:
        return "completed"
    if months <= 0 or income <= 0:
        return "infeasible"
    needed = rem / months
    if needed <= income * 0.3:
        return "feasible"
    if needed <= income * 0.6:
        return "stretch"
    return "infeasible"

def budget_health(income, spent):
    if income <= 0:
        return "ok"
    r = spent / income
    if r >= 1.0:
        return "critical"
    if r >= 0.8:
        return "warning"
    return "ok"

def user_dict(r):
    return {
        "id": r["id"], "email": r["email"], "name": r["name"],
        "monthlyIncome": r["monthly_income"], "occupation": r["occupation"]
    }

# ── Yahoo Finance ──────────────────────────────────────────────
YF_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://finance.yahoo.com/",
}

def yahoo_quote(symbol):
    for host in ["query1", "query2"]:
        try:
            r = requests.get(
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}",
                headers=YF_HEADERS,
                params={"interval": "1d", "range": "5d", "includePrePost": "false"},
                timeout=12
            )
            if r.status_code != 200:
                continue
            result = r.json().get("chart", {}).get("result")
            if not result:
                continue
            meta = result[0]["meta"]
            price = float(meta.get("regularMarketPrice") or meta.get("previousClose") or 0)
            prev  = float(meta.get("chartPreviousClose") or meta.get("previousClose") or price)
            chg   = round(price - prev, 2)
            pct   = round(chg / prev * 100, 2) if prev else 0
            return {
                "symbol":    meta.get("symbol", symbol),
                "name":      meta.get("longName") or meta.get("shortName", ""),
                "price":     price,
                "change":    chg,
                "changePct": f"{pct:+.2f}%",
                "high":      float(meta.get("regularMarketDayHigh") or price),
                "low":       float(meta.get("regularMarketDayLow") or price),
                "prevClose": prev,
                "volume":    str(meta.get("regularMarketVolume") or 0),
                "currency":  meta.get("currency", "INR"),
            }
        except Exception:
            continue
    return {"symbol": symbol, "price": 0, "change": 0, "changePct": "0.00%", "error": "unavailable"}

def yahoo_intraday(symbol):
    for host in ["query1", "query2"]:
        try:
            r = requests.get(
                f"https://{host}.finance.yahoo.com/v8/finance/chart/{symbol}",
                headers=YF_HEADERS,
                params={"interval": "5m", "range": "1d"},
                timeout=12
            )
            if r.status_code != 200:
                continue
            res    = r.json()["chart"]["result"][0]
            ts     = res.get("timestamp", [])
            closes = res["indicators"]["quote"][0].get("close", [])
            if not ts:
                continue
            return [
                {"time": datetime.utcfromtimestamp(t).strftime("%H:%M"), "close": round(float(c), 2)}
                for t, c in zip(ts, closes) if c is not None
            ]
        except Exception:
            continue
    return []

def yahoo_search(keyword):
    for host in ["query1", "query2"]:
        try:
            r = requests.get(
                f"https://{host}.finance.yahoo.com/v1/finance/search",
                headers=YF_HEADERS,
                params={"q": keyword, "quotesCount": 10, "newsCount": 0},
                timeout=10
            )
            if r.status_code != 200:
                continue
            return [
                {
                    "symbol":   q.get("symbol", ""),
                    "name":     q.get("longname") or q.get("shortname", ""),
                    "exchange": q.get("exchange", ""),
                    "currency": q.get("currency", "INR"),
                }
                for q in r.json().get("quotes", []) if q.get("symbol")
            ]
        except Exception:
            continue
    return []

BSE_SYMBOLS = [
    "RELIANCE.BO", "TCS.BO", "INFY.BO", "HDFCBANK.BO",
    "ICICIBANK.BO", "SBIN.BO", "BAJFINANCE.BO", "WIPRO.BO",
    "ADANIENT.BO", "MARUTI.BO", "SUNPHARMA.BO", "TATAMOTORS.BO",
]

# ── OpenAI AI Advisor ──────────────────────────────────────────
CLEO_SYSTEM = """You are Cleo, an expert AI financial advisor inside AssetEdge for Indian users.
Help with budgeting, investments, EMI/loans, tax saving, and wealth-building.
You receive the user's real financial data in each message. Be concise, specific, and actionable.
Use ₹ for Rupees. Keep answers under 250 words unless detail is truly needed.
Format responses with clear line breaks. Be warm, encouraging, and professional."""

def build_ctx(uid):
    with db() as c:
        sal  = c.execute("SELECT net_in_hand FROM salary_entries WHERE user_id=? ORDER BY created_at DESC LIMIT 1", (uid,)).fetchone()
        loans= rows_list(c.execute("SELECT emi_amount FROM loans WHERE user_id=? AND status='ACTIVE'", (uid,)).fetchall())
        hold = rows_list(c.execute("SELECT current_value,invested_value FROM holdings WHERE user_id=?", (uid,)).fetchall())
        goals= rows_list(c.execute("SELECT id FROM goals WHERE user_id=?", (uid,)).fetchall())
        buds = rows_list(c.execute("SELECT actual_amount FROM budgets WHERE user_id=?", (uid,)).fetchall())
        usr  = row_dict(c.execute("SELECT monthly_income FROM users WHERE id=?", (uid,)).fetchone())
    income    = float(sal[0]) if sal else float((usr or {}).get("monthly_income", 0))
    total_emi = sum(float(l["emi_amount"]) for l in loans)
    pv = sum(float(h["current_value"]) for h in hold)
    pc = sum(float(h["invested_value"]) for h in hold)
    spent = sum(float(b["actual_amount"]) for b in buds)
    return {
        "netIncome":      round(income, 2),
        "totalEMI":       round(total_emi, 2),
        "emiPercent":     round(total_emi / income * 100, 1) if income > 0 else 0,
        "portfolioValue": round(pv, 2),
        "portfolioReturn":round((pv - pc) / pc * 100, 2) if pc > 0 else 0,
        "totalSpent":     round(spent, 2),
        "savingsRate":    round((income - total_emi - spent) / income * 100, 1) if income > 0 else 0,
        "activeLoans":    len(loans),
        "activeGoals":    len(goals),
        "holdingsCount":  len(hold),
    }

def ai_fallback(message, ctx):
    msg = message.lower()
    inc = ctx.get("netIncome", 0)
    if any(w in msg for w in ["budget", "spend", "expense"]):
        return (f"Your income is ₹{inc:,.0f}/month and you've spent ₹{ctx.get('totalSpent', 0):,.0f}.\n\n"
                f"Savings rate: {ctx.get('savingsRate', 0):.1f}%.\n\n"
                f"*Set OPENAI_API_KEY in .env to unlock full GPT-4o advice.*")
    if any(w in msg for w in ["loan", "emi", "debt"]):
        return (f"You have {ctx.get('activeLoans', 0)} active loan(s), "
                f"EMI = ₹{ctx.get('totalEMI', 0):,.0f}/month ({ctx.get('emiPercent', 0):.1f}% of income).\n\n"
                f"Recommended: keep EMI below 40% of income.\n\n"
                f"*Set OPENAI_API_KEY in .env for full GPT-4o advice.*")
    if any(w in msg for w in ["stock", "portfolio", "invest"]):
        return (f"Portfolio: ₹{ctx.get('portfolioValue', 0):,.0f} "
                f"({ctx.get('portfolioReturn', 0):+.1f}% return) "
                f"across {ctx.get('holdingsCount', 0)} holdings.\n\n"
                f"*Set OPENAI_API_KEY in .env for full GPT-4o advice.*")
    return (f"Hi! I'm Cleo, your AI financial advisor. 👋\n\n"
            f"Savings rate: {ctx.get('savingsRate', 0):.1f}% · EMI burden: {ctx.get('emiPercent', 0):.1f}%\n\n"
            f"*Add OPENAI_API_KEY in .env to unlock full GPT-4o-powered advice!*")

# ══════════════════════════════════════════════════════════════
#  ROUTES
# ══════════════════════════════════════════════════════════════

@app.get("/")
def root():
    return jsonify({"status": "ok", "service": "AssetEdge Flask API", "version": "4.0"})

@app.get("/api/auth/ping")
def ping():
    return jsonify({"status": "ok", "service": "AssetEdge", "time": datetime.utcnow().isoformat()})

# ── Auth ───────────────────────────────────────────────────────
@app.post("/api/auth/register")
def register():
    b = request.get_json() or {}
    email = (b.get("email") or "").strip().lower()
    name  = (b.get("name") or "").strip()
    pw    = b.get("password") or ""
    if "@" not in email or "." not in email:
        return err("Enter a valid email address")
    if len(pw) < 6:
        return err("Password must be at least 6 characters")
    if not name:
        return err("Name is required")
    with db() as c:
        if c.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone():
            return err("Email already registered — please sign in", 409)
        c.execute(
            "INSERT INTO users(email,name,password_hash,monthly_income,occupation) VALUES(?,?,?,?,?)",
            (email, name, hash_pw(pw), float(b.get("monthly_income") or 0), b.get("occupation") or "")
        )
        row = row_dict(c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())
    return jsonify({"token": make_token(row["id"]), "user": user_dict(row)})

@app.post("/api/auth/login")
def login():
    b = request.get_json() or {}
    email = (b.get("email") or "").strip().lower()
    with db() as c:
        row = row_dict(c.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone())
    if not row or not verify_pw(b.get("password") or "", row["password_hash"]):
        return err("Invalid email or password", 401)
    return jsonify({"token": make_token(row["id"]), "user": user_dict(row)})

@app.get("/api/auth/me")
@require_auth
def me():
    with db() as c:
        row = row_dict(c.execute("SELECT * FROM users WHERE id=?", (g.uid,)).fetchone())
    if not row:
        return err("User not found", 404)
    return jsonify(user_dict(row))

# ── Dashboard ──────────────────────────────────────────────────
@app.get("/api/dashboard")
@require_auth
def dashboard():
    uid = g.uid
    with db() as c:
        salaries = rows_list(c.execute("SELECT * FROM salary_entries WHERE user_id=? ORDER BY created_at DESC", (uid,)).fetchall())
        loans    = rows_list(c.execute("SELECT * FROM loans WHERE user_id=? AND status='ACTIVE'", (uid,)).fetchall())
        holdings = rows_list(c.execute("SELECT * FROM holdings WHERE user_id=?", (uid,)).fetchall())
        goals    = rows_list(c.execute("SELECT * FROM goals WHERE user_id=?", (uid,)).fetchall())
        budgets  = rows_list(c.execute("SELECT * FROM budgets WHERE user_id=?", (uid,)).fetchall())
        usr      = row_dict(c.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    income     = float(salaries[0]["net_in_hand"]) if salaries else float((usr or {}).get("monthly_income", 0))
    total_emi  = sum(float(l["emi_amount"]) for l in loans)
    port_curr  = sum(float(h["current_value"]) for h in holdings)
    port_cost  = sum(float(h["invested_value"]) for h in holdings)
    total_spent= sum(float(b["actual_amount"]) for b in budgets)
    savings    = income - total_emi - total_spent
    return jsonify({
        "income":         round(income, 2),
        "totalEMI":       round(total_emi, 2),
        "emiPercent":     round(total_emi / income * 100, 1) if income > 0 else 0,
        "portfolioValue": round(port_curr, 2),
        "portfolioReturn":round((port_curr - port_cost) / port_cost * 100, 1) if port_cost > 0 else 0,
        "totalSpent":     round(total_spent, 2),
        "savings":        round(savings, 2),
        "savingsRate":    round(savings / income * 100, 1) if income > 0 else 0,
        "activeLoans":    len(loans),
        "activeGoals":    len(goals),
        "salaryTrend":    [{"month": s["month"], "net": s["net_in_hand"]} for s in reversed(salaries[:6])],
    })

# ── Salary ─────────────────────────────────────────────────────
@app.get("/api/salary")
@require_auth
def get_salary():
    with db() as c:
        return jsonify(rows_list(c.execute("SELECT * FROM salary_entries WHERE user_id=? ORDER BY created_at DESC", (g.uid,)).fetchall()))

@app.post("/api/salary")
@require_auth
def add_salary():
    b = request.get_json() or {}
    month = b.get("month", "")
    gross = float(b.get("gross_amount") or 0)
    if not month:
        return err("Month is required")
    if gross <= 0:
        return err("Gross amount must be positive")
    net = round(gross - float(b.get("tax_deducted") or 0) - float(b.get("pf_contribution") or 0)
                - float(b.get("professional_tax") or 0) - float(b.get("other_deductions") or 0), 2)
    with db() as c:
        c.execute("""
            INSERT INTO salary_entries (
                user_id, month, gross_amount, tax_deducted, 
                pf_contribution, professional_tax, other_deductions, net_in_hand
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            g.uid, month, gross, float(b.get("tax_deducted") or 0), 
            float(b.get("pf_contribution") or 0),
            float(b.get("professional_tax") or 0), float(b.get("other_deductions") or 0), net
        ))
        return jsonify(row_dict(c.execute("SELECT * FROM salary_entries WHERE rowid=last_insert_rowid()").fetchone()))

@app.delete("/api/salary/<int:eid>")
@require_auth
def del_salary(eid):
    with db() as c:
        c.execute("DELETE FROM salary_entries WHERE id=? AND user_id=?", (eid, g.uid))
    return jsonify({"message": "Removed"})

# ── Budget ─────────────────────────────────────────────────────
@app.get("/api/budget")
@require_auth
def get_budget():
    with db() as c:
        items = rows_list(c.execute("SELECT * FROM budgets WHERE user_id=? ORDER BY created_at DESC", (g.uid,)).fetchall())
    income = latest_income(g.uid)
    spent  = sum(float(b["actual_amount"]) for b in items)
    return jsonify({"budgets": items, "income": income, "totalSpent": spent, "health": budget_health(income, spent)})

@app.post("/api/budget/expense")
@require_auth
def add_expense():
    b = request.get_json() or {}
    amt = float(b.get("actual_amount") or 0)
    if amt <= 0:
        return err("Amount must be positive")
    with db() as c:
        c.execute("""
            INSERT INTO budgets (
                user_id, category, planned_amount, actual_amount, month, note
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            g.uid, b.get("category") or "Other", float(b.get("planned_amount") or 0),
            amt, b.get("month") or "", b.get("note") or ""
        ))
        return jsonify(row_dict(c.execute("SELECT * FROM budgets WHERE rowid=last_insert_rowid()").fetchone()))

@app.delete("/api/budget/<int:bid>")
@require_auth
def del_budget(bid):
    with db() as c:
        c.execute("DELETE FROM budgets WHERE id=? AND user_id=?", (bid, g.uid))
    return jsonify({"message": "Removed"})

# ── Portfolio ──────────────────────────────────────────────────
@app.get("/api/portfolio")
@require_auth
def get_portfolio():
    with db() as c:
        holdings = rows_list(c.execute("SELECT * FROM holdings WHERE user_id=?", (g.uid,)).fetchall())
    holdings = [apply_pl(dict(h)) for h in holdings]
    ti = round(sum(h["invested_value"] for h in holdings), 2)
    tc = round(sum(h["current_value"] for h in holdings), 2)
    return jsonify({
        "holdings": holdings,
        "summary": {
            "totalInvested": ti, "totalCurrent": tc,
            "totalPnl": round(tc - ti, 2),
            "pnlPercent": round((tc - ti) / ti * 100, 2) if ti > 0 else 0,
        }
    })

@app.post("/api/portfolio/holdings")
@require_auth
def add_holding():
    b = request.get_json() or {}
    sym = (b.get("symbol") or "").upper().strip()
    qty = float(b.get("quantity") or 0)
    bp  = float(b.get("buy_price") or 0)
    if not sym:
        return err("Symbol is required")
    if qty <= 0:
        return err("Quantity must be positive")
    if bp <= 0:
        return err("Buy price must be positive")
    curr = float(b.get("current_price") or 0) or bp
    # Try live price from Yahoo Finance
    try:
        yf_sym = sym + ".BO" if "." not in sym else sym
        q = yahoo_quote(yf_sym)
        if q.get("price", 0) > 0:
            curr = q["price"]
            if not b.get("name"):
                b["name"] = q.get("name", "")
    except Exception:
        pass
    h = apply_pl({"buy_price": bp, "current_price": curr, "quantity": qty})
    with db() as c:
        c.execute("""
            INSERT INTO holdings (
                user_id, symbol, name, type, sector, quantity,
                buy_price, current_price, invested_value, current_value,
                pnl, pnl_percent, buy_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            g.uid, sym, b.get("name") or "", b.get("type") or "STOCK", b.get("sector") or "Other",
            qty, bp, curr, h["invested_value"], h["current_value"], 
            h["pnl"], h["pnl_percent"], b.get("buy_date") or ""
        ))
        return jsonify(row_dict(c.execute("SELECT * FROM holdings WHERE rowid=last_insert_rowid()").fetchone()))

@app.delete("/api/portfolio/holdings/<int:hid>")
@require_auth
def del_holding(hid):
    with db() as c:
        c.execute("DELETE FROM holdings WHERE id=? AND user_id=?", (hid, g.uid))
    return jsonify({"message": "Removed"})

@app.post("/api/portfolio/live-prices")
@require_auth
def refresh_prices():
    with db() as c:
        holdings = rows_list(c.execute("SELECT * FROM holdings WHERE user_id=?", (g.uid,)).fetchall())
    updated = []
    for h in holdings:
        sym   = h["symbol"]
        tried = [sym + ".BO", sym + ".NS", sym] if "." not in sym else [sym]
        price = 0
        for s in tried:
            q = yahoo_quote(s)
            if q.get("price", 0) > 0:
                price = q["price"]
                break
        if price > 0:
            nh = apply_pl({"buy_price": h["buy_price"], "current_price": price, "quantity": h["quantity"]})
            with db() as c2:
                c2.execute(
                    "UPDATE holdings SET current_price=?,current_value=?,pnl=?,pnl_percent=? WHERE id=?",
                    (price, nh["current_value"], nh["pnl"], nh["pnl_percent"], h["id"])
                )
            updated.append({"symbol": sym, "price": price, "pnl": nh["pnl"], "updated": True})
        else:
            updated.append({"symbol": sym, "price": h["current_price"], "updated": False})
    return jsonify(updated)

# ── Goals ──────────────────────────────────────────────────────
@app.get("/api/goals")
@require_auth
def get_goals():
    income = latest_income(g.uid)
    with db() as c:
        goals = rows_list(c.execute("SELECT * FROM goals WHERE user_id=? ORDER BY created_at DESC", (g.uid,)).fetchall())
    for goal in goals:
        goal["feasibility"] = check_feasibility(income, goal["target_amount"], goal["saved_amount"], goal["deadline_months"])
    return jsonify(goals)

@app.post("/api/goals")
@require_auth
def create_goal():
    b = request.get_json() or {}
    name   = (b.get("name") or "").strip()
    target = float(b.get("target_amount") or 0)
    if not name:
        return err("Name is required")
    if target <= 0:
        return err("Target amount must be positive")
    income = latest_income(g.uid)
    saved  = float(b.get("saved_amount") or 0)
    months = int(b.get("deadline_months") or 12)
    feat   = check_feasibility(income, target, saved, months)
    with db() as c:
        c.execute("""
            INSERT INTO goals (
                user_id, name, target_amount, saved_amount, deadline_months,
                icon, color, feasibility
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            g.uid, name, target, saved, months,
            b.get("icon") or "🎯", b.get("color") or "#634ef2", feat
        ))
        return jsonify(row_dict(c.execute("SELECT * FROM goals WHERE rowid=last_insert_rowid()").fetchone()))

@app.put("/api/goals/<int:gid>/contribute")
@require_auth
def contribute(gid):
    b = request.get_json() or {}
    amount = float(b.get("amount") or 0)
    with db() as c:
        goal = row_dict(c.execute("SELECT * FROM goals WHERE id=? AND user_id=?", (gid, g.uid)).fetchone())
        if not goal:
            return err("Goal not found", 404)
        new_saved = float(goal["saved_amount"]) + amount
        feat = "completed" if new_saved >= float(goal["target_amount"]) else goal["feasibility"]
        c.execute("UPDATE goals SET saved_amount=?,feasibility=? WHERE id=?", (new_saved, feat, gid))
        return jsonify(row_dict(c.execute("SELECT * FROM goals WHERE id=?", (gid,)).fetchone()))

@app.delete("/api/goals/<int:gid>")
@require_auth
def del_goal(gid):
    with db() as c:
        c.execute("DELETE FROM goals WHERE id=? AND user_id=?", (gid, g.uid))
    return jsonify({"message": "Removed"})

# ── EMI ────────────────────────────────────────────────────────
@app.post("/api/emi/calculate")
def emi_calc():
    b = request.get_json() or {}
    emi, interest, total = calc_emi(float(b.get("principal") or 0), float(b.get("interest_rate") or 0), int(b.get("tenure_months") or 0))
    return jsonify({"emi": emi, "totalInterest": interest, "totalPayment": total})

@app.post("/api/emi/amortization")
def amortization():
    b = request.get_json() or {}
    p, r_rate, m = float(b.get("principal") or 0), float(b.get("interest_rate") or 0), int(b.get("tenure_months") or 0)
    emi, _, _ = calc_emi(p, r_rate, m)
    rv = r_rate / 100 / 12
    balance = p
    schedule = []
    for month in range(1, m + 1):
        ip = round(balance * rv, 2) if rv > 0 else 0
        pp = round(emi - ip, 2)
        balance = max(0.0, round(balance - pp, 2))
        schedule.append({"month": month, "emi": emi, "principal": pp, "interest": ip, "balance": balance})
    return jsonify({"schedule": schedule, "emi": emi})

@app.get("/api/emi/loans")
@require_auth
def get_loans():
    with db() as c:
        return jsonify(rows_list(c.execute("SELECT * FROM loans WHERE user_id=? ORDER BY created_at DESC", (g.uid,)).fetchall()))

@app.post("/api/emi/loans")
@require_auth
def add_loan():
    b = request.get_json() or {}
    name = (b.get("name") or "").strip()
    principal = float(b.get("principal") or 0)
    if not name:
        return err("Loan name is required")
    if principal <= 0:
        return err("Principal must be positive")
    emi, interest, total = calc_emi(principal, float(b.get("interest_rate") or 0), int(b.get("tenure_months") or 12))
    with db() as c:
        c.execute(
            "INSERT INTO loans(user_id,name,bank,type,principal,interest_rate,tenure_months,emi_amount,total_interest,total_payment) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (g.uid, name, b.get("bank") or "", b.get("type") or "PERSONAL",
             principal, float(b.get("interest_rate") or 0), int(b.get("tenure_months") or 12),
             emi, interest, total)
        )
        return jsonify(row_dict(c.execute("SELECT * FROM loans WHERE rowid=last_insert_rowid()").fetchone()))

@app.put("/api/emi/loans/<int:lid>/pay")
@require_auth
def pay_loan(lid):
    with db() as c:
        loan = row_dict(c.execute("SELECT * FROM loans WHERE id=? AND user_id=?", (lid, g.uid)).fetchone())
        if not loan:
            return err("Loan not found", 404)
        paid   = int(loan["paid_months"]) + 1
        status = "CLOSED" if paid >= int(loan["tenure_months"]) else "ACTIVE"
        c.execute("UPDATE loans SET paid_months=?,status=? WHERE id=?", (paid, status, lid))
        return jsonify(row_dict(c.execute("SELECT * FROM loans WHERE id=?", (lid,)).fetchone()))

@app.delete("/api/emi/loans/<int:lid>")
@require_auth
def del_loan(lid):
    with db() as c:
        c.execute("DELETE FROM loans WHERE id=? AND user_id=?", (lid, g.uid))
    return jsonify({"message": "Removed"})

# ── Payments ───────────────────────────────────────────────────
@app.get("/api/payments/transactions")
@require_auth
def get_txns():
    with db() as c:
        return jsonify(rows_list(c.execute("SELECT * FROM transactions WHERE user_id=? ORDER BY date DESC", (g.uid,)).fetchall()))

@app.post("/api/payments/intent")
@require_auth
def create_intent():
    b = request.get_json() or {}
    amount = float(b.get("amount") or 0)
    if amount <= 0:
        return err("Amount must be positive")
    fid = f"pi_dev_{int(time.time()*1000)}"
    with db() as c:
        c.execute(
            "INSERT INTO transactions(user_id,amount,type,category,note) VALUES(?,?,?,?,?)",
            (g.uid, amount, "DEBIT", b.get("payment_for") or "Payment", b.get("note") or "")
        )
    return jsonify({
        "intentId": fid, "status": "SUCCEEDED",
        "amount": amount, "currency": (b.get("currency") or "INR").upper()
    })

# ── Stocks ─────────────────────────────────────────────────────
@app.get("/api/stocks/market")
def stock_market():
    results = []
    for sym in BSE_SYMBOLS:
        q = yahoo_quote(sym)
        results.append({
            "symbol":    sym.replace(".BO", "").replace(".NS", ""),
            "fullSymbol":sym,
            "price":     q.get("price", 0),
            "change":    q.get("change", 0),
            "changePct": q.get("changePct", "0.00%"),
            "name":      q.get("name", ""),
        })
    return jsonify(results)

@app.get("/api/stocks/quote/<symbol>")
def stock_quote(symbol):
    tried = [symbol + ".BO", symbol + ".NS", symbol] if "." not in symbol else [symbol]
    for s in tried:
        q = yahoo_quote(s)
        if q.get("price", 0) > 0:
            return jsonify(q)
    return jsonify(yahoo_quote(symbol))

@app.get("/api/stocks/search/<keyword>")
def stock_search(keyword):
    return jsonify(yahoo_search(keyword))

@app.get("/api/stocks/intraday/<symbol>")
def stock_intraday(symbol):
    tried = [symbol + ".BO", symbol + ".NS", symbol] if "." not in symbol else [symbol]
    for s in tried:
        data = yahoo_intraday(s)
        if data:
            return jsonify({"symbol": symbol, "data": data})
    return jsonify({"symbol": symbol, "data": []})

# ── AI Advisor ─────────────────────────────────────────────────
@app.post("/api/advisor/chat")
@require_auth
def advisor_chat():
    b   = request.get_json() or {}
    ctx = build_ctx(g.uid)
    user_msg = f"[My Financial Data: {json.dumps(ctx)}]\n\nQuestion: {b.get('message','')}"
    messages = [{"role": "system", "content": CLEO_SYSTEM}]
    for h in (b.get("history") or [])[-8:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": str(h["content"])})
    messages.append({"role": "user", "content": user_msg})

    if not OPENAI_API_KEY:
        return jsonify({"reply": ai_fallback(b.get("message", ""), ctx), "context": ctx})
    try:
        r = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
            json={"model": "gpt-4o-mini", "max_tokens": 700, "temperature": 0.7, "messages": messages},
            timeout=30
        )
        r.raise_for_status()
        reply = r.json()["choices"][0]["message"]["content"]
        return jsonify({"reply": reply, "context": ctx})
    except Exception as e:
        return jsonify({"reply": ai_fallback(b.get("message", ""), ctx) + f"\n\n*(Error: {e})*", "context": ctx})

@app.get("/api/advisor/stream")
@require_auth
def advisor_stream():
    message = request.args.get("message", "")
    ctx     = build_ctx(g.uid)
    user_msg= f"[My Financial Data: {json.dumps(ctx)}]\n\nQuestion: {message}"
    messages= [
        {"role": "system", "content": CLEO_SYSTEM},
        {"role": "user",   "content": user_msg},
    ]

    if not OPENAI_API_KEY:
        def fb():
            for word in ai_fallback(message, ctx).split():
                yield f"data: {json.dumps(word + ' ')}\n\n"
            yield "data: [DONE]\n\n"
        return Response(fb(), mimetype="text/event-stream")

    def gen():
        try:
            with requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"},
                json={"model": "gpt-4o-mini", "max_tokens": 700, "temperature": 0.7,
                      "messages": messages, "stream": True},
                stream=True, timeout=60
            ) as resp:
                for raw in resp.iter_lines():
                    if not raw:
                        continue
                    line = raw.decode("utf-8") if isinstance(raw, bytes) else raw
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        yield "data: [DONE]\n\n"
                        break
                    try:
                        ev    = json.loads(chunk)
                        delta = ev.get("choices", [{}])[0].get("delta", {}).get("content", "")
                        if delta:
                            yield f"data: {json.dumps(delta)}\n\n"
                    except Exception:
                        pass
        except Exception:
            yield f"data: {json.dumps(ai_fallback(message, ctx))}\n\ndata: [DONE]\n\n"

    return Response(gen(), mimetype="text/event-stream")


# ── Run ────────────────────────────────────────────────────────
if __name__ == "__main__":
    init_db()
    print("🚀 Starting AssetEdge on http://localhost:8000")
    app.run(host="0.0.0.0", port=8000, debug=False)
