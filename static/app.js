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
  $$(".embed-only").forEach((node) => { node.hidden = mode !== "embed"; });
  $(".step-number").textContent = mode === "embed" ? "3" : "2";
  $(".button-label").textContent = mode === "embed" ? "產生隱寫圖片" : "讀取隱藏內容";
  $("#processing-label").textContent = mode === "embed"
    ? (state.payloadType === "text" ? "正在嵌入文字" : "正在嵌入圖片")
    : "正在讀取內容";
  updateCapacity();
}

function clearFile() {
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
    return;
  }
  if (file.size > 30 * 1024 * 1024) {
    showError("隱藏圖片不可大於 30 MB。");
    return;
  }
  if (state.hiddenObjectUrl) URL.revokeObjectURL(state.hiddenObjectUrl);
  state.hiddenFile = file;
  state.hiddenObjectUrl = URL.createObjectURL(file);
  $("#hidden-image-thumb").src = state.hiddenObjectUrl;
  $("#hidden-image-thumb").hidden = false;
  $("#hidden-image-copy strong").textContent = file.name;
  $("#hidden-image-copy small").textContent = `${formatBytes(file.size)} · 按一下可更換`;
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
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = getDownloadName(response, "watermarked.png");
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 3000);
      toast("圖片已完成並開始下載");
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

$$(".mode-tab").forEach((tab) => tab.addEventListener("click", () => setMode(tab.dataset.mode)));
$$(".payload-tab").forEach((tab) => tab.addEventListener("click", () => setPayloadType(tab.dataset.payload)));
fileInput.addEventListener("change", () => selectImage(fileInput.files[0]));
$("#hidden-image-input").addEventListener("change", (event) => selectHiddenImage(event.target.files[0]));
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
  if (await selectImage(pastedFile)) toast("已從剪貼簿貼上圖片");
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

updateMessageCount();
