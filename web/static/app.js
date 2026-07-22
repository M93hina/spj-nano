/* B1F フリースペース 混雑状況ダッシュボード フロントエンドロジック
 *
 * /api/dashboard をポーリングして描画する。利用者向け表示を優先し、
 * 閾値の算出根拠やスパイク除去数などの内部情報は「データについて」
 * (折りたたみ)にまとめる方針。
 */

const REFRESH_MS = 5 * 60 * 1000;

const STATUS_COLORS = {
  1: "#0ca30c", // 空いています
  2: "#fab219", // やや利用あり
  3: "#ec835a", // 混雑
  4: "#d03b3b", // 非常に混雑
};

// spj_nano/levels.py の LEVEL_META と対応(予測値のレベル表示をクライアント側で算出するため)
const LEVEL_META = [
  ["空いています", "🟢"],
  ["やや利用あり", "🟡"],
  ["混雑", "🟠"],
  ["非常に混雑", "🔴"],
];

const root = document.querySelector(".viz-root");
const $ = (id) => document.getElementById(id);

function cssVar(name) {
  return getComputedStyle(root).getPropertyValue(name).trim();
}

let chart = null;
// チャートの現在の表示範囲(時間)。トグル操作やポーリング再描画をまたいで保持する。
let selectedRangeHours = 6;
// チャートの全データが張る範囲(分オフセット)。トグル押下時にmin/maxを付け替えるため保持する。
let chartBounds = { minOffset: -6 * 60, maxOffset: 0 };
// 直近の描画で使った「最新実測時刻」。目盛/ツールチップのコールバックが分オフセット
// →時刻の変換に使うため、renderChart()実行のたびに更新するモジュール変数として持つ。
let latestTimeRef = null;

// "YYYY-MM-DD HH:MM" 形式の文字列をローカル時刻のDateとして解釈する。
// ブラウザ依存のDateパース(タイムゾーン扱いの差異)を避けるため手動で分解する。
function parseTimestamp(s) {
  const [datePart, timePart] = s.split(" ");
  const [y, mo, d] = datePart.split("-").map(Number);
  const [h, mi] = timePart.split(":").map(Number);
  return new Date(y, mo - 1, d, h, mi);
}

// 分オフセット(latestTime基準)を "HH:MM"、日付が変わる場合は "M/D HH:MM" に整形する。
function formatOffsetClock(minutesOffset, latestTime) {
  const d = new Date(latestTime.getTime() + minutesOffset * 60000);
  const sameDay =
    d.getFullYear() === latestTime.getFullYear() &&
    d.getMonth() === latestTime.getMonth() &&
    d.getDate() === latestTime.getDate();
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  return sameDay ? `${hh}:${mm}` : `${d.getMonth() + 1}/${d.getDate()} ${hh}:${mm}`;
}

// levels.py の level() と境界挙動を揃える(閾値ちょうどは上位レベル)
function levelFromCo2(co2, thresholds) {
  if (co2 < thresholds.t1) return 1;
  if (co2 < thresholds.t2) return 2;
  if (co2 < thresholds.t3) return 3;
  return 4;
}

function hexToRgb(hex) {
  const h = hex.replace("#", "");
  return [
    parseInt(h.substring(0, 2), 16),
    parseInt(h.substring(2, 4), 16),
    parseInt(h.substring(4, 6), 16),
  ];
}

