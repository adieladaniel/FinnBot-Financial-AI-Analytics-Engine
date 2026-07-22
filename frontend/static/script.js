let sessionId = null;
let lastQuestion = null;
let isLoading = false;
let apiTimer = null;
let apiStartTime = null;
let latestDatasetInfo = null;


async function uploadDataset() {
  const file = document.getElementById("fileInput").files[0];
  if (!file) {
    alert("Please select a file first.");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);

  const res = await fetch("/upload", {
    method: "POST",
    body: formData
  });

  const data = await res.json();
  sessionId = data.session_id;
  window.sessionId = data.session_id;

  document.getElementById("datasetSummary").innerHTML = `
    <p><strong>Rows:</strong> ${data.rows}</p>
    <p><strong>Dimensions:</strong> ${data.dimensions.join(", ")}</p>
    <p><strong>Measures:</strong> ${data.measures.join(", ")}</p>
  `;

  // Update sidebar session indicator
  const info = document.getElementById("sessionInfo");
  if (info) {
    info.innerHTML = `<span class="dot dot--active"></span>${file.name}`;
  }

  // Remove empty state
  const empty = document.querySelector('.empty-state');
  if (empty) empty.remove();

  addBotMessage("Dataset uploaded successfully. Puch le ab .");
  
}

function handleEnter(event) {
  if (event.key === "Enter" && !isLoading) {
    sendMessage();
  }
}

