# -*- coding: utf-8 -*-
"""Forex Analysis App — Flask backend: price data + 4 analysis engines."""
import re, math, html as htmlmod, datetime as dt, requests
from flask import Flask, jsonify, send_from_directory

app = Flask(__name__, static_folder="static", static_url_path="/static")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

SYMBOLS = {
    "EURUSD": "EUR/USD", "GBPUSD": "GBP/USD", "USDJPY": "USD/JPY", "USDCHF": "USD/CHF",
    "AUDUSD": "AUD/USD", "USDCAD": "USD/CAD", "NZDUSD": "NZD/USD", "EURGBP": "EUR/GBP",
    "EURJPY": "EUR/JPY", "GBPJPY": "GBP/JPY", "XAUUSD": "XAU/USD", "XAGUSD": "XAG/USD",
}

# ---------------------------------------------------------------- price data
def yahoo(symbol):
    r = requests.get(
        f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}=X",
        params={"range": "6mo", "interval": "1d"}, headers=UA, timeout=15)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    ts = res.get("timestamp", [])
    q = res["indicators"]["quote"][0]
    rows = [(dt.datetime.fromtimestamp(t, dt.timezone.utc).date(), c)
            for t, c in zip(ts, q.get("close", [])) if c is not None]
    meta = res["meta"]
    return rows, meta.get("regularMarketPrice"), meta

NEWS_FEEDS = [
    ("Investing.com", "https://www.investing.com/rss/news_285.rss"),
    ("ForexLive", "https://www.forexlive.com/feed/news"),
    ("WSJ Markets", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("Investing (Forex)", "https://www.investing.com/rss/news_1.rss"),
]

def _clean(s):
    s = re.sub(r"<!\[CDATA\[|\]\]>", "", s)
    return htmlmod.unescape(re.sub(r"<[^>]+>", "", s)).strip()

def parse_rss(xml, source, limit=10):
    out = []
    for m in re.finditer(r"<item>(.*?)</item>", xml, re.S):
        it = m.group(1)
        tm = re.search(r"<title>(.*?)</title>", it, re.S)
        if not tm:
            continue
        title = _clean(tm.group(1))
        lm = re.search(r"<link>(.*?)</link>", it, re.S)
        link = _clean(lm.group(1)) if lm else ""
        dm = re.search(r"<pubDate>(.*?)</pubDate>", it)
        date = _clean(dm.group(1)) if dm else ""
        try:
            date = dt.datetime.strptime(date.split(" +")[0], "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
        except Exception:
            pass
        out.append({"title": title, "date": date, "source": source, "link": link})
        if len(out) >= limit:
            break
    return out

def news_items(symbol):
    """Aggregate news from major financial outlets + symbol-specific Google News."""
    items = []
    for source, url in NEWS_FEEDS:
        try:
            r = requests.get(url, headers=UA, timeout=12)
            if r.ok:
                items += parse_rss(r.text, source, 8)
        except Exception:
            pass
    # symbol-specific headlines via Google News
    try:
        q = requests.utils.quote(f"{symbol} forecast")
        r = requests.get(
            f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en",
            headers=UA, timeout=12)
        if r.ok:
            items += parse_rss(r.text, "Google News", 6)
    except Exception:
        pass
    # dedupe by title
    seen, uniq = set(), []
    for it in items:
        k = it["title"].lower()[:80]
        if k not in seen:
            seen.add(k)
            uniq.append(it)
    return uniq[:24]

# ---------------------------------------------------------------- indicators
def ema_series(vals, n):
    k = 2.0 / (n + 1)
    out, last = [], vals[0]
    out.append(last)
    for v in vals[1:]:
        last = v * k + last * (1 - k)
        out.append(last)
    return out

def compute_macd(closes, fast=12, slow=26, sig=9):
    """returns lists aligned to closes (None where undefined)"""
    n = len(closes)
    if n < slow + sig:
        return [None] * n, [None] * n, [None] * n
    ef, es = ema_series(closes, fast), ema_series(closes, slow)
    macd_line = [f - s for f, s in zip(ef, es)]
    valid = macd_line[slow - 1:]
    sig_valid = ema_series(valid, sig)
    ml = [None] * (slow - 1) + valid
    sl = [None] * (slow + sig - 2) + sig_valid
    hist = [None if (m is None or s is None) else m - s for m, s in zip(ml, sl)]
    return ml, sl, hist

def compute_rsi(closes, period=14):
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    gains, losses = [], []
    for i in range(1, n):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0)); losses.append(max(-d, 0.0))
    ag, al = sum(gains[:period]) / period, sum(losses[:period]) / period
    out[period] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(period + 1, n):
        ag = (ag * (period - 1) + gains[i - 1]) / period
        al = (al * (period - 1) + losses[i - 1]) / period
        out[i] = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    return out