function lerpColorHex(hexA, hexB, t) {
  const a = hexToRgb(hexA);
  const b = hexToRgb(hexB);
  const c = a.map((v, i) => Math.round(v + (b[i] - v) * t));
  return `#${c.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
}

function relativeLuminance([r, g, b]) {
  const srgb = [r, g, b].map((v) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  });
  return 0.2126 * srgb[0] + 0.7152 * srgb[1] + 0.0722 * srgb[2];
}

function renderEmpty() {
  $("empty-state").classList.remove("hidden");
  $("dashboard-body").classList.add("hidden");
}

function renderDashboard(data) {
  $("empty-state").classList.add("hidden");
  $("dashboard-body").classList.remove("hidden");

  renderHero(data);
  renderStaleness(data.staleness);
  renderAbout(data);

  // データ更新が止まっている(stale)場合、最終データ時点起点の「15〜180分後予測」は
  // 現在時刻に対する予測として意味を持たないため表示しない。
  renderChart(data.series_24h, data.thresholds, data.staleness.is_stale ? null : data.forecast);
  renderHeatmap(data.heatmap, data.thresholds);

  $("fetched-at").textContent = `最終取得: ${new Date().toLocaleString("ja-JP")}`;
}

function renderHero(data) {
  const cur = data.current;

  const badge = $("hero-level");
  badge.textContent = `${cur.icon} ${cur.level_label}`;
  badge.style.background = STATUS_COLORS[cur.level] || cssVar("--text-muted");

  $("hero-co2-value").textContent = cur.co2.toFixed(0);
  $("hero-updated").textContent = `最終更新 ${cur.last_update}`;

  // 予測があり、かつデータが新鮮な場合のみ「1時間後の見込み」を表示する
  const chip = $("hero-forecast");
  const forecast = data.forecast;
  const oneHour = Array.isArray(forecast)
    ? forecast.find((f) => f.horizon_minutes === 60)
    : null;
  if (oneHour && !data.staleness.is_stale) {
    const lvl = levelFromCo2(oneHour.predicted_co2, data.thresholds);
    const [label, icon] = LEVEL_META[lvl - 1];
    const mini = $("hero-forecast-badge");
    mini.textContent = `${icon} ${label}`;
    mini.style.background = STATUS_COLORS[lvl];
    chip.classList.remove("hidden");
  } else {
    chip.classList.add("hidden");
  }
}

function renderStaleness(staleness) {
  const banner = $("warning-banner");
  if (!staleness.is_stale) {
    banner.classList.remove("show");
    return;
  }
  const ageHours = staleness.age_hours;
  const ageStr =
    ageHours >= 24 ? `約${(ageHours / 24).toFixed(1)}日` : `約${ageHours.toFixed(1)}時間`;
  $("warning-text").textContent =
    `データの更新が${ageStr}前（${staleness.last_update}）から止まっています。` +
    "以下はその時点までの情報であり、現在の状況ではない可能性があります。";
  banner.classList.add("show");
}

function renderAbout(data) {
  const th = data.thresholds;
  $("about-levels").textContent =
    `🟢 空いています（〜${th.t1.toFixed(0)}ppm） / ` +
    `🟡 やや利用あり（〜${th.t2.toFixed(0)}ppm） / ` +
    `🟠 混雑（〜${th.t3.toFixed(0)}ppm） / ` +
    `🔴 非常に混雑（${th.t3.toFixed(0)}ppm〜）`;
  $("about-basis").textContent =
    `閾値は平日9〜18時のCO2分布から自動算出しています` +
    `（サンプル数 ${th.weekday_daytime_samples}、中央値 ${
      th.median !== null ? th.median.toFixed(0) + "ppm" : "–"
    }）。`;
  $("about-spikes").textContent =
    `センサーの瞬間的な異常値（スパイク）${data.current.spikes_removed} 点を除去した値を表示しています。`;
  $("about-forecast").textContent = Array.isArray(data.forecast)
    ? "予測はLightGBMモデルによる15〜180分後の推定値です。"
    : "予測モデルは現在利用できないため、実測のみ表示しています。";
}

// トグル操作(6時間/24時間)に応じてx軸のmin/maxだけを付け替える。
// データの再取得・再スライスは行わず、Chart.jsの表示範囲を動かすだけなので軽量。
function applyChartRange(hours) {
  selectedRangeHours = hours;
  if (!chart) return;
  chart.options.scales.x.min = -hours * 60;
  chart.options.scales.x.max = Math.max(chartBounds.maxOffset, 0);
  chart.update();
}

function initRangeToggle() {
  const buttons = document.querySelectorAll("#range-toggle button");
  buttons.forEach((btn) => {
    btn.addEventListener("click", () => {
      buttons.forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      applyChartRange(Number(btn.dataset.hours));
    });
  });
}

function renderChart(series, thresholds, forecast) {
  const ctx = $("chart-24h").getContext("2d");
  const n = series.timestamps.length;

  const seriesColor = cssVar("--series-co2");
  const muted = cssVar("--text-muted");
  const grid = cssVar("--gridline");
  const textSecondary = cssVar("--text-secondary");

  // x軸は「最新実測時刻を0とした分オフセット」の線形軸。実測は負側、予測は正側(+15〜+180分)。
  const actualTimes = series.timestamps.map(parseTimestamp);
  latestTimeRef = actualTimes[n - 1];
  const toOffset = (d) => (d - latestTimeRef) / 60000;
  const earliestOffset = toOffset(actualTimes[0]);

  // 予測(forecast)があれば実測の右側(未来方向)にデータ点を追加する。
  const hasForecast = Array.isArray(forecast) && forecast.length > 0;
  const forecastMaxOffset = hasForecast
    ? Math.max(...forecast.map((f) => f.horizon_minutes))
    : 0;

  // チャート全体が張る範囲(トグルのmin/max計算に使う)を更新
  chartBounds = { minOffset: earliestOffset, maxOffset: forecastMaxOffset };

  $("chart-note").textContent = hasForecast
    ? "実線: 実測のCO2濃度 / グレーの点線: 混雑レベルの目安 / 右側の破線: 3時間後までの予測"
    : "実線: 実測のCO2濃度 / グレーの点線: 混雑レベルの目安";

  const actualPoints = series.co2.map((v, i) => ({ x: toOffset(actualTimes[i]), y: v }));

  const datasets = [
    {
      label: "CO2（実測）",
      data: actualPoints,
      borderColor: seriesColor,
      backgroundColor: seriesColor,
      borderWidth: 2,
      pointRadius: 0,
      tension: 0.15,
      order: 1,
      _role: "actual",
    },
    ...[thresholds.t1, thresholds.t2, thresholds.t3].map((t, i) => ({
      label: `レベル境界${i + 1} (${t.toFixed(0)}ppm)`,
      // 表示範囲全体(6時間/24時間どちらに切り替えても)に届くよう、
      // 実測開始点〜予測終端の2点だけを結ぶ水平線として引く。
      data: [
        { x: earliestOffset, y: t },
        { x: Math.max(forecastMaxOffset, 0), y: t },
      ],
      borderColor: muted,
      borderWidth: 1,
      borderDash: [4, 3],
      pointRadius: 0,
      order: 2,
      _role: "threshold",
    })),
  ];

  if (hasForecast) {
    // 実測最終点(x=0)を先頭に入れて実線と破線をつなげる。
    const forecastPoints = [{ x: 0, y: series.co2[n - 1] }].concat(
      forecast.map((f) => ({ x: f.horizon_minutes, y: f.predicted_co2 }))
    );
    datasets.push({
      label: "予測",
      data: forecastPoints,
      borderColor: seriesColor,
      backgroundColor: seriesColor,
      borderWidth: 2,
      borderDash: [6, 4],
      pointRadius: (ctx) => (ctx.dataIndex >= 1 ? 3 : 0),
      spanGaps: true,
      tension: 0,
      order: 1,
      _role: "forecast",
    });
  }

  if (chart) {
    chart.data.datasets = datasets;
    applyChartRange(selectedRangeHours);
    return;
  }

  chart = new Chart(ctx, {
    type: "line",
    data: { datasets },
    options: {
      responsive: true,
      // ラッパー(.chart-wrap)の高さに従わせる。アスペクト比固定だと
      // モバイル幅(360px前後)でチャートが極端に低く潰れるため。
      maintainAspectRatio: false,
      // 線形x軸・データセット間で点数/間隔が異なる(実測は5分間隔で多数、閾値線は2点、
      // 予測は疎)ため、配列インデックスで揃える"index"モードではなく、
      // x軸上の近傍点を探す"nearest"モードを使う。
      interaction: { mode: "nearest", intersect: false, axis: "x" },
      plugins: {
        // 系列は実測CO2・予測(あれば)のみ(閾値線はキャプションで説明)なので凡例は出さない。
        // 凡例に閾値3本が並ぶとモバイルで数行を占有してしまう。
        legend: { display: false },
        tooltip: {
          // 閾値データセットはdatasetIndexではなくカスタムプロパティ(_role)で除外する。
          filter: (item) => item.dataset._role !== "threshold",
          callbacks: {
            title: (items) =>
              items.length ? formatOffsetClock(items[0].parsed.x, latestTimeRef) : "",
            label: (item) => `${item.dataset.label}: ${Math.round(item.parsed.y)} ppm`,
          },
        },
      },
      scales: {
        x: {
          type: "linear",
          min: -selectedRangeHours * 60,
          max: Math.max(chartBounds.maxOffset, 0),
          ticks: {
            color: muted,
            // モバイル幅では目盛が重ならないようさらに間引く
            maxTicksLimit: window.innerWidth < 480 ? 5 : 8,
            font: { size: 10 },
            callback: (value) => formatOffsetClock(value, latestTimeRef),
          },
          grid: { color: grid },
        },
        y: {
          title: { display: true, text: "CO2 [ppm]", color: textSecondary },
          ticks: { color: muted },
          grid: { color: grid },
        },
      },
    },
  });
  applyChartRange(selectedRangeHours);
}

function renderHeatmap(heatmap, thresholds) {
  const table = $("heatmap-table");
  table.innerHTML = "";

  const lowHex = cssVar("--seq-100");
  const highHex = cssVar("--seq-700");
  const lo = thresholds.t1;
  const hi = thresholds.t3;

  const thead = document.createElement("tr");
  const corner = document.createElement("th");
  corner.className = "corner";
  thead.appendChild(corner);
  heatmap.hours.forEach((h) => {
    const th = document.createElement("th");
    th.textContent = h;
    thead.appendChild(th);
  });
  table.appendChild(thead);

  heatmap.weekdays.forEach((wd, ri) => {
    const tr = document.createElement("tr");
    const wdCell = document.createElement("td");
    wdCell.textContent = wd;
    wdCell.className = "wd-label";
    tr.appendChild(wdCell);

    heatmap.values[ri].forEach((v) => {
      const td = document.createElement("td");
      td.className = "cell";
      if (v === null || v === undefined) {
        td.classList.add("empty");
        td.textContent = "";
      } else {
        const t = Math.max(0, Math.min(1, (v - lo) / (hi - lo || 1)));
        const bg = lerpColorHex(lowHex, highHex, t);
        td.style.background = bg;
        const lum = relativeLuminance(hexToRgb(bg));
        td.style.color = lum > 0.45 ? "#0b0b0b" : "#ffffff";
        td.textContent = Math.round(v);
      }
      tr.appendChild(td);
    });
    table.appendChild(tr);
  });
}

async function fetchAndRender() {
  try {
    const res = await fetch("/api/dashboard");
    const data = await res.json();
    if (data.empty) {
      renderEmpty();
    } else {
      renderDashboard(data);
    }
  } catch (e) {
    console.error("ダッシュボード取得に失敗しました", e);
  }
}

initRangeToggle();
fetchAndRender();
setInterval(fetchAndRender, REFRESH_MS);
