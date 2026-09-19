import requests
from datetime import datetime, timedelta

HISTORY_URL = "https://query2.finance.yahoo.com/v8/finance/chart"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin": "https://finance.yahoo.com",
    "Referer": "https://finance.yahoo.com/",
}


def get_stock(symbol: str):
    """Get current price and daily change using v8 chart endpoint."""
    try:
        url = f"{HISTORY_URL}/{symbol}?interval=1d&range=5d"
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()

        result = data["chart"]["result"][0]
        meta   = result["meta"]

        price = (
            meta.get("regularMarketPrice")
            or meta.get("previousClose")
            or meta.get("chartPreviousClose")
        )
        prev  = meta.get("chartPreviousClose") or meta.get("previousClose") or price

        if not price:
            print(f"[market] get_stock({symbol}): no price found in meta")
            return None

        price   = float(price)
        prev    = float(prev)
        change  = round(price - prev, 4)
        percent = round((change / prev) * 100, 4) if prev else 0.0

        print(f"[market] get_stock({symbol}): ${price} ({percent:+.2f}%)")
        return {
            "symbol":  meta.get("symbol", symbol),
            "price":   round(price, 2),
            "change":  change,
            "percent": percent,
        }

    except Exception as e:
        print(f"[market] get_stock({symbol}) error: {e}")
        return None


def get_stock_history(symbol: str, days: int = 30):
    """
    Fetch daily closing prices for the last `days` trading days.
    Returns list of {"date": "MMM DD", "price": float} sorted oldest → newest.
    """
    try:
        url = f"{HISTORY_URL}/{symbol}?interval=1d&range=3mo"
        r = requests.get(url, headers=HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()

        chart_result = data["chart"]["result"]
        if not chart_result:
            print(f"[market] get_stock_history({symbol}): empty result")
            return None

        chart      = chart_result[0]
        timestamps = chart.get("timestamp", [])
        closes     = chart["indicators"]["quote"][0].get("close", [])

        if not timestamps or not closes:
            print(f"[market] get_stock_history({symbol}): no timestamps or closes")
            return None

        history = []
        for ts, price in zip(timestamps, closes):
            if price is None:
                continue
            dt = datetime.fromtimestamp(ts)
            history.append({
                "date":  dt.strftime("%b %d"),
                "price": round(float(price), 2),
            })

        # Return the most recent `days` data points
        result = history[-days:] if len(history) > days else history
        print(f"[market] get_stock_history({symbol}): {len(result)} points returned")
        return result if len(result) >= 2 else None

    except Exception as e:
        print(f"[market] get_stock_history({symbol}) error: {e}")
        return None


def market_summary():
    """Quick summary of major US market indexes."""
    indexes = ["^GSPC", "^DJI", "^IXIC"]
    results = []
    for i in indexes:
        s = get_stock(i)
        if s:
            results.append(s)
    return results