def macd_signal(ml, sl, hist):
    last_h = [h for h in hist if h is not None]
    if not last_h:
        return 0, "داده کافی نیست"
    h = last_h[-1]
    prev = last_h[-2] if len(last_h) > 1 else 0
    score = 0; why = []
    if h > 0:
        score += 2; why.append("هیستوگرام مثبت (مومنتوم صعودی)")
    else:
        score -= 2; why.append("هیستوگرام منفی (مومنتوم نزولی)")
    if prev is not None and prev < 0 and h > 0:
        score += 2; why.append("تقاطع صعودی تازه")
    if prev is not None and prev > 0 and h < 0:
        score -= 2; why.append("تقاطع نزولی تازه")
    if len(last_h) >= 4 and h > last_h[-4]:
        score += 1; why.append("تمایل صعودی هیستوگرام")
    elif len(last_h) >= 4 and h < last_h[-4]:
        score -= 1; why.append("تمایل نزولی هیستوگرام")
    return max(-5, min(5, score)), "؛ ".join(why) if why else "بدون سیگنال واضح"

def rsi_signal(rsi_vals):
    last = [r for r in rsi_vals if r is not None]
    if not last:
        return 0, "داده کافی نیست", None
    r = last[-1]
    if r < 30:
        return 2, f"RSI = {r:.0f} → اشباع فروش (احتمال برگشت صعودی)", r
    if r > 70:
        return -2, f"RSI = {r:.0f} → اشباع خرید (احتمال اصلاح نزولی)", r
    if r > 55:
        return 1, f"RSI = {r:.0f} → مومنتوم صعودی", r
    if r < 45:
        return -1, f"RSI = {r:.0f} → مومنتوم نزولی", r
    return 0, f"RSI = {r:.0f} → خنثی", r

