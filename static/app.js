/* Forex app frontend */
const $ = (id) => document.getElementById(id);
let charts = {};
let tvLoaded = false;

const SYMBOL_TV = {
  EURUSD: "FX:EURUSD", GBPUSD: "FX:GBPUSD", USDJPY: "FX:USDJPY", USDCHF: "FX:USDCHF",
  AUDUSD: "FX:AUDUSD", USDCAD: "FX:USDCAD", NZDUSD: "FX:NZDUSD", EURGBP: "FX:EURGBP",
  EURJPY: "FX:EURJPY", GBPJPY: "FX:GBPJPY", XAUUSD: "OANDA:XAUUSD", XAGUSD: "OANDA:XAGUSD"
};

const faNum = (n, d = 2) => Number(n).toLocaleString("fa-IR", { maximumFractionDigits: d, minimumFractionDigits: d });

async function loadSymbols() {
  const r = await fetch("/api/symbols");
  const map = await r.json();
  const sel = $("symbol");
  for (const [code, name] of Object.entries(map)) {
    const o = document.createElement("option");
    o.value = code; o.textContent = name;
    sel.appendChild(o);
  }
  sel.value = "EURUSD";
}

function badgeClass(v) { return v === "صعودی" ? "up" : v === "نزولی" ? "down" : "flat"; }

function scoreBar(score, max = 5) {
  const pct = 50 + (score / max) * 50;
  const color = score > 0 ? "#26c281" : score < 0 ? "#f0544f" : "#f0b429";
  return `<div class="score-line"><div class="score-fill" style="width:${pct}%;background:${color}"></div><div class="score-zero"></div></div>`;
}

function renderEngine(key, e) {
  const li = (e.details || []).map(d => `<li>${d}</li>`).join("");
  return `<div class="engine">
    <div class="engine-head">
      <span class="engine-title">${e.icon} ${e.name}</span>
      <span class="badge ${badgeClass(e.verdict)}">${e.verdict}</span>
    </div>
    ${scoreBar(e.score)}
    <ul>${li}</ul>
  </div>`;
}

function destroyCharts() {
  Object.values(charts).forEach(c => c && c.destroy());
  charts = {};
}

function baseOpts(legend = false) {
  return {
    responsive: true, maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { display: legend, labels: { color: "#8b93a7", font: { family: "Vazirmatn" } } },
      tooltip: { bodyFont: { family: "Vazirmatn" }, titleFont: { family: "Vazirmatn" } }
    },
    scales: {
      x: { ticks: { color: "#8b93a7", maxTicksLimit: 7, font: { size: 10 } }, grid: { display: false } },
      y: { ticks: { color: "#8b93a7", font: { size: 10 } }, grid: { color: "rgba(255,255,255,.06)" } }
    }
  };
}

function mkChart(id, cfg) {
  charts[id] = new Chart($(id).getContext("2d"), cfg);
}

function loadTV(tvSymbol) {
  const box = $("tvwidget");
  box.innerHTML = "";
  const mount = () => {
    new TradingView.widget({
      container_id: "tvwidget",
      symbol: tvSymbol,
      interval: "240",
      timezone: "Asia/Tehran",
      theme: "dark",
      style: "1",
      locale: "fa",
      autosize: true,
      hide_side_toolbar: false,
      allow_symbol_change: true,
      withdateranges: true,
      details: false
    });
  };
  if (window.TradingView) { mount(); return; }
  if (!tvLoaded) {
    tvLoaded = true;
    const s = document.createElement("script");
    s.src = "https://s3.tradingview.com/tv.js";
    s.onload = mount;
    s.onerror = () => { box.innerHTML = '<p class="tv-err">بارگذاری TradingView ناموفق بود — اتصال اینترنت را بررسی کنید.</p>'; };
    document.head.appendChild(s);
  } else {
    // script still loading; wait for it
    const t = setInterval(() => {
      if (window.TradingView) { clearInterval(t); mount(); }
    }, 200);
    setTimeout(() => clearInterval(t), 15000);
  }
}

