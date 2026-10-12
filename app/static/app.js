"use strict";

/* Must match pipeline.py constants. */
const LANGUAGES = ["英語", "國語", "日語", "韓語", "台語", "粵語"];
const CATEGORIES = ["男歌星", "女歌星", "團體", "合唱", "外國男", "外國女", "外國團體"];

const STR = {
  en: {
    app_title: "KTV OCR Renamer",
    upload_title: "Upload karaoke video",
    upload_hint: "Drop a video file below or pick one. The first 30 seconds are scanned for on-screen text and audio language.",
    drop_hint: "Drag & drop a video file here",
    or: "or",
    choose: "Choose file",
    analyze: "Analyze",
    analyzing: "Analyzing… (first run downloads models and is slower)",
    no_file: "Please choose a video file first.",
    result_title: "Results — confirm, then rename",
    frames_title: "Sampled frames",
    candidates_title: "OCR text candidates",
    chips_hint: "Tap a chip's buttons to copy its text into the Singer or Title field.",
    chip_singer: "Singer",
    chip_title: "Title",
    singer: "Singer",
    title: "Song title",
    language: "Language",
    category: "Category",
    preview_title: "Filename preview",
    rename: "Rename & Save",
    next: "Next song",
    renamed_ok: "Saved as",
    rename_need: "Please fill singer, title, language and category first.",
    error: "Error",
    ready: "Ready.",
    ocr_at: "OCR frame at current video position",
    frame_ocr_title: "Frame OCR",
    frame_ocr_hint: "Click a sampled frame above to see its text, or pause the video on the title card and capture that exact frame.",
    frames_hint: "Click a frame to inspect the text found in it.",
    select_prompt: "— select —",
    warn_no_frames: "Could not extract frames — is ffmpeg installed and on PATH?",
    warn_no_text: "No text found in the sampled frames — click a frame above or capture the title-card moment.",
    warn_no_lang: "Language detection found nothing — please choose the language manually.",
    frame_no_text: "No text found in this frame.",
    ocr_at_working: "Capturing frame…",
    ocr_at_failed: "Could not capture/OCR that frame."
  },
  zh: {
    app_title: "KTV OCR 改名工具",
    upload_title: "上傳卡拉OK影片",
    upload_hint: "將影片拖放到下方或選擇檔案。程式會掃描前 30 秒的畫面文字與聲音語言。",
    drop_hint: "將影片拖放到這裡",
    or: "或",
    choose: "選擇檔案",
    analyze: "開始分析",
    analyzing: "分析中…（首次執行需下載模型，會比較慢）",
    no_file: "請先選擇影片檔案。",
    result_title: "分析結果 — 確認後改名",
    frames_title: "擷取畫面",
    candidates_title: "OCR 文字候選",
    chips_hint: "點選標籤上的按鈕，可把文字填入歌手或歌名欄位。",
    chip_singer: "歌手",
    chip_title: "歌名",
    singer: "歌手",
    title: "歌名",
    language: "語言",
    category: "類別",
    preview_title: "檔名預覽",
    rename: "改名並儲存",
    next: "下一首",
    renamed_ok: "已儲存為",
    rename_need: "請先填寫歌手、歌名、語言與類別。",
    error: "錯誤",
    ready: "就緒。",
    ocr_at: "擷取目前影片位置的影格並 OCR",
    frame_ocr_title: "影格 OCR",
    frame_ocr_hint: "點選上方擷取畫面可查看該影格的文字，或將影片暫停在歌名畫面後擷取該影格。",
    frames_hint: "點選畫面可查看其 OCR 文字。",
    select_prompt: "— 請選擇 —",
    warn_no_frames: "無法擷取畫面 — 請確認已安裝 ffmpeg 並加入 PATH？",
    warn_no_text: "擷取畫面中找不到文字 — 請點選上方畫面或在歌名出現時擷取影格。",
    warn_no_lang: "語言偵測沒有結果 — 請手動選擇語言。",
    frame_no_text: "此影格中找不到文字。",
    ocr_at_working: "擷取影格中…",
    ocr_at_failed: "無法擷取/辨識該影格。"
  }
};

let lang = "en";
let state = { fileId: null, ext: "", file: null, candidates: [], frameTexts: {} };

const $ = (id) => document.getElementById(id);
const t = (key) => (STR[lang] && STR[lang][key]) || STR.en[key] || key;

