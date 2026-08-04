const state = {
  mode: "embed",
  payloadType: "text",
  file: null,
  objectUrl: null,
  capacity: null,
  dimensions: null,
  busy: false,
  hiddenFile: null,
  hiddenObjectUrl: null,
  extractedObjectUrl: null,
  extractedFilename: null,
  outputObjectUrl: null,
  outputFilename: null,
};

const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

const form = $("#process-form");
const fileInput = $("#image-input");
const dropzone = $("#dropzone");
const selectedFile = $("#selected-file");
const formError = $("#form-error");
const message = $("#message");
const useKey = $("#use-key");
const keyInput = $("#key");
const resultCard = $("#result-card");
const zeroWidthForm = $("#zero-width-form");
let zeroWidthMode = "hide";
const lsbState = {
  mode: "embed",
  carrierFile: null,
  carrierObjectUrl: null,
  secretFile: null,
  secretObjectUrl: null,
  resultObjectUrl: null,
  resultFilename: null,
  capacity: null,
  busy: false,
};
const supportedImageTypes = new Set(["image/png", "image/jpeg", "image/webp", "image/bmp", "image/x-ms-bmp"]);
const pastedImageExtensions = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/webp": "webp",
  "image/bmp": "bmp",
  "image/x-ms-bmp": "bmp",
};

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

function utf8Length(value) {
  return new TextEncoder().encode(value).length;
}

function showError(text) {
  formError.textContent = text;
  formError.hidden = false;
}

function clearError() {
  formError.textContent = "";
  formError.hidden = true;
}

let toastTimer;
function toast(text) {
  const node = $("#toast");
  node.textContent = text;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 3200);
}

function setBusy(busy, label = "正在處理圖片") {
  state.busy = busy;
  $("#submit-button").disabled = busy;
  $("#processing-label").textContent = label;
  $("#processing").hidden = !busy;
}

function clearOutputPreview() {
  if (state.outputObjectUrl) URL.revokeObjectURL(state.outputObjectUrl);
  state.outputObjectUrl = null;
  state.outputFilename = null;
  $("#preview-download-hint").hidden = true;
}

function updateMessageCount() {
  const bytes = utf8Length(message.value);
  $("#message-count").textContent = `${bytes.toLocaleString()} bytes`;
  const isOver = Number.isInteger(state.capacity) && bytes > state.capacity;
  $("#message-count").classList.toggle("over-limit", isOver);
  if (Number.isInteger(state.capacity)) {
    $("#capacity-label").textContent = `上限 ${state.capacity.toLocaleString()} bytes`;
    $("#image-capacity-label").textContent = `可用 ${state.capacity.toLocaleString()} bytes；圖片會自動壓縮與縮小。`;
    $("#capacity-label").classList.toggle("over-limit", isOver);
  }
}