function renderSeries(s) {
  const labels = s.dates.map(d => d.slice(5));

  mkChart("cPrice", {
    type: "line",
    data: { labels, datasets: [{
      label: "قیمت", data: s.price, borderColor: "#5b8def",
      backgroundColor: "rgba(91,141,239,.1)", fill: true,
      pointRadius: 0, borderWidth: 2, tension: .25
    }]},
    options: baseOpts(false)
  });

  mkChart("cMacd", {
    type: "bar",
    data: { labels, datasets: [
      { type: "bar", label: "هیستوگرام", data: s.hist,
        backgroundColor: s.hist.map(h => (h == null || h < 0) ? "rgba(240,84,79,.45)" : "rgba(38,194,129,.45)"), borderWidth: 0 },
      { type: "line", label: "MACD", data: s.macd, borderColor: "#5b8def", pointRadius: 0, borderWidth: 2, tension: .3 },
      { type: "line", label: "Signal", data: s.signal, borderColor: "#f0b429", pointRadius: 0, borderWidth: 2, tension: .3 }
    ]},
    options: baseOpts(true)
  });

  const rsiOpts = baseOpts(false);
  rsiOpts.scales.y.min = 0; rsiOpts.scales.y.max = 100;
  mkChart("cRsi", {
    type: "line",
    data: { labels, datasets: [
      { label: "RSI", data: s.rsi, borderColor: "#b57bff", pointRadius: 0, borderWidth: 2, tension: .3, fill: false },
      { label: "اشباع خرید (۷۰)", data: labels.map(() => 70), borderColor: "rgba(240,84,79,.5)", borderDash: [6, 6], pointRadius: 0, borderWidth: 1 },
      { label: "اشباع فروش (۳۰)", data: labels.map(() => 30), borderColor: "rgba(38,194,129,.5)", borderDash: [6, 6], pointRadius: 0, borderWidth: 1 }
    ]},
    options: rsiOpts
  });
}

async function analyze() {
  const sym = $("symbol").value;
  const st = $("status");
  st.classList.remove("hidden", "err");
  st.textContent = "در حال دریافت داده و اجرای تحلیل‌ها…";
  ["summary", "engines", "charts", "news"].forEach(id => $(id).classList.add("hidden"));
  try {
    const r = await fetch(`/api/analyze/${sym}`);
    const j = await r.json();
    if (!r.ok) throw new Error(j.error || "خطا");
    st.classList.add("hidden");
    render(j);
    loadTV(SYMBOL_TV[sym] || "FX:EURUSD");
  } catch (e) {
    st.classList.add("err");
    st.textContent = "خطا در دریافت تحلیل: " + e.message;
  }
}

function render(j) {
  $("finalVerdict").textContent = j.final;
  $("finalVerdict").className = "v-main " + j.color;
  $("probFill").style.width = (100 - j.probability_up) + "%";
  $("probUp").textContent = `احتمال رشد: ${faNum(j.probability_up, 0)}٪`;
  $("probDown").textContent = `احتمال ریزش: ${faNum(100 - j.probability_up, 0)}٪`;
  $("priceNow").textContent = faNum(j.price, 4);
  const chg = j.change_pct;
  $("chgNow").textContent = chg == null ? "—" : `${chg >= 0 ? "▲" : "▼"} ${faNum(Math.abs(chg), 2)}٪ امروز`;
  $("chgNow").className = "m-sub " + (chg >= 0 ? "up" : "down");
  $("hi52").textContent = faNum(j.fifty2.high, 4);
  $("lo52").textContent = faNum(j.fifty2.low, 4);
  $("summary").classList.remove("hidden");

  $("engines").innerHTML = Object.entries(j.engines).map(([k, e]) => renderEngine(k, e)).join("");
  $("engines").classList.remove("hidden");

  destroyCharts();
  renderSeries(j.series);
  $("charts").classList.remove("hidden");

  const sources = [...new Set(j.news_items.map(n => n.source))];
  $("newsSrc").textContent = sources.length ? "منابع: " + sources.join(" · ") : "";
  $("newsList").innerHTML = j.news_items.map(n =>
    `<li><a class="n-title" href="${n.link || "#"}" target="_blank" rel="noopener noreferrer">${n.title}</a>
     <div class="n-meta">${n.source || ""} ${n.date ? "· " + n.date : ""}</div></li>`
  ).join("") || "<li>خبری یافت نشد.</li>";
  $("news").classList.remove("hidden");
}

$("symbol").addEventListener("change", analyze);
loadSymbols().then(analyze);