function buildSelects() {
  const keepL = $("language").value, keepC = $("category").value;
  const mk = (sel, values, keep) => {
    sel.innerHTML = "";
    const ph = document.createElement("option");
    ph.value = "";
    ph.textContent = t("select_prompt");
    sel.appendChild(ph);
    values.forEach((v) => {
      const o = document.createElement("option");
      o.value = v;
      o.textContent = v;
      sel.appendChild(o);
    });
    sel.value = keep || "";
  };
  mk($("language"), LANGUAGES, keepL);
  mk($("category"), CATEGORIES, keepC);
}

function setLang(l) {
  lang = l;
  document.documentElement.lang = l === "zh" ? "zh-Hant" : "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  $("langToggle").textContent = l === "en" ? "中文" : "EN";
  buildSelects();
  renderChips();
  renderFrameChips(state._frameChipTexts || null);
  updatePreview();
}

function setStatus(msg, isErr) {
  const el = $("status");
  el.textContent = msg || "";
  el.classList.toggle("err", !!isErr);
}

function renderChips() {
  const box = $("chips");
  box.innerHTML = "";
  state.candidates.forEach((c) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    const txt = document.createElement("span");
    txt.className = "chip-text";
    txt.textContent = c.text;
    txt.title = c.text + "  (" + c.score + ")";
    const btnS = document.createElement("button");
    btnS.type = "button";
    btnS.className = "mini";
    btnS.textContent = t("chip_singer");
    btnS.addEventListener("click", () => { $("singer").value = c.text; updatePreview(); });
    const btnT = document.createElement("button");
    btnT.type = "button";
    btnT.className = "mini";
    btnT.textContent = t("chip_title");
    btnT.addEventListener("click", () => { $("title").value = c.text; updatePreview(); });
    chip.append(txt, btnS, btnT);
    box.appendChild(chip);
  });
}

function renderWarnings(codes) {
  const box = $("warnings");
  box.innerHTML = "";
  (codes || []).forEach((code) => {
    const key = "warn_" + code.replace(/^warn_/, "");
    const div = document.createElement("div");
    div.textContent = t(key);
    box.appendChild(div);
  });
}

function chipButton(label, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "mini";
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

function renderFrameChips(texts) {
  state._frameChipTexts = texts;
  const box = $("frameChips");
  box.innerHTML = "";
  if (!texts) return;
  if (!texts.length) {
    const d = document.createElement("div");
    d.className = "muted small";
    d.textContent = t("frame_no_text");
    box.appendChild(d);
    return;
  }
  texts.forEach((txt) => {
    const chip = document.createElement("div");
    chip.className = "chip";
    const s = document.createElement("span");
    s.className = "chip-text";
    s.textContent = txt;
    chip.append(
      s,
      chipButton(t("chip_singer"), () => { $("singer").value = txt; updatePreview(); }),
      chipButton(t("chip_title"), () => { $("title").value = txt; updatePreview(); })
    );
    box.appendChild(chip);
  });
}

function updatePreview() {
  const s = $("singer").value.trim() || "?";
  const ti = $("title").value.trim() || "?";
  const l = $("language").value || "?";
  const c = $("category").value || "?";
  $("preview").textContent = s + "-" + ti + "-" + l + "-" + c + state.ext;
}

async function analyze() {
  const picked = state.file || ($("fileInput").files && $("fileInput").files[0]);
  if (!picked) { setStatus(t("no_file"), true); return; }
  state.file = picked;
  setStatus(t("analyzing"));
  $("analyzeBtn").disabled = true;
  try {
    const fd = new FormData();
    fd.append("video", picked, picked.name);
    const res = await fetch("/api/analyze", { method: "POST", body: fd });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));
    state.fileId = data.file_id;
    state.ext = data.ext || "";
    state.candidates = data.candidates || [];
    state.frameTexts = {};
    (data.frame_texts || []).forEach((ft) => {
      state.frameTexts[ft.url] = ft.texts || [];
    });
    renderWarnings(data.warnings);
    $("singer").value = data.singer_guess || "";
    $("title").value = data.title_guess || "";
    $("language").value = data.language_guess || "";
    $("player").src = URL.createObjectURL(picked);
    const fr = $("frames");
    fr.innerHTML = "";
    (data.frames || []).forEach((url) => {
      const img = document.createElement("img");
      img.src = url; img.loading = "lazy"; img.alt = "frame";
      img.className = "thumb";
      img.addEventListener("click", () => renderFrameChips(state.frameTexts[url] || []));
      fr.appendChild(img);
    });
    renderChips();
    renderFrameChips(null);
    updatePreview();
    $("uploadCard").classList.add("hidden");
    $("resultCard").classList.remove("hidden");
    const note = data.language_note ? " (" + data.language_note + ")" : "";
    setStatus(t("ready") + " " + (data.language_guess || "") + note);
  } catch (e) {
    setStatus(t("error") + ": " + e.message, true);
  } finally {
    $("analyzeBtn").disabled = false;
  }
}