function setPayloadType(type) {
  state.payloadType = type;
  clearError();
  $$(".payload-tab").forEach((tab) => {
    const active = tab.dataset.payload === type;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $$('[data-payload-panel]').forEach((panel) => {
    panel.hidden = panel.dataset.payloadPanel !== type;
  });
  $("#processing-label").textContent = type === "text" ? "正在嵌入文字" : "正在嵌入圖片";
}

function setMode(mode) {
  state.mode = mode;
  clearError();
  resultCard.hidden = true;
  if (state.extractedObjectUrl) URL.revokeObjectURL(state.extractedObjectUrl);
  state.extractedObjectUrl = null;
  state.extractedFilename = null;
  $$(".mode-tab").forEach((tab) => {
    const active = tab.dataset.mode === mode;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  const isZeroWidth = mode === "zero-width";
  const isLsb = mode === "lsb";
  $("#image-workspace").hidden = isZeroWidth || isLsb;
  $("#lsb-workspace").hidden = !isLsb;
  $("#zero-width-workspace").hidden = !isZeroWidth;
  $("#page-title").textContent = isZeroWidth
    ? "文字隱寫處理"
    : (isLsb ? "LSB 圖片隱寫" : "圖片隱寫處理");
  $("#page-description").textContent = isZeroWidth
    ? "用 U+200B 與 U+200C 把秘密文字藏進另一段文字，亦可隨時提取。"
    : (isLsb
      ? "把一張圖片無損寫入另一張圖片的 RGB 最低有效位元，並可完整提取。"
      : "把文字或另一張圖片嵌入載體圖片，之後可完整辨識內容類型並取回。");
  if (isZeroWidth || isLsb) return;
  $$(".embed-only").forEach((node) => { node.hidden = mode !== "embed"; });
  $(".step-number").textContent = mode === "embed" ? "3" : "2";
  $(".button-label").textContent = mode === "embed" ? "產生隱寫圖片" : "讀取隱藏內容";
  $("#processing-label").textContent = mode === "embed"
    ? (state.payloadType === "text" ? "正在嵌入文字" : "正在嵌入圖片")
    : "正在讀取內容";
  updateCapacity();
}

function setZeroWidthMode(mode) {
  zeroWidthMode = mode;
  $("#zero-width-error").hidden = true;
  $$(".zero-width-tab").forEach((tab) => {
    const active = tab.dataset.zeroWidthMode === mode;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $("#zero-width-hide-panel").hidden = mode !== "hide";
  $("#zero-width-extract-panel").hidden = mode !== "extract";
  $("#zero-width-submit-label").textContent = mode === "hide" ? "產生隱寫文字" : "提取秘密文字";
  $("#zero-width-result").hidden = true;
  $("#zero-width-empty").hidden = false;
  $("#zero-width-result-title").textContent = "等待輸入內容";
}

function updateZeroWidthCounts() {
  const carrierLength = [...$("#carrier-text").value].length;
  const secretBytes = utf8Length($("#secret-text").value);
  const zeroWidthCount = [...$("#stego-text").value].filter(
    (character) => character === ZeroWidthSteg.ZERO || character === ZeroWidthSteg.ONE,
  ).length;
  $("#carrier-count").textContent = `${carrierLength.toLocaleString()} 個字元`;
  $("#secret-count").textContent = `${secretBytes.toLocaleString()} bytes`;
  $("#secret-bits").textContent = `會產生 ${(secretBytes * 8).toLocaleString()} 個零寬字元`;
  $("#stego-count").textContent = `${zeroWidthCount.toLocaleString()} 個零寬字元`;
}

function showZeroWidthError(text) {
  const error = $("#zero-width-error");
  error.textContent = text;
  error.hidden = false;
}

async function copyText(value) {
  try {
    await navigator.clipboard.writeText(value);
  } catch {
    const helper = document.createElement("textarea");
    helper.value = value;
    helper.setAttribute("readonly", "");
    helper.style.position = "fixed";
    helper.style.opacity = "0";
    document.body.appendChild(helper);
    helper.select();
    document.execCommand("copy");
    helper.remove();
  }
}

function clearFile() {
  clearOutputPreview();
  state.file = null;
  state.capacity = null;
  state.dimensions = null;
  fileInput.value = "";
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.objectUrl = null;
  dropzone.hidden = false;
  selectedFile.hidden = true;
  $("#large-preview").hidden = true;
  $("#empty-preview").hidden = false;
  $("#image-stage").classList.add("empty");
  $("#image-stats").hidden = true;
  $("#format-badge").hidden = true;
  $("#preview-title").textContent = "尚未選擇圖片";
  $("#capacity-label").textContent = "選擇圖片後顯示容量";
  $("#image-capacity-label").textContent = "選擇載體圖片後顯示可用容量。";
  resultCard.hidden = true;
  updateMessageCount();
}

async function selectHiddenImage(file) {
  clearError();
  if (!file || !supportedImageTypes.has(file.type.toLowerCase())) {
    showError("隱藏圖片只支援 PNG、JPEG、WebP 或 BMP。");
    return false;
  }
  if (file.size > 30 * 1024 * 1024) {
    showError("隱藏圖片不可大於 30 MB。");
    return false;
  }
  if (state.hiddenObjectUrl) URL.revokeObjectURL(state.hiddenObjectUrl);
  state.hiddenFile = file;
  state.hiddenObjectUrl = URL.createObjectURL(file);
  $("#hidden-image-thumb").src = state.hiddenObjectUrl;
  $("#hidden-image-thumb").hidden = false;
  $("#hidden-image-copy strong").textContent = file.name;
  $("#hidden-image-copy small").textContent = `${formatBytes(file.size)} · 按一下可更換`;
  return true;
}

async function selectImage(file) {
  clearError();
  if (!file || !supportedImageTypes.has(file.type.toLowerCase())) {
    showError("只支援 PNG、JPEG、WebP 或 BMP 圖片。");
    return false;
  }
  if (file.size > 30 * 1024 * 1024) {
    showError("圖片不可大於 30 MB。");
    return false;
  }

  clearOutputPreview();
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  state.file = file;
  state.objectUrl = URL.createObjectURL(file);
  const preview = $("#large-preview");
  preview.src = state.objectUrl;
  $("#file-thumb").src = state.objectUrl;

  const dimensions = await new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => resolve(null);
    image.src = state.objectUrl;
  });
  if (!dimensions) {
    clearFile();
    showError("無法讀取這張圖片。");
    return false;
  }

  state.dimensions = dimensions;
  dropzone.hidden = true;
  selectedFile.hidden = false;
  $("#file-name").textContent = file.name;
  $("#file-meta").textContent = `${dimensions.width} × ${dimensions.height} · ${formatBytes(file.size)}`;
  preview.hidden = false;
  $("#empty-preview").hidden = true;
  $("#image-stage").classList.remove("empty");
  $("#preview-title").textContent = file.name;
  $("#format-badge").textContent = (file.name.split(".").pop() || "IMG").toUpperCase();
  $("#format-badge").hidden = false;
  $("#stat-dimensions").textContent = `${dimensions.width} × ${dimensions.height}`;
  $("#stat-size").textContent = formatBytes(file.size);
  $("#stat-capacity").textContent = "計算中";
  $("#image-stats").hidden = false;
  resultCard.hidden = true;
  await updateCapacity();
  return true;
}

async function updateCapacity() {
  if (!state.file || state.mode !== "embed") {
    state.capacity = null;
    if (state.file) $("#stat-capacity").textContent = "—";
    updateMessageCount();
    return;
  }
  const data = new FormData();
  data.append("image", state.file);
  data.append("redundancy", $("#redundancy").value);
  try {
    const response = await fetch("/api/capacity", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "無法計算圖片容量");
    state.capacity = payload.max_payload_bytes;
    $("#stat-capacity").textContent = `${payload.max_payload_bytes.toLocaleString()} bytes`;
    updateMessageCount();
  } catch (error) {
    state.capacity = null;
    $("#stat-capacity").textContent = "無法計算";
  }
}

function getDownloadName(response, fallback) {
  const header = response.headers.get("Content-Disposition") || "";
  const utf8 = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (utf8) return decodeURIComponent(utf8[1]);
  const plain = header.match(/filename="?([^";]+)"?/i);
  return plain ? plain[1] : fallback;
}

async function parseError(response) {
  try {
    const payload = await response.json();
    return payload.error || "處理失敗，請檢查圖片與設定。";
  } catch {
    return "處理失敗，請稍後再試。";
  }
}

function showLsbError(text) {
  const node = $("#lsb-error");
  node.textContent = text;
  node.hidden = false;
}

function clearLsbError() {
  const node = $("#lsb-error");
  node.textContent = "";
  node.hidden = true;
}

function clearLsbResult() {
  if (lsbState.resultObjectUrl) URL.revokeObjectURL(lsbState.resultObjectUrl);
  lsbState.resultObjectUrl = null;
  lsbState.resultFilename = null;
  $("#lsb-result-card").hidden = true;
  if (lsbState.carrierObjectUrl) $("#lsb-large-preview").src = lsbState.carrierObjectUrl;
}

function clearLsbCarrier() {
  clearLsbError();
  clearLsbResult();
  lsbState.carrierFile = null;
  lsbState.capacity = null;
  $("#lsb-carrier-input").value = "";
  if (lsbState.carrierObjectUrl) URL.revokeObjectURL(lsbState.carrierObjectUrl);
  lsbState.carrierObjectUrl = null;
  $("#lsb-dropzone").hidden = false;
  $("#lsb-selected-file").hidden = true;
  $("#lsb-large-preview").hidden = true;
  $("#lsb-empty-preview").hidden = false;
  $("#lsb-image-stage").classList.add("empty");
  $("#lsb-image-stats").hidden = true;
  $("#lsb-format-badge").hidden = true;
  $("#lsb-preview-title").textContent = "尚未選擇圖片";
  $("#lsb-capacity-label").textContent = "選擇載體圖片後顯示容量。";
}

function loadImageDimensions(url) {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth, height: image.naturalHeight });
    image.onerror = () => resolve(null);
    image.src = url;
  });
}

