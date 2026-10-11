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
    ready: "Ready."
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
    ready: "就緒。"
  }
};

let lang = "en";
let state = { fileId: null, ext: "", file: null, candidates: [] };

const $ = (id) => document.getElementById(id);
const t = (key) => (STR[lang] && STR[lang][key]) || STR.en[key] || key;

function setLang(l) {
  lang = l;
  document.documentElement.lang = l === "zh" ? "zh-Hant" : "en";
  document.querySelectorAll("[data-i18n]").forEach((el) => {
    el.textContent = t(el.dataset.i18n);
  });
  $("langToggle").textContent = l === "en" ? "中文" : "EN";
  renderChips();
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
    $("singer").value = data.singer_guess || "";
    $("title").value = data.title_guess || "";
    if (data.language_guess) $("language").value = data.language_guess;
    $("player").src = URL.createObjectURL(picked);
    const fr = $("frames");
    fr.innerHTML = "";
    (data.frames || []).forEach((url) => {
      const img = document.createElement("img");
      img.src = url; img.loading = "lazy"; img.alt = "frame";
      fr.appendChild(img);
    });
    renderChips();
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
  state = { fileId: null, ext: "", file: null, candidates: [] };
  $("fileInput").value = "";
  $("player").removeAttribute("src");
  $("player").load();
  $("frames").innerHTML = "";
  $("chips").innerHTML = "";
  $("singer").value = "";
  $("title").value = "";
  $("language").selectedIndex = 0;
  $("category").selectedIndex = 0;
  $("preview").textContent = "—";
  setStatus("");
  $("resultCard").classList.add("hidden");
  $("uploadCard").classList.remove("hidden");
}

function init() {
  const langSel = $("language"), catSel = $("category");
  LANGUAGES.forEach((v) => {
    const o = document.createElement("option");
    o.value = v; o.textContent = v;
    langSel.appendChild(o);
  });
  CATEGORIES.forEach((v) => {
    const o = document.createElement("option");
    o.value = v; o.textContent = v;
    catSel.appendChild(o);
  });
  ["singer", "title"].forEach((id) => $(id).addEventListener("input", updatePreview));
  [langSel, catSel].forEach((el) => el.addEventListener("change", updatePreview));
  $("langToggle").addEventListener("click", () => setLang(lang === "en" ? "zh" : "en"));
  $("analyzeBtn").addEventListener("click", analyze);
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