# ------------------------------------------------- engine 1: Gann / angles
def gann_engine(rows, price):
    """Gann angles from the significant swing low of last ~4 months.
    1x1 = 45°. Compare slope of the recent trend with Gann fan angles."""
    n = len(rows)
    closes = [c for _, c in rows]
    if n < 30:
        return {"score": 0, "verdict": "داده کافی نیست", "details": [], "slope_deg": None, "swing": None}
    look = rows[-100:]
    lo_i = min(range(len(look)), key=lambda i: look[i][1])
    swing_date, swing_price = look[lo_i]
    # slope in price-per-day from swing low to now, measured in "points per day",
    # normalised: gann 1x1 = 1 unit of price per 1 day, unit = price * 0.001 (10 pips)
    days = max((rows[-1][0] - swing_date).days, 1)
    rise = closes[-1] - swing_price
    unit = max(abs(swing_price) * 0.0008, 1e-6)  # ~8 pips for FX
    slope_units_per_day = (rise / unit) / days
    slope_deg = math.degrees(math.atan(slope_units_per_day))
    recent = closes[-20:]
    chg20 = (recent[-1] / recent[0] - 1) * 100
    score, details = 0, []
    # position of price relative to key gann fractions of the range
    hi = max(c for _, c in look); lo = swing_price
    rng = max(hi - lo, 1e-9)
    pos = (closes[-1] - lo) / rng  # 0..1 within range
    if pos > 0.618:
        score += 2; details.append("قیمت بالای سطح ۶۱٫۸٪ محدوده (ناحیه قدرت گن)")
    elif pos < 0.382:
        score -= 2; details.append("قیمت زیر سطح ۳۸٫۲٪ محدوده (ناحیه ضعف گن)")
    else:
        details.append("قیمت در ناحیه میانی محدوده گن")
    if slope_deg >= 75:
        score += 2; details.append("شیب بالای ۷۵° → قوی‌تر از زاویه 1x1 گن (روند تند صعودی)")
    elif slope_deg >= 45:
        score += 1; details.append("شیب نزدیک زاویه 1x1 (۴۵°) → روند صعودی سالم")
    elif slope_deg <= -75:
        score -= 2; details.append("شیب زیر −۷۵° → سقوط تندتر از 1x1 معکوس")
    elif slope_deg <= -45:
        score -= 1; details.append("شیب نزدیک 1x1 معکوس → روند نزولی")
    else:
        details.append("شیب ملایم‌تر از 1x1 → بازار در تعادل")
    if chg20 > 0:
        score += 1; details.append(f"بازده ۲۰ روز اخیر: {chg20:+.1f}% (صعودی)")
    else:
        score -= 1; details.append(f"بازده ۲۰ روز اخیر: {chg20:+.1f}% (نزولی)")
    # gann square-of-9 resistance/support near current price
    sq = math.sqrt(max(closes[-1], 1e-9))
    lvl_up = (sq + 0.25) ** 2
    lvl_dn = (sq - 0.25) ** 2
    details.append(f"مقاومت مربع ۹ گن: {lvl_up:.4f} | حمایت: {lvl_dn:.4f}")
    verdict = "صعودی" if score >= 2 else ("نزولی" if score <= -2 else "خنثی")
    return {"score": max(-5, min(5, score)), "verdict": verdict,
            "details": details, "slope_deg": round(slope_deg, 1),
            "swing": {"date": str(swing_date), "price": swing_price}}

# --------------------------------------- engine 2: astrology / planetary
ZODIAC = ["حمل", "ثور", "جوزا", "سرطان", "اسد", "سنبله",
          "میزان", "عقرب", "قوس", "جدی", "دلو", "حوت"]
# planetary "rulerships" for major currencies (traditional astrology)
RULERS = {"USD": "حوت", "EUR": "حوت", "GBP": "حمل", "JPY": "میزان",
          "CHF": "جوزا", "AUD": "عقرب", "CAD": "سرطان", "NZD": "قوس",
          "XAU": "اسد", "XAG": "قمر"}

def sun_sign(date):
    # approximate ecliptic longitude of the Sun (degrees)
    d = (date - dt.date(2000, 1, 1)).days
    L = (280.460 + 0.9856474 * d) % 360
    g = math.radians((357.528 + 0.9856003 * d) % 360)
    lam = L + 1.915 * math.sin(g) + 0.020 * math.sin(2 * g)
    return lam

def moon_long(date):
    d = (date - dt.date(2000, 1, 1)).days
    L = (218.316 + 13.176396 * d) % 360
    M = math.radians((134.963 + 13.064993 * d) % 360)
    F = math.radians((93.272 + 13.229350 * d) % 360)
    lam = L + 6.289 * math.sin(M) - 1.274 * math.sin(2 * L - M) + 0.658 * math.sin(2 * F)
    return lam