async function updateLsbCapacity() {
  if (!lsbState.carrierFile) return;
  const data = new FormData();
  data.append("image", lsbState.carrierFile);
  $("#lsb-stat-capacity").textContent = "計算中";
  try {
    const response = await fetch("/api/lsb/capacity", { method: "POST", body: data });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || "無法計算 LSB 容量");
    lsbState.capacity = payload.max_payload_bytes;
    $("#lsb-stat-capacity").textContent = formatBytes(payload.max_payload_bytes);
    const secretSize = lsbState.secretFile ? `；目前秘密檔案 ${formatBytes(lsbState.secretFile.size)}` : "";
    $("#lsb-capacity-label").textContent = `最多可寫入 ${formatBytes(payload.max_payload_bytes)} 的 PNG 資料${secretSize}。`;
  } catch {
    lsbState.capacity = null;
    $("#lsb-stat-capacity").textContent = "無法計算";
  }
}

async function selectLsbCarrier(file) {
  clearLsbError();
  if (!file || !supportedImageTypes.has(file.type.toLowerCase())) {
    showLsbError("圖片只支援 PNG、JPEG、WebP 或 BMP。");
    return false;
  }
  if (file.size > 30 * 1024 * 1024) {
    showLsbError("圖片不可大於 30 MB。");
    return false;
  }

  clearLsbResult();
  if (lsbState.carrierObjectUrl) URL.revokeObjectURL(lsbState.carrierObjectUrl);
  lsbState.carrierFile = file;
  lsbState.carrierObjectUrl = URL.createObjectURL(file);
  const dimensions = await loadImageDimensions(lsbState.carrierObjectUrl);
  if (!dimensions) {
    clearLsbCarrier();
    showLsbError("無法讀取這張圖片。");
    return false;
  }

  $("#lsb-dropzone").hidden = true;
  $("#lsb-selected-file").hidden = false;
  $("#lsb-file-thumb").src = lsbState.carrierObjectUrl;
  $("#lsb-file-name").textContent = file.name;
  $("#lsb-file-meta").textContent = `${dimensions.width} × ${dimensions.height} · ${formatBytes(file.size)}`;
  $("#lsb-large-preview").src = lsbState.carrierObjectUrl;
  $("#lsb-large-preview").hidden = false;
  $("#lsb-empty-preview").hidden = true;
  $("#lsb-image-stage").classList.remove("empty");
  $("#lsb-preview-title").textContent = file.name;
  $("#lsb-format-badge").textContent = (file.name.split(".").pop() || "IMG").toUpperCase();
  $("#lsb-format-badge").hidden = false;
  $("#lsb-stat-dimensions").textContent = `${dimensions.width} × ${dimensions.height}`;
  $("#lsb-stat-size").textContent = formatBytes(file.size);
  $("#lsb-image-stats").hidden = false;
  await updateLsbCapacity();
  return true;
}