function setLoading(loading) {
  isLoading = loading;
  const sendBtn = document.getElementById("sendBtn");
  const input = document.getElementById("questionInput");

  sendBtn.disabled = loading;
  input.disabled = loading;

  if (loading) {
    sendBtn.innerHTML = `
      <div class="spinner" style="width:13px;height:13px;border-width:2px;flex-shrink:0"></div>
      Running…
    `;
  } else {
    sendBtn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
      Run Query
    `;
  }
}

async function sendMessage(forceQuestion = null) {
  const input = document.getElementById("questionInput");
  const question = forceQuestion || input.value.trim();

  if (!question) return;

  if (!sessionId) {
    alert("Please upload a dataset first.");
    return;
  }

  const empty = document.querySelector('.empty-state');
  if (empty) empty.remove();

  if (!forceQuestion) {
    addUserMessage(question);
    input.value = "";
  }

  lastQuestion = question;
  setLoading(true);

  const loadingId = addLoadingMessage();

  try {
    const res = await fetch("/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        session_id: window.sessionId,
        question: question,
        domain: "fees"
      })
    });

    const data = await res.json();
    removeMessageById(loadingId);
    addBotResponse(data);
  } catch (err) {
    removeMessageById(loadingId);
    addBotMessage("Something went wrong while fetching the response.");
    console.error(err);
  } finally {
    setLoading(false);
  }
}

function addUserMessage(text) {
  const chatBox = document.getElementById("chatBox");
  const div = document.createElement("div");
  div.className = "message user";
  div.textContent = text;
  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function addBotMessage(text) {
  const chatBox = document.getElementById("chatBox");
  const div = document.createElement("div");
  div.className = "message bot";
  div.textContent = text;
  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function addLoadingMessage() {
  const chatBox = document.getElementById("chatBox");
  const div = document.createElement("div");
  const id = `loading-${Date.now()}`;
  div.id = id;
  div.className = "message bot";
  div.innerHTML = `
    <div class="loading">
      <span class="spinner"></span>
      <span>Analyzing your question…</span>
    </div>
  `;
  chatBox.appendChild(div);
  chatBox.scrollTop = chatBox.scrollHeight;
  return id;
}

function removeMessageById(id) {
  const el = document.getElementById(id);
  if (el) el.remove();
}

function getSourceBadge(source) {
  if (source === "rule_based") {
    return `<span class="badge rule">Rule-based</span>`;
  }
  if (source === "gemini_fallback") {
    return `<span class="badge gemini">Gemini fallback</span>`;
  }
  if (source === "rule_based_failed" || source === "low_confidence_fail") {
    return `<span class="badge fail">Low confidence</span>`;
  }
  return `<span class="badge conf">Unknown source</span>`;
}

function renderRetryButton(data) {
  const weak =
    data.source === "rule_based_failed" ||
    data.source === "low_confidence_fail" ||
    (typeof data.confidence === "number" && data.confidence < 0.68);

  if (!weak || !lastQuestion) return "";

  return `
    <div class="retry-wrap">
      <button class="retry-btn" onclick="retryLastQuestion()">↺ Retry query</button>
    </div>
  `;
}

function retryLastQuestion() {
  if (!lastQuestion) return;
  addUserMessage(`Retry: ${lastQuestion}`);
  sendMessage(lastQuestion);
}

function addBotResponse(data) {
  const chatBox = document.getElementById("chatBox");
  const div = document.createElement("div");
  div.className = "message bot";

  const confidenceText =
    typeof data.confidence === "number"
      ? `<span class="badge conf">Confidence: ${data.confidence}</span>`
      : "";

  let html = `<div><strong>${data.answer}</strong></div>`;

  html += `
    <div class="status-row">
      ${getSourceBadge(data.source)}
      ${confidenceText}
    </div>
  `;

  if (data.refined_question && data.refined_question !== data.question) {
    html += `<div class="meta"><strong>Refined:</strong> ${escapeHtml(data.refined_question)}</div>`;
  }

  if (data.plan) {
    html += `<div class="meta"><strong>Plan:</strong> ${escapeHtml(JSON.stringify(data.plan))}</div>`;
  }

  if (data.rows && data.rows.length > 0) {
    const headers = Object.keys(data.rows[0]);
    html += "<table><thead><tr>";
    headers.forEach(h => { html += `<th>${escapeHtml(h)}</th>`; });
    html += "</tr></thead><tbody>";
    data.rows.forEach(row => {
      html += "<tr>";
      headers.forEach(h => { html += `<td>${escapeHtml(String(row[h] ?? ""))}</td>`; });
      html += "</tr>";
    });
    html += "</tbody></table>";
  }

  html += renderRetryButton(data);

  div.innerHTML = html;
  chatBox.appendChild(div);
  renderChart(data, div);
  chatBox.scrollTop = chatBox.scrollHeight;
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function questionWantsChart(question) {
  const q = question.toLowerCase();

  const chartWords = [
    "chart",
    "graph",
    "visual",
    "visualization",
    "plot",
    "bar chart",
    "line chart",
    "pie chart"
  ];

  return chartWords.some(word => q.includes(word));
}

function detectChartType(question, rows) {
  const q = question.toLowerCase();

  if (q.includes("line")) return "line";
  if (q.includes("pie")) return "pie";
  if (q.includes("bar")) return "bar";

  if (!rows || rows.length === 0) return null;

  const headers = Object.keys(rows[0]);
  const numericCols = headers.filter(h => rows.some(r => !isNaN(Number(r[h]))));

  if (numericCols.length === 1 && rows.length <= 8) {
    return "pie";
  }

  return "bar";
}

function getChartColumns(rows) {
  if (!rows || rows.length === 0) return null;

  const headers = Object.keys(rows[0]);

  const numericCols = headers.filter(h =>
    rows.some(row => {
      const value = Number(row[h]);
      return !isNaN(value) && value !== null;
    })
  );

  const labelCols = headers.filter(h => !numericCols.includes(h));

  if (labelCols.length === 0 || numericCols.length === 0) {
    return null;
  }

  return {
    labelCol: labelCols[0],
    numericCols: numericCols
  };
}

function generateRandomColor(index) {
  const hue = (index * 137.508) % 360;
  return `hsl(${hue}, 75%, 55%)`;
}

function generateColorList(count) {
  return Array.from({ length: count }, (_, i) => generateRandomColor(i));
}

function renderChart(data, container) {
  if (!questionWantsChart(data.question)) return;
  if (!data.rows || data.rows.length === 0) return;

  const chartInfo = getChartColumns(data.rows);
  if (!chartInfo) return;

  const chartType = detectChartType(data.question, data.rows);
  const finalType = chartType === "pie" && chartInfo.numericCols.length > 1 ? "bar" : chartType;

  const chartId = `chart-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

  const chartCard = document.createElement("div");
  chartCard.className = "chart-card";

  chartCard.innerHTML = `
    <div class="chart-header">
      <div class="chart-title">Visualization</div>
      <div class="chart-actions">
        <button onclick="toggleChart('${chartId}')">Toggle</button>
        <button onclick="downloadChart('${chartId}')">Download</button>
      </div>
    </div>
    <div class="chart-wrapper">
      <canvas id="${chartId}"></canvas>
    </div>
  `;

  container.appendChild(chartCard);

  const labels = data.rows.map(row => String(row[chartInfo.labelCol]));
  

  let datasets = [];

  if (finalType === "pie") {
    const colors = generateColorList(data.rows.length);

    datasets = [{
      label: chartInfo.numericCols[0],
      data: data.rows.map(row => Number(row[chartInfo.numericCols[0]]) || 0),
      backgroundColor: colors,
      borderColor: "#ffffff",
      borderWidth: 2
    }];
  } else {
    const colors = generateColorList(data.rows.length);

    datasets = chartInfo.numericCols.map(col => ({
      label: col,
      data: data.rows.map(row => Number(row[col]) || 0),
      backgroundColor: colors,
      borderColor: colors,
      borderWidth: 1
    }));
  }

  const ctx = document.getElementById(chartId);

  new Chart(ctx, {
    type: finalType,
    data: {
      labels,
      datasets
    },
    options: {
      indexAxis: finalType === "bar" ? "y" : "x",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: "top",
          labels: {
            usePointStyle: true,
            boxWidth: 10,
            font: {
              size: 11
            }
          }
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return `${context.dataset.label}: ${formatNumber(context.raw)}`;
            }
          }
        }
      },
      scales: finalType === "pie" ? {} : {
        x: {
          beginAtZero: true
        }
      }
    }
  });
}