async function ocrAt() {
  if (!state.fileId) return;
  const btn = $("ocrAtBtn");
  btn.disabled = true;
  setStatus(t("ocr_at_working"));
  try {
    const seconds = Math.floor($("player").currentTime || 0);
    const res = await fetch("/api/ocr_at", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id: state.fileId, seconds })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));
    state.frameTexts[data.frame_url] = data.texts || [];
    const fr = $("frames");
    const img = document.createElement("img");
    img.src = data.frame_url;
    img.loading = "lazy";
    img.alt = "frame @" + data.seconds + "s";
    img.title = data.seconds + "s";
    img.className = "thumb";
    img.addEventListener("click", () => renderFrameChips(state.frameTexts[data.frame_url] || []));
    fr.appendChild(img);
    renderFrameChips(data.texts || []);
    setStatus(t("ready"));
  } catch (e) {
    setStatus(t("error") + ": " + (e.message || t("ocr_at_failed")), true);
  } finally {
    btn.disabled = false;
  }
}

async function rename() {
  const singer = $("singer").value.trim();
  const title = $("title").value.trim();
  const language = $("language").value;
  const category = $("category").value;
  if (!singer || !title || !language || !category || !state.fileId) {
    setStatus(t("rename_need"), true);
    return;
  }
  setStatus(t("analyzing"));
  try {
    const res = await fetch("/api/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_id: state.fileId, singer, title, language, category })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || ("HTTP " + res.status));
    setStatus(t("renamed_ok") + ": " + data.new_name);
  } catch (e) {
    setStatus(t("error") + ": " + e.message, true);
  }
}

function reset() {
  if ($("player").src && $("player").src.startsWith("blob:")) {
    URL.revokeObjectURL($("player").src);
  }
  state = { fileId: null, ext: "", file: null, candidates: [], frameTexts: {} };
  $("fileInput").value = "";
  $("player").removeAttribute("src");
  $("player").load();
  $("frames").innerHTML = "";
  $("chips").innerHTML = "";
  $("frameChips").innerHTML = "";
  $("warnings").innerHTML = "";
  $("singer").value = "";
  $("title").value = "";
  buildSelects();
  $("preview").textContent = "—";
  setStatus("");
  $("resultCard").classList.add("hidden");
  $("uploadCard").classList.remove("hidden");
}

function init() {
  buildSelects();
  ["singer", "title"].forEach((id) => $(id).addEventListener("input", updatePreview));
  [$("language"), $("category")].forEach((el) => el.addEventListener("change", updatePreview));
  $("langToggle").addEventListener("click", () => setLang(lang === "en" ? "zh" : "en"));
  $("analyzeBtn").addEventListener("click", analyze);
  $("ocrAtBtn").addEventListener("click", ocrAt);
  $("renameBtn").addEventListener("click", rename);
  $("nextBtn").addEventListener("click", reset);

  const dz = $("dropzone");
  const pick = (files) => {
    if (files && files[0]) { state.file = files[0]; analyze(); }
  };
  $("fileInput").addEventListener("change", (e) => {
    if (e.target.files && e.target.files[0]) { state.file = e.target.files[0]; }
  });
  ["dragover", "dragenter"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.add("drag"); }));
  ["dragleave", "drop"].forEach((ev) =>
    dz.addEventListener(ev, (e) => { e.preventDefault(); dz.classList.remove("drag"); }));
  dz.addEventListener("drop", (e) => pick(e.dataTransfer.files));
  dz.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $("fileInput").click(); }
  });

  setLang("en");
  updatePreview();
}

document.addEventListener("DOMContentLoaded", init);