async function selectLsbSecret(file) {
  clearLsbError();
  if (!file || !supportedImageTypes.has(file.type.toLowerCase())) {
    showLsbError("秘密圖片只支援 PNG、JPEG、WebP 或 BMP。");
    return false;
  }
  if (file.size > 30 * 1024 * 1024) {
    showLsbError("秘密圖片不可大於 30 MB。");
    return false;
  }
  clearLsbResult();
  if (lsbState.secretObjectUrl) URL.revokeObjectURL(lsbState.secretObjectUrl);
  lsbState.secretFile = file;
  lsbState.secretObjectUrl = URL.createObjectURL(file);
  $("#lsb-secret-thumb").src = lsbState.secretObjectUrl;
  $("#lsb-secret-thumb").hidden = false;
  $("#lsb-secret-copy strong").textContent = file.name;
  $("#lsb-secret-copy small").textContent = `${formatBytes(file.size)} · 按一下可更換`;
  if (lsbState.carrierFile) await updateLsbCapacity();
  return true;
}

function setLsbMode(mode) {
  lsbState.mode = mode;
  clearLsbError();
  clearLsbResult();
  $$(".lsb-action-tab").forEach((tab) => {
    const active = tab.dataset.lsbMode === mode;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  $$(".lsb-embed-only").forEach((node) => { node.hidden = mode !== "embed"; });
  $("#lsb-carrier-label").textContent = mode === "embed" ? "選擇載體圖片" : "選擇 LSB 隱寫圖片";
  $("#lsb-dropzone-title").textContent = mode === "embed" ? "拖放或選擇載體圖片" : "拖放或選擇 LSB 隱寫圖片";
  $("#lsb-dropzone-note").textContent = mode === "embed"
    ? "載體越大，可隱藏的圖片資料越多"
    : "只支援本工具產生、未被修改的 PNG";
  $("#lsb-submit-label").textContent = mode === "embed" ? "產生 LSB 隱寫圖片" : "提取隱藏圖片";
}

function setLsbBusy(busy, label) {
  lsbState.busy = busy;
  $("#lsb-submit").disabled = busy;
  $("#lsb-processing-label").textContent = label;
  $("#lsb-processing").hidden = !busy;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.busy) return;
  clearError();
  resultCard.hidden = true;

  if (!state.file) {
    showError("請先選擇圖片。");
    return;
  }
  if (state.mode === "embed" && !message.value) {
    if (state.payloadType === "text") {
      showError("請輸入要隱藏的文字。");
      message.focus();
      return;
    }
  }
  if (state.mode === "embed" && state.payloadType === "image" && !state.hiddenFile) {
    showError("請選擇要隱藏的圖片。");
    return;
  }
  if (state.mode === "embed" && state.payloadType === "text" && Number.isInteger(state.capacity) && utf8Length(message.value) > state.capacity) {
    showError("文字超出這張圖片目前可用的容量。");
    return;
  }

  const data = new FormData();
  data.append("image", state.file);
  data.append("key", useKey.checked ? keyInput.value : "");
  data.append("strength", $("#strength").value);
  const busyLabel = state.mode === "extract"
    ? "正在讀取內容"
    : (state.payloadType === "text" ? "正在嵌入文字" : "正在壓縮並嵌入圖片");
  setBusy(true, busyLabel);

  try {
    if (state.mode === "embed") {
      data.append("payload_type", state.payloadType);
      if (state.payloadType === "text") data.append("text", message.value);
      else data.append("hidden_image", state.hiddenFile);
      data.append("redundancy", $("#redundancy").value);
      data.append("output_format", $("#output-format").value);
      data.append("quality", $("#quality").value);
      const response = await fetch("/api/embed", { method: "POST", body: data });
      if (!response.ok) throw new Error(await parseError(response));
      const blob = await response.blob();
      clearOutputPreview();
      state.outputObjectUrl = URL.createObjectURL(blob);
      state.outputFilename = getDownloadName(response, "watermarked.png");
      const preview = $("#large-preview");
      preview.src = state.outputObjectUrl;
      preview.alt = "輸出的隱寫圖片預覽";
      $("#preview-title").textContent = state.outputFilename;
      $("#format-badge").textContent = (state.outputFilename.split(".").pop() || "IMG").toUpperCase();
      $("#stat-size").textContent = formatBytes(blob.size);
      $("#preview-download-hint").hidden = false;
      toast("圖片已完成，可在預覽圖上按右鍵下載");
    } else {
      const response = await fetch("/api/extract", { method: "POST", body: data });
      if (!response.ok) throw new Error(await parseError(response));
      const payload = await response.json();
      if (state.extractedObjectUrl) URL.revokeObjectURL(state.extractedObjectUrl);
      if (payload.type === "image") {
        const binary = atob(payload.image_base64);
        const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
        const blob = new Blob([bytes], { type: payload.mime_type });
        state.extractedObjectUrl = URL.createObjectURL(blob);
        state.extractedFilename = payload.filename || "hidden-image.webp";
        $("#result-image").src = state.extractedObjectUrl;
        $("#result-image-wrap").hidden = false;
        $("#result-text").hidden = true;
        $("#result-action").textContent = "下載圖片";
        $("#result-meta").textContent = `${payload.width} × ${payload.height} · ${formatBytes(payload.byte_count)}`;
      } else {
        state.extractedObjectUrl = null;
        state.extractedFilename = null;
        $("#result-text").textContent = payload.text;
        $("#result-text").hidden = false;
        $("#result-image-wrap").hidden = true;
        $("#result-action").textContent = "複製文字";
        $("#result-meta").textContent = `${payload.byte_count.toLocaleString()} bytes`;
      }
      resultCard.hidden = false;
      resultCard.scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  } catch (error) {
    showError(error.message || "處理失敗，請檢查圖片與設定。");
  } finally {
    setBusy(false);
  }
});

$("#lsb-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (lsbState.busy) return;
  clearLsbError();
  clearLsbResult();
  if (!lsbState.carrierFile) {
    showLsbError(lsbState.mode === "embed" ? "請先選擇載體圖片。" : "請先選擇 LSB 隱寫圖片。");
    return;
  }
  if (lsbState.mode === "embed" && !lsbState.secretFile) {
    showLsbError("請選擇要隱藏的圖片。");
    return;
  }

  const data = new FormData();
  data.append("image", lsbState.carrierFile);
  if (lsbState.mode === "embed") data.append("hidden_image", lsbState.secretFile);
  setLsbBusy(true, lsbState.mode === "embed" ? "正在寫入 LSB 資料" : "正在提取隱藏圖片");

  try {
    const endpoint = lsbState.mode === "embed" ? "/api/lsb/embed" : "/api/lsb/extract";
    const response = await fetch(endpoint, { method: "POST", body: data });
    if (!response.ok) throw new Error(await parseError(response));
    const blob = await response.blob();
    lsbState.resultObjectUrl = URL.createObjectURL(blob);
    lsbState.resultFilename = getDownloadName(
      response,
      lsbState.mode === "embed" ? "lsb-stego.png" : "lsb-hidden-image.png",
    );
    $("#lsb-result-image").src = lsbState.resultObjectUrl;
    $("#lsb-result-title").textContent = lsbState.mode === "embed" ? "LSB 隱寫圖片已產生" : "隱藏圖片已提取";
    const hiddenDimensions = response.headers.get("X-Hidden-Image-Size");
    $("#lsb-result-meta").textContent = [hiddenDimensions, formatBytes(blob.size), lsbState.resultFilename].filter(Boolean).join(" · ");
    $("#lsb-result-card").hidden = false;
    if (lsbState.mode === "embed") {
      $("#lsb-large-preview").src = lsbState.resultObjectUrl;
      $("#lsb-preview-title").textContent = lsbState.resultFilename;
      $("#lsb-format-badge").textContent = "PNG";
      $("#lsb-stat-size").textContent = formatBytes(blob.size);
    }
    $("#lsb-result-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
    toast(lsbState.mode === "embed" ? "LSB 隱寫圖片已完成" : "隱藏圖片已成功提取");
  } catch (error) {
    showLsbError(error.message || "LSB 圖片處理失敗。");
  } finally {
    setLsbBusy(false, "正在處理 LSB 資料");
  }
});

$$(".mode-tab").forEach((tab) => tab.addEventListener("click", () => setMode(tab.dataset.mode)));
$$(".payload-tab").forEach((tab) => tab.addEventListener("click", () => setPayloadType(tab.dataset.payload)));
$$(".zero-width-tab").forEach((tab) => tab.addEventListener("click", () => setZeroWidthMode(tab.dataset.zeroWidthMode)));
$$(".lsb-action-tab").forEach((tab) => tab.addEventListener("click", () => setLsbMode(tab.dataset.lsbMode)));
fileInput.addEventListener("change", () => selectImage(fileInput.files[0]));
$("#hidden-image-input").addEventListener("change", (event) => selectHiddenImage(event.target.files[0]));
$("#lsb-carrier-input").addEventListener("change", (event) => selectLsbCarrier(event.target.files[0]));
$("#lsb-secret-input").addEventListener("change", (event) => selectLsbSecret(event.target.files[0]));
$("#lsb-remove-file").addEventListener("click", clearLsbCarrier);
$("#remove-file").addEventListener("click", clearFile);
message.addEventListener("input", updateMessageCount);
$("#redundancy").addEventListener("change", updateCapacity);

["dragenter", "dragover"].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault();
  dropzone.classList.add("dragover");
}));
["dragleave", "drop"].forEach((name) => dropzone.addEventListener(name, (event) => {
  event.preventDefault();
  dropzone.classList.remove("dragover");
}));
dropzone.addEventListener("drop", (event) => selectImage(event.dataTransfer.files[0]));