def planet_longs(date):
    """rough mean longitudes + simple corrections (geocentric approximations)"""
    d = (date - dt.date(2000, 1, 1)).days
    out = {}
    for name, T, corr in (("عطارد", 87.969, 0), ("زهره", 224.701, 0),
                          ("مریخ", 686.980, 0), ("مشتری", 4332.589, 0),
                          ("زحل", 10759.22, 0)):
        # heliocentric mean longitude, then a crude geocentric shift by synodic phase
        L = (252.25 + 360 * d / T) % 360 if name != "عطارد" else (252.25 + 360 * d / T) % 360
        syn = {"عطارد": 115.88, "زهره": 583.92, "مریخ": 779.94,
               "مشتری": 398.88, "زحل": 378.09}[name]
        phase = math.radians((360 * d / syn) % 360)
        geo = (L + 20 * math.sin(phase)) % 360
        out[name] = geo
    return out

def sign_of(lon):
    return ZODIAC[int(lon // 30) % 12]

def astrology_engine(symbol, date):
    base, quote = symbol[:3], symbol[3:]
    sun_l, moon_l = sun_sign(date), moon_long(date)
    pl = planet_longs(date)
    sun_sign_name, moon_sign_name = sign_of(sun_l), sign_of(moon_l)
    score, details = 0, []
    # Moon phase angle: 0=new, 180=full — market lore: waxing favours base currency
    phase = (moon_l - sun_l) % 360
    waxing = phase < 180
    score += 2 if waxing else -2
    details.append(f"قمر {'در نیمه روشن (افزایشی)' if waxing else 'در نیمه تاریک (کاهشی)'} — "
                   f"زاویه فاز: {phase:.0f}°")
    details.append(f"خورشید در برج {sun_sign_name} | ماه در برج {moon_sign_name}")
    # planetary hour-ish: benefic vs malefic longitudes vs currency signs
    benefics = {"زهره", "مشتری"}; malefics = {"مریخ", "زحل", "عطارد"}
    for planet, lon in pl.items():
        psign = sign_of(lon)
        if psign == RULERS.get(base):
            w = 2 if planet in benefics else 1
            score += w
            details.append(f"{planet} در برج حاکمِ {base} ({psign}) → تقویت {base}")
        if psign == RULERS.get(quote):
            w = 2 if planet in benefics else 1
            score -= w
            details.append(f"{planet} در برج حاکمِ {quote} ({psign}) → تقویت {quote}")
        if planet == "زحل" and (sun_l - lon) % 360 < 12 or planet == "زحل" and (lon - sun_l) % 360 < 12:
            score -= 1
            details.append("هم‌قراری زحل با خورشید → فشار محدودکننده")
    verdict = "صعودی" if score >= 2 else ("نزولی" if score <= -2 else "خنثی")
    return {"score": max(-5, min(5, score)), "verdict": verdict, "details": details,
            "sun_sign": sun_sign_name, "moon_sign": moon_sign_name,
            "phase_deg": round(phase)}

# ---------------------------------------- engine 3: news / sentiment
POS = ["surge", "rally", "gain", "rise", "rose", "jump", "bullish", "strong", "boost",
       "upbeat", "higher", "recover", "optimis", "win", "growth", "up", "soar", "climb"]
NEG = ["fall", "drop", "plunge", "bearish", "weak", "slump", "decline", "lower",
       "loss", "fear", "risk-off", "crisis", "sell-off", "selloff", "tumble", "down",
       "recession", "war", "sanction", "tariff", "panic", "slide", "downturn"]

def news_engine(symbol, items):
    if not items:
        return {"score": 0, "verdict": "خنثی", "details": ["خبر تازه‌ای یافت نشد"],
                "pos": 0, "neg": 0, "total": 0}
    pos = neg = 0
    for it in items:
        t = it["title"].lower()
        p = sum(1 for w in POS if w in t)
        n = sum(1 for w in NEG if w in t)
        if p > n:
            pos += 1
        elif n > p:
            neg += 1
    total = len(items)
    raw = (pos - neg) / max(total, 1)  # -1..1
    score = round(raw * 5)
    det = [f"{total} خبر اخیر: {pos} خبر با لحن مثبت، {neg} خبر با لحن منفی",
           f"شاخص احساسات: {raw:+.2f} (بین −۱ تا +۱)"]
    if pos > neg:
        det.append("غلبه اخبار مثبت → فشار خرید روی نماد")
    elif neg > pos:
        det.append("غلبه اخبار منفی → فشار فروش روی نماد")
    else:
        det.append("تعادل لحن اخبار → اثر خنثی")
    verdict = "صعودی" if score >= 2 else ("نزولی" if score <= -2 else "خنثی")
    return {"score": max(-5, min(5, score)), "verdict": verdict, "details": det,
            "pos": pos, "neg": neg, "total": total}

# ---------------------------------------------------------------- routes
@app.get("/api/symbols")
def api_symbols():
    return jsonify(SYMBOLS)

@app.get("/api/analyze/<symbol>")
def api_analyze(symbol):
    symbol = symbol.upper()
    if symbol not in SYMBOLS:
        return jsonify({"error": "symbol not found"}), 404
    try:
        rows, price, meta = yahoo(symbol)
    except Exception as e:
        return jsonify({"error": f"خطا در دریافت قیمت: {e}"}), 502
    closes = [c for _, c in rows]
    dates = [str(d) for d, _ in rows]
    today = dt.date.today()
    ml, sl, hist = compute_macd(closes)
    rsi_vals = compute_rsi(closes)
    m_score, m_why = macd_signal(ml, sl, hist)
    r_score, r_why, r_now = rsi_signal(rsi_vals)
    gann = gann_engine(rows, price)
    astro = astrology_engine(symbol, today)
    items = news_items(symbol)
    news = news_engine(symbol, items)
    engines = {
        "gann": {**gann, "name": "زاویه‌های گن", "icon": "📐"},
        "astro": {**astro, "name": "آسترولوژی", "icon": "🪐"},
        "news": {**news, "name": "احساسات اخبار", "icon": "📰"},
        "macd": {"score": m_score, "verdict": "صعودی" if m_score > 0 else ("نزولی" if m_score < 0 else "خنثی"),
                 "details": [m_why], "name": "MACD", "icon": "📊"},
        "rsi": {"score": r_score, "verdict": "صعودی" if r_score > 0 else ("نزولی" if r_score < 0 else "خنثی"),
                "details": [r_why], "name": "RSI", "icon": "📈", "value": r_now},
    }
    weights = {"gann": 0.30, "astro": 0.15, "news": 0.25, "macd": 0.15, "rsi": 0.15}
    total = sum(weights[k] * engines[k]["score"] for k in weights)
    prob_up = round(max(5, min(95, 50 + total * 9)))
    if total > 0.5:
        final, color = "صعودی 📈", "up"
    elif total < -0.5:
        final, color = "نزولی 📉", "down"
    else:
        final, color = "خنثی ➖", "flat"
    # series for charts (last 120 points)
    N = 120
    sl_price = None
    series = {
        "dates": dates[-N:],
        "price": closes[-N:],
        "macd": ml[-N:],
        "signal": sl[-N:],
        "hist": hist[-N:],
        "rsi": rsi_vals[-N:],
    }
    return jsonify({
        "symbol": symbol, "name": SYMBOLS[symbol], "price": price,
        "change_pct": meta.get("regularMarketChangePercent"),
        "fifty2": {"high": meta.get("fiftyTwoWeekHigh"), "low": meta.get("fiftyTwoWeekLow")},
        "probability_up": prob_up, "final": final, "color": color,
        "engines": engines, "news_items": items, "series": series,
    })

@app.get("/fonts/<path:fname>")
def fonts(fname):
    return send_from_directory("fonts", fname)

@app.get("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json")

@app.get("/sw.js")
def service_worker():
    response = app.make_response(send_from_directory("static", "sw.js"))
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Content-Type"] = "application/javascript; charset=utf-8"
    return response

@app.get("/")
def index():
    return send_from_directory("static", "index.html")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, threaded=True)