function formatNumber(num) {
  if (num >= 1e7) return (num / 1e7).toFixed(1) + "Cr";
  if (num >= 1e5) return (num / 1e5).toFixed(1) + "L";
  return num.toLocaleString();
}

function toggleChart(chartId) {
  const canvas = document.getElementById(chartId);
  const parent = canvas.parentElement;

  if (parent.style.display === "none") {
    parent.style.display = "block";
  } else {
    parent.style.display = "none";
  }
}
function downloadChart(chartId) {
  const canvas = document.getElementById(chartId);
  const url = canvas.toDataURL("image/png");

  const a = document.createElement("a");
  a.href = url;
  a.download = "chart.png";
  a.click();
}

function toggleApiBox() {
  const box = document.getElementById("apiBox");
  box.style.display = box.style.display === "none" ? "block" : "none";
}

async function uploadFromApi() {
  const curl = document.getElementById("curlInput").value.trim();
  const maxPages = Number(document.getElementById("maxPagesInput").value || 1);
  const status = document.getElementById("apiStatus");

  if (!curl) {
    status.innerText = "Paste cURL first";
    return;
  }

  startApiLoading();

  try {
    const res = await fetch("/upload/api", {
      method: "POST",
      headers: {
        "Content-Type": "application/json"
      },
      body: JSON.stringify({
        curl: curl,
        max_pages: maxPages
      })
    });

    updateApiLoadingText("Processing received data...");

    const data = await res.json();

    if (data.error) {
      stopApiLoading();
      status.innerText = "Error: " + data.error;
      return;
    }

    sessionId = data.session_id;
    window.sessionId = data.session_id;
    latestDatasetInfo = data;

    document.getElementById("datasetSummary").innerHTML = `
      <p><strong>Rows:</strong> ${data.rows}</p>
      <p><strong>Dimensions:</strong> ${data.dimensions.length}</p>
      <p><strong>Measures:</strong> ${data.measures.length}</p>
    `;

    renderDatasetDetails(data);

    const info = document.getElementById("sessionInfo");
    if (info) {
      info.innerHTML = `<span class="dot dot--active"></span>API Dataset`;
    }

    const empty = document.querySelector(".empty-state");
    if (empty) empty.remove();

    stopApiLoading();
    status.innerText = `Loaded ${data.rows} rows`;

    addBotMessage("API data loaded successfully. You can ask questions now.");

  } catch (err) {
    stopApiLoading();
    status.innerText = "API failed";
    console.error(err);
  }
}

function startApiLoading() {
  const loadingBox = document.getElementById("apiLoadingBox");
  const status = document.getElementById("apiStatus");

  loadingBox.style.display = "block";
  status.innerText = "";

  apiStartTime = Date.now();

  updateApiLoadingText("Connecting to API...");

  apiTimer = setInterval(() => {
    const seconds = Math.floor((Date.now() - apiStartTime) / 1000);
    document.getElementById("apiElapsedTime").innerText = `${seconds}s`;

    if (seconds === 3) updateApiLoadingText("Fetching API response...");
    if (seconds === 8) updateApiLoadingText("Large data detected, still loading...");
    if (seconds === 15) updateApiLoadingText("Processing rows, dimensions and measures...");
  }, 1000);
}

function stopApiLoading() {
  const loadingBox = document.getElementById("apiLoadingBox");

  loadingBox.style.display = "none";

  if (apiTimer) {
    clearInterval(apiTimer);
    apiTimer = null;
  }
}

function updateApiLoadingText(text) {
  const el = document.getElementById("apiLoadingText");
  if (el) el.innerText = text;
}

function renderDatasetDetails(data) {
  const box = document.getElementById("datasetDetailsBox");
  const content = document.getElementById("datasetDetailsContent");

  box.style.display = "block";

  content.innerHTML = `
    <div class="detail-section">
      <h4>Dataset Overview</h4>
      <p><strong>Rows:</strong> ${data.rows}</p>
      <p><strong>Total Columns:</strong> ${data.columns.length}</p>
      <p><strong>Total Dimensions:</strong> ${data.dimensions.length}</p>
      <p><strong>Total Measures:</strong> ${data.measures.length}</p>
    </div>

    <div class="detail-section">
      <h4>Dimensions</h4>
      <div class="tag-list">
        ${data.dimensions.map(d => `<span>${escapeHtml(d)}</span>`).join("")}
      </div>
    </div>

    <div class="detail-section">
      <h4>Measures</h4>
      <div class="tag-list">
        ${data.measures.map(m => `<span>${escapeHtml(m)}</span>`).join("")}
      </div>
    </div>

    <div class="detail-section">
      <h4>All Columns</h4>
      <div class="tag-list">
        ${data.columns.map(c => `<span>${escapeHtml(c)}</span>`).join("")}
      </div>
    </div>
  `;
}

function toggleDatasetDetails() {
  const content = document.getElementById("datasetDetailsContent");

  if (content.style.display === "none") {
    content.style.display = "block";
  } else {
    content.style.display = "none";
  }
}