["dragenter", "dragover"].forEach((name) => $("#lsb-dropzone").addEventListener(name, (event) => {
  event.preventDefault();
  $("#lsb-dropzone").classList.add("dragover");
}));
["dragleave", "drop"].forEach((name) => $("#lsb-dropzone").addEventListener(name, (event) => {
  event.preventDefault();
  $("#lsb-dropzone").classList.remove("dragover");
}));
$("#lsb-dropzone").addEventListener("drop", (event) => selectLsbCarrier(event.dataTransfer.files[0]));

document.addEventListener("paste", async (event) => {
  const imageItem = [...(event.clipboardData?.items || [])].find(
    (item) => item.kind === "file" && item.type.startsWith("image/"),
  );
  if (!imageItem) return;

  event.preventDefault();
  const clipboardFile = imageItem.getAsFile();
  const extension = pastedImageExtensions[clipboardFile?.type.toLowerCase()];
  const pastedFile = clipboardFile && extension
    ? new File([clipboardFile], `pasted-image.${extension}`, { type: clipboardFile.type })
    : clipboardFile;
  if (state.mode === "lsb") {
    if (lsbState.mode === "embed" && lsbState.carrierFile) {
      if (await selectLsbSecret(pastedFile)) toast("已貼上要隱藏的圖片");
    } else if (await selectLsbCarrier(pastedFile)) {
      toast("已從剪貼簿貼上 LSB 圖片");
    }
    return;
  }
  const pasteAsHiddenImage = state.mode === "embed" && state.payloadType === "image";
  if (pasteAsHiddenImage) {
    if (await selectHiddenImage(pastedFile)) toast("已貼上要隱藏的圖片");
  } else if (await selectImage(pastedFile)) {
    toast("已從剪貼簿貼上載體圖片");
  }
});

