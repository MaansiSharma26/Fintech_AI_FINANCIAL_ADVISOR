from fastapi import FastAPI, Request, Cookie
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from typing import Optional
import requests

from database import (
    init_db, create_user, verify_user,
    create_session, get_user_from_token, delete_session,
    save_message
)

try:
    from market import get_stock
    MARKET_AVAILABLE = True
except ImportError:
    MARKET_AVAILABLE = False

app = FastAPI()
templates = Jinja2Templates(directory="templates")

init_db()

OPENROUTER_API_KEY = ""
MODEL = "openrouter/free"


class ChatRequest(BaseModel):
    message: str
    mode: str

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str


def get_current_user(session_token: Optional[str] = None):
    if not session_token:
        return None
    return get_user_from_token(session_token)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request, session_token: Optional[str] = Cookie(default=None)):
    user = get_current_user(session_token)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, session_token: Optional[str] = Cookie(default=None)):
    if get_current_user(session_token):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request})


@app.post("/api/register")
async def register(req: RegisterRequest):
    if len(req.username.strip()) < 3:
        return JSONResponse({"success": False, "error": "Username must be at least 3 characters"})
    if len(req.password) < 6:
        return JSONResponse({"success": False, "error": "Password must be at least 6 characters"})
    if "@" not in req.email:
        return JSONResponse({"success": False, "error": "Invalid email address"})
    result = create_user(req.username, req.email, req.password)
    return JSONResponse(result)


@app.post("/api/login")
async def login(req: LoginRequest):
    user = verify_user(req.email, req.password)
    if not user:
        return JSONResponse({"success": False, "error": "Invalid email or password"})
    token = create_session(user["id"])
    response = JSONResponse({"success": True, "username": user["username"]})
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        max_age=60 * 60 * 24 * 7,
        samesite="lax"
    )
    return response


@app.post("/api/logout")
async def logout(session_token: Optional[str] = Cookie(default=None)):
    if session_token:
        delete_session(session_token)
    response = JSONResponse({"success": True})
    response.delete_cookie("session_token")
    return response


def system_prompt(mode):
    base_rules = """
You are an advanced AI Financial Advisor designed to help users understand, plan, and make better financial decisions.

GLOBAL RULES:
- Always respond in structured sections with clear headings and emojis
- Use bullet points instead of long paragraphs
- Each section must contain meaningful, slightly detailed explanations (not one-liners)
- Keep responses beginner-friendly but insightful
- Avoid unnecessary jargon; explain when used
- Give practical, real-world advice (not textbook definitions)
- Do NOT ask unnecessary questions if you can reasonably answer
- If assumptions are made, clearly state them
- Always think like a real financial advisor helping a client
- Prefer clarity + usefulness over complexity

User profile: Assume beginner investor unless specified otherwise
"""
    if mode == "investment":
        return base_rules + """
MODE: Investment Advisor
RESPONSE FORMAT:
🎯 Investment Summary
💰 Suggested Investment Options (3–5 with brief explanation each)
📊 Strategy (Step-by-Step Plan with allocation %)
⚠️ Risks & Considerations
🚀 Next Steps
📊 Confidence Level: Low / Medium / High
"""
    if mode == "stocks":
        return base_rules + """
MODE: Stock Market Advisor
RESPONSE FORMAT:
📌 Company / Topic Overview
📊 Key Insights
📈 Bull Case (2–3 reasons)
📉 Bear Case (2–3 reasons)
⚠️ Risks
💡 Verdict: Long-term / Short-term / Speculative / Avoid
📊 Confidence Level: Low / Medium / High
"""
    if mode == "savings":
        return base_rules + """
MODE: Savings Coach
RESPONSE FORMAT:
🎯 Goal Understanding
💡 Smart Saving Strategy
📊 Suggested Plan (monthly breakdown or % allocation)
⚠️ Common Mistakes to Avoid (2–3)
🚀 Action Steps
📊 Confidence Level: Low / Medium / High
"""
    return base_rules + """
MODE: General Finance
RESPONSE FORMAT:
📘 Explanation
💡 Why It Matters
📊 Example
⚠️ Practical Tip
📊 Confidence Level: Low / Medium / High
"""


def extract_stock(user_text):
    stocks = {
        "apple": "AAPL", "tesla": "TSLA", "nvidia": "NVDA",
        "amazon": "AMZN", "google": "GOOGL", "microsoft": "MSFT"
    }
    for name, ticker in stocks.items():
        if name in user_text:
            return ticker
    return None


@app.post("/chat")
async def chat(req: ChatRequest, session_token: Optional[str] = Cookie(default=None)):
    user = get_current_user(session_token)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)

    save_message(user["id"], req.mode, "user", req.message)

    if req.mode == "stocks" and MARKET_AVAILABLE:
        ticker = extract_stock(req.message.lower())
        if ticker:
            s = get_stock(ticker)
            if s:
                reply = f"""📊 {s['symbol']} Quick Snapshot

💰 Current Price: ${s['price']}
📉 Daily Change: {round(s['percent'], 2)}%

📌 Insight:
- This gives you a quick view of the stock's current movement.
- For deeper analysis, ask: "Analyze {s['symbol']} stock"
"""
                save_message(user["id"], req.mode, "assistant", reply)
                return {"reply": reply}

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "Finance AI Advisor"
    }
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt(req.mode)},
            {"role": "user", "content": req.message}
        ]
    }

    try:
        r = requests.post(url, headers=headers, json=payload)
        data = r.json()
        if "choices" not in data:
            error_msg = data.get("error", {}).get("message", "Unknown API error")
            return {"reply": f"⚠️ AI Error: {error_msg}\n\nTry again in a moment."}
        reply = data["choices"][0]["message"]["content"]
        save_message(user["id"], req.mode, "assistant", reply)
        return {"reply": reply}
    except Exception as e:
        return {"reply": f"⚠️ Something went wrong: {str(e)}\n\nPlease try again."}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("finance:app", host="127.0.0.1", port=8000, reload=True)