useKey.addEventListener("change", () => {
  $("#key-input-row").hidden = !useKey.checked;
  if (!useKey.checked) {
    keyInput.value = "";
    toast("已設定為不使用金鑰");
  }
});

$("#toggle-key").addEventListener("click", (event) => {
  const showing = keyInput.type === "text";
  keyInput.type = showing ? "password" : "text";
  event.currentTarget.textContent = showing ? "顯示" : "隱藏";
  event.currentTarget.setAttribute("aria-label", showing ? "顯示金鑰" : "隱藏金鑰");
});

$("#strength").addEventListener("input", (event) => { $("#strength-value").textContent = event.target.value; });
$("#quality").addEventListener("input", (event) => { $("#quality-value").textContent = event.target.value; });
$("#output-format").addEventListener("change", (event) => { $("#quality-field").hidden = event.target.value === "png"; });

$("#result-action").addEventListener("click", async () => {
  if (state.extractedObjectUrl) {
    const link = document.createElement("a");
    link.href = state.extractedObjectUrl;
    link.download = state.extractedFilename || "hidden-image.webp";
    link.click();
    toast("隱藏圖片已下載");
  } else {
    await navigator.clipboard.writeText($("#result-text").textContent);
    toast("文字已複製");
  }
});

$("#lsb-result-action").addEventListener("click", () => {
  if (!lsbState.resultObjectUrl) return;
  const link = document.createElement("a");
  link.href = lsbState.resultObjectUrl;
  link.download = lsbState.resultFilename || "lsb-image.png";
  link.click();
  toast("圖片已下載");
});

zeroWidthForm.addEventListener("submit", (event) => {
  event.preventDefault();
  $("#zero-width-error").hidden = true;
  try {
    const result = zeroWidthMode === "hide"
      ? ZeroWidthSteg.hide($("#carrier-text").value, $("#secret-text").value)
      : ZeroWidthSteg.extract($("#stego-text").value);
    $("#zero-width-output").value = result.text;
    $("#zero-width-result-label").textContent = zeroWidthMode === "hide" ? "隱寫結果" : "提取結果";
    $("#zero-width-result-title").textContent = zeroWidthMode === "hide" ? "隱寫文字已產生" : "秘密文字已提取";
    $("#zero-width-meta").textContent = `${result.byteCount.toLocaleString()} bytes · ${result.bitCount.toLocaleString()} 個零寬字元`;
    $("#zero-width-empty").hidden = true;
    $("#zero-width-result").hidden = false;
    $("#zero-width-result").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    showZeroWidthError(error.message || "文字隱寫處理失敗。");
  }
});

$("#carrier-text").addEventListener("input", updateZeroWidthCounts);
$("#secret-text").addEventListener("input", updateZeroWidthCounts);
$("#stego-text").addEventListener("input", updateZeroWidthCounts);
$("#zero-width-copy").addEventListener("click", async () => {
  await copyText($("#zero-width-output").value);
  toast(zeroWidthMode === "hide" ? "隱寫文字已複製" : "秘密文字已複製");
});

window.addEventListener("beforeunload", () => {
  if (state.objectUrl) URL.revokeObjectURL(state.objectUrl);
  if (state.hiddenObjectUrl) URL.revokeObjectURL(state.hiddenObjectUrl);
  if (state.extractedObjectUrl) URL.revokeObjectURL(state.extractedObjectUrl);
  if (state.outputObjectUrl) URL.revokeObjectURL(state.outputObjectUrl);
  if (lsbState.carrierObjectUrl) URL.revokeObjectURL(lsbState.carrierObjectUrl);
  if (lsbState.secretObjectUrl) URL.revokeObjectURL(lsbState.secretObjectUrl);
  if (lsbState.resultObjectUrl) URL.revokeObjectURL(lsbState.resultObjectUrl);
});

updateMessageCount();
updateZeroWidthCounts();
