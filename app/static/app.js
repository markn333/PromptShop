"use strict";

// ジャンル選択欄で「すべて」「未分類」を表す値（ジャンルの id は 1 以上の数値）
const GENRE_ALL = "all";
const GENRE_NONE = "none";

const DELETE_CONFIRM_MS = 3000;
const SEARCH_DEBOUNCE_MS = 250;
const TOAST_MS = 4000;
const EXCERPT_LENGTH = 80;
const ELAPSED_TICK_MS = 1000;
const COST_DECIMALS = 4;
const KIND_LABEL = { source: "元", result: "結果" };
const RATING_MAX = 5;
// ギャラリーとプロンプトの逆引きで 1 回に取り出す件数（サーバー側の上限と同じ）
const GALLERY_LIMIT = 500;
const FILTER_ALL = "";

const state = {
    summary: null,           // 今月の料金の集計
    gallery: [],             // ギャラリーに表示中の変換結果
    detail: null,            // 詳細表示中の画像と、そこまでの変換の連鎖
    resultTransform: null,   // 変換画面の「比較」に表示中の履歴
    genres: [],
    allPrompts: [],      // 変換画面のプルダウン用（絞り込みなし）
    listPrompts: [],     // プロンプト画面の一覧（絞り込み後）
    selectedPromptId: null,
    providers: [],
    images: [],          // 変換画面で元画像として選べる画像（取り込み済み + 変換結果）
    inputImage: null,    // 変換画面で選択中の元画像
    transforming: false,
    analyzers: [],       // 作風の読み取りに使えるプロバイダー
    draftImage: null,    // 作風の読み取りで選択中のお手本の画像
    draft: null,         // 読み取りでできた下書き（まだプロンプトとして保存していない）
    analyzing: false,
    stripKind: "source",      // 変換画面の、画像を選ぶ列に出す種類（source / result / all）
    draftStripKind: "all",    // 「画像から下書きを作る」の列に出す種類
};

// ---------- 共通の道具 ----------

function $(id) {
    return document.getElementById(id);
}

/**
 * 要素を作る。文字列は必ず textContent 経由で入れ、HTML として解釈させない。
 */
function el(tag, props = {}, ...children) {
    const node = document.createElement(tag);
    Object.assign(node, props);
    for (const child of children) {
        node.append(child);
    }
    return node;
}

function errorMessage(status, data) {
    if (data && typeof data.detail === "string") {
        return data.detail;
    }
    if (status === 422) {
        return "入力内容を確認してください。";
    }
    return `エラーが発生しました（${status}）。`;
}

function api(method, path, body) {
    const options = { method };
    if (body !== undefined) {
        options.headers = { "Content-Type": "application/json" };
        options.body = JSON.stringify(body);
    }
    return request(path, options);
}

async function request(path, options) {
    let response;
    try {
        response = await fetch(path, options);
    } catch (error) {
        throw new Error("サーバーに接続できません。PromptShop が起動しているか確認してください。");
    }
    if (response.status === 204) {
        return null;
    }
    const data = await response.json().catch(() => null);
    if (!response.ok) {
        throw new Error(errorMessage(response.status, data));
    }
    return data;
}

let toastTimer = null;

function showToast(message, isError = false) {
    const toast = $("toast");
    toast.textContent = message;
    toast.classList.toggle("error", isError);
    toast.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toast.hidden = true; }, TOAST_MS);
}

/** 画面操作から呼ぶ非同期処理を包み、失敗を画面に出す。 */
function guarded(action) {
    return async (...args) => {
        try {
            await action(...args);
        } catch (error) {
            showToast(error.message, true);
        }
    };
}

/**
 * 削除ボタンを 2 回押しにする。1 回目で確認表示に変わり、一定時間内の 2 回目で実行する。
 */
function armDelete(button, onConfirm, armedLabel = "もう一度押すと削除") {
    const originalLabel = button.textContent;
    let timer = null;
    const disarm = () => {
        clearTimeout(timer);
        button.classList.remove("armed");
        button.textContent = originalLabel;
    };
    button.addEventListener("click", () => {
        if (button.classList.contains("armed")) {
            disarm();
            onConfirm();
            return;
        }
        button.classList.add("armed");
        button.textContent = armedLabel;
        timer = setTimeout(disarm, DELETE_CONFIRM_MS);
    });
    return disarm;
}

function genreName(genreId) {
    if (genreId === null) {
        return "未分類";
    }
    const genre = state.genres.find((item) => item.id === genreId);
    return genre ? genre.name : "未分類";
}

function money(amount) {
    return `$${amount.toFixed(COST_DECIMALS)}`;
}

function localDateTime(isoText) {
    return new Date(isoText).toLocaleString("ja-JP");
}

function providerLabel(name) {
    const provider = state.providers.find((item) => item.name === name);
    return provider ? provider.label : name;
}

function imageName(image) {
    return image.original_name || `${KIND_LABEL[image.kind]}画像 #${image.id}`;
}

/**
 * 「すべて」と候補からなる選択欄を作り直す。作り直す前の選択が候補に残っていれば選び直す。
 */
function fillFilterSelect(select, items) {
    const previous = select.value;
    select.replaceChildren(el("option", { value: FILTER_ALL, textContent: "すべて" }));
    for (const [value, label] of items) {
        select.append(el("option", { value: String(value), textContent: label }));
    }
    if (Array.from(select.options).some((option) => option.value === previous)) {
        select.value = previous;
    }
}

function excerpt(text) {
    const flat = text.replace(/\s+/g, " ");
    return flat.length > EXCERPT_LENGTH ? `${flat.slice(0, EXCERPT_LENGTH)}…` : flat;
}

/**
 * ジャンル選択欄を作り直す。作り直す前に選ばれていた値が残っていれば選び直す。
 */
function fillGenreSelect(select, leadingOptions) {
    const previous = select.value;
    select.replaceChildren();
    for (const [value, label] of leadingOptions) {
        select.append(el("option", { value, textContent: label }));
    }
    for (const genre of state.genres) {
        select.append(el("option", { value: String(genre.id), textContent: genre.name }));
    }
    const stillExists = Array.from(select.options).some((option) => option.value === previous);
    if (stillExists) {
        select.value = previous;
    }
}

function matchesGenre(prompt, selectValue) {
    if (selectValue === GENRE_ALL) {
        return true;
    }
    if (selectValue === GENRE_NONE) {
        return prompt.genre_id === null;
    }
    return prompt.genre_id === Number(selectValue);
}

// ---------- 画像の拡大表示 ----------

// 画像本体の URL（/api/images/123/file）。これ以外へのリンクは拡大表示の対象にしない
const IMAGE_FILE_PATH = /^\/api\/images\/\d+\/file$/;

/**
 * 画像を、この画面の上に重ねて大きく表示する。
 * 別のタブを開かないのは、専用の窓で動かす版（PromptShop.exe）にはタブがないため。
 */
function openLightbox(fileUrl) {
    $("lightbox-image").src = fileUrl;
    $("lightbox-stage").classList.remove("actual");
    $("lightbox-save").href = `${fileUrl}?download=true`;
    $("lightbox").hidden = false;
    $("lightbox-close").focus();
}

function closeLightbox() {
    $("lightbox").hidden = true;
    $("lightbox-image").removeAttribute("src");
}

function bindLightbox() {
    // 画像本体へのリンクを押したら、別のタブで開く代わりに拡大表示する
    document.addEventListener("click", (event) => {
        const link = event.target.closest ? event.target.closest("a[target='_blank']") : null;
        if (!link || !IMAGE_FILE_PATH.test(link.getAttribute("href") || "")) {
            return;
        }
        event.preventDefault();
        openLightbox(link.getAttribute("href"));
    });
    $("lightbox-close").addEventListener("click", closeLightbox);
    $("lightbox-image").addEventListener("click", () => $("lightbox-stage").classList.toggle("actual"));
    // 画像の外側（余白）を押しても閉じる
    $("lightbox-stage").addEventListener("click", (event) => {
        if (event.target === $("lightbox-stage")) {
            closeLightbox();
        }
    });
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !$("lightbox").hidden) {
            closeLightbox();
        }
    });
}

// ---------- タブ ----------

function switchTab(name) {
    for (const tab of document.querySelectorAll(".tab")) {
        tab.setAttribute("aria-selected", String(tab.dataset.tab === name));
    }
    for (const panel of document.querySelectorAll(".panel")) {
        panel.hidden = panel.id !== `panel-${name}`;
    }
    // 開いたときに最新の内容へ更新する
    if (name === "gallery") {
        guarded(loadGallery)();
    } else if (name === "costs") {
        guarded(loadCosts)();
    } else if (name === "help") {
        guarded(loadAbout)();
    } else if (name === "settings") {
        guarded(loadDataLocation)();
    }
}

// ---------- データの読み込み ----------

function listQuery() {
    const params = new URLSearchParams();
    const genre = $("list-genre").value;
    if (genre === GENRE_NONE) {
        params.set("unclassified", "true");
    } else if (genre !== GENRE_ALL) {
        params.set("genre_id", genre);
    }
    const keyword = $("list-search").value.trim();
    if (keyword) {
        params.set("q", keyword);
    }
    const query = params.toString();
    return query ? `?${query}` : "";
}

async function loadPromptList() {
    state.listPrompts = await api("GET", `/api/prompts${listQuery()}`);
    renderPromptList();
}

async function refreshAll() {
    state.genres = await api("GET", "/api/genres");
    renderGenreSelects();
    renderGenreManager();
    state.allPrompts = await api("GET", "/api/prompts");
    renderTransformPrompts();
    fillFilterSelect($("gallery-prompt"), state.allPrompts.map((prompt) => [prompt.id, prompt.title]));
    await loadPromptList();
    await loadExamples();
}

// ---------- 描画 ----------

function renderGenreSelects() {
    const filterOptions = [[GENRE_ALL, "すべて"], [GENRE_NONE, "未分類"]];
    fillGenreSelect($("transform-genre"), filterOptions);
    fillGenreSelect($("list-genre"), filterOptions);
    fillGenreSelect($("editor-genre"), [[GENRE_NONE, "未分類"]]);
}

function renderPromptList() {
    const list = $("prompt-list");
    list.replaceChildren();
    const count = state.listPrompts.length;
    $("list-count").textContent = count > 0
        ? `${count} 件　押すと、右の欄で編集・削除できます。`
        : "0 件";
    for (const prompt of state.listPrompts) {
        const item = el(
            "button",
            { type: "button", className: "prompt-item", title: "押すと、右の欄で編集・削除できます" },
            el(
                "div",
                { className: "prompt-item-head" },
                el("span", { className: "prompt-item-title", textContent: prompt.title }),
                el("span", { className: "badge", textContent: genreName(prompt.genre_id) }),
                el("span", { className: "prompt-item-edit", textContent: "編集" }),
            ),
            el("div", { className: "prompt-item-body", textContent: excerpt(prompt.body) }),
        );
        item.classList.toggle("selected", prompt.id === state.selectedPromptId);
        item.addEventListener("click", () => {
            openEditor(prompt);
            // 入力欄が画面の外にあるとき（幅の狭い窓など）でも、開いたことが分かるようにする
            $("prompt-form").scrollIntoView({ block: "nearest", behavior: "smooth" });
        });
        list.append(el("li", {}, item));
    }
}

function renderGenreManager() {
    const list = $("genre-list");
    list.replaceChildren();
    // 閉じていても、いくつあるかは見出しの横で分かるようにする
    $("genre-summary").textContent = `${state.genres.length} 件（押すと開閉します）`;
    state.genres.forEach((genre, index) => {
        const nameInput = el("input", { type: "text", value: genre.name, maxLength: 50 });
        nameInput.setAttribute("aria-label", `ジャンル名: ${genre.name}`);
        const rename = el("button", { type: "button", className: "small", textContent: "改名" });
        const up = el("button", { type: "button", className: "small", textContent: "▲", title: "上へ" });
        const down = el("button", { type: "button", className: "small", textContent: "▼", title: "下へ" });
        const remove = el("button", { type: "button", className: "small danger", textContent: "削除" });
        up.disabled = index === 0;
        down.disabled = index === state.genres.length - 1;

        const doRename = guarded(() => renameGenre(genre, nameInput.value));
        rename.addEventListener("click", doRename);
        nameInput.addEventListener("keydown", (event) => {
            if (event.key === "Enter") {
                event.preventDefault();
                doRename();
            }
        });
        up.addEventListener("click", guarded(() => moveGenre(index, -1)));
        down.addEventListener("click", guarded(() => moveGenre(index, 1)));
        armDelete(remove, guarded(() => deleteGenre(genre)));

        list.append(el("li", { className: "genre-row" }, nameInput, rename, up, down, remove));
    });
}

function renderTransformPrompts() {
    const select = $("transform-prompt");
    const previous = select.value;
    const genreValue = $("transform-genre").value;
    const candidates = state.allPrompts.filter((prompt) => matchesGenre(prompt, genreValue));

    select.replaceChildren(el("option", { value: "", textContent: "（選択してください）" }));
    for (const prompt of candidates) {
        select.append(el("option", { value: String(prompt.id), textContent: prompt.title }));
    }
    // 一覧を作り直しても、選択中のプロンプトが候補に残っていれば選択と本文を保つ
    if (candidates.some((prompt) => String(prompt.id) === previous)) {
        select.value = previous;
    }
}

function selectedTransformPrompt() {
    const selectedId = Number($("transform-prompt").value);
    return state.allPrompts.find((item) => item.id === selectedId) || null;
}

function onTransformPromptChange() {
    const prompt = selectedTransformPrompt();
    $("transform-body").value = prompt ? prompt.body : "";
    updateTransformButton();
    guarded(loadExamples)();
}

// ---------- 変換: 作例 ----------

/**
 * 選択中のプロンプトとプロバイダーの作例（ギャラリーで登録した変換結果）をサムネイルで出す。
 * プロンプトを選んでいないとき（本文を直接入力しているとき）は出さない。
 */
async function loadExamples() {
    const prompt = selectedTransformPrompt();
    const providerName = $("transform-provider").value;
    $("examples-block").hidden = !prompt || !providerName;
    if (!prompt || !providerName) {
        return;
    }
    const query = new URLSearchParams({
        kind: "result", example: "true", prompt_id: String(prompt.id), provider: providerName,
        limit: String(GALLERY_LIMIT),
    });
    const images = await api("GET", `/api/images?${query}`);
    // 取り出している間に選択が変わっていたら、古い結果は出さない
    const current = selectedTransformPrompt();
    if (!current || current.id !== prompt.id || $("transform-provider").value !== providerName) {
        return;
    }
    $("examples-heading").textContent = `作例（${prompt.title} / ${providerLabel(providerName)}）`;
    $("examples-hint").textContent = images.length === 0
        ? "まだありません。ギャラリーで「作例に登録」を押した変換結果が、ここに出ます。"
        : `${images.length} 件（クリックで拡大します）`;
    const strip = $("transform-examples");
    strip.replaceChildren();
    for (const image of images) {
        strip.append(el(
            "a",
            { className: "strip-item example-item", href: image.file_url, target: "_blank", rel: "noopener",
              title: "拡大して見る" },
            el("img", { src: image.thumb_url, alt: `作例 #${image.id}`, loading: "lazy" }),
        ));
    }
}

// ---------- 画像を選ぶ列の、種類の切り替え ----------

const STRIP_KIND_ALL = "all";
const STRIP_EMPTY_TEXT = {
    source: "元画像はまだありません。上の枠から取り込めます。",
    result: "変換済みの画像はまだありません。",
    all: "まだ画像がありません。",
};

/** 選んでいる種類の画像だけを返す。 */
function imagesOfKind(kind) {
    return kind === STRIP_KIND_ALL ? state.images : state.images.filter((image) => image.kind === kind);
}

/** 切り替えボタンの見た目を、今選んでいる種類に合わせる。 */
function markStripFilter(groupId, kind) {
    for (const button of $(groupId).querySelectorAll("button")) {
        const active = button.dataset.kind === kind;
        button.classList.toggle("active", active);
        button.setAttribute("aria-pressed", String(active));
    }
}

/** 切り替えボタンが押されたら、状態を変えて列を描き直す。 */
function bindStripFilter(groupId, stateKey, render) {
    for (const button of $(groupId).querySelectorAll("button")) {
        button.addEventListener("click", () => {
            state[stateKey] = button.dataset.kind;
            render();
        });
    }
}

// ---------- 変換: 元画像 ----------

async function loadImages() {
    state.images = await api("GET", "/api/images");
    renderImageStrip();
    renderDraftStrip();
}

function renderImageStrip() {
    const strip = $("image-strip");
    strip.replaceChildren();
    markStripFilter("strip-filter", state.stripKind);
    const images = imagesOfKind(state.stripKind);
    if (images.length === 0) {
        strip.append(el("p", { className: "hint", textContent: STRIP_EMPTY_TEXT[state.stripKind] }));
        return;
    }
    for (const image of images) {
        const label = imageName(image);
        const item = el(
            "button",
            { type: "button", className: "strip-item", title: label },
            el("img", { src: image.thumb_url, alt: label, loading: "lazy" }),
            el("span", { className: "strip-kind", textContent: KIND_LABEL[image.kind] }),
        );
        item.classList.toggle("selected", state.inputImage !== null && state.inputImage.id === image.id);
        item.addEventListener("click", () => selectInput(image));
        strip.append(item);
    }
}

function selectInput(image) {
    state.inputImage = image;
    // 再変換などで、今の切り替えに出ていない種類の画像が選ばれたら、その種類に切り替えて見えるようにする
    if (state.stripKind !== STRIP_KIND_ALL && state.stripKind !== image.kind) {
        state.stripKind = image.kind;
    }
    $("input-preview").src = image.file_url;
    $("input-preview").hidden = false;
    $("drop-hint").hidden = true;
    $("input-name").textContent =
        `${imageName(image)}（${image.width} × ${image.height}）　クリックまたはドロップで差し替え`;
    // 取り込んだ元画像は、ギャラリー（変換結果だけを並べる）に出ないので、ここで削除できるようにする
    const remove = deleteButton(image, "この画像を削除");
    remove.classList.add("small");
    $("input-actions").replaceChildren(remove);
    renderImageStrip();
    updateTransformButton();
}

function clearInput() {
    state.inputImage = null;
    $("input-preview").hidden = true;
    $("input-preview").removeAttribute("src");
    $("drop-hint").hidden = false;
    $("input-name").textContent = "";
    $("input-actions").replaceChildren();
    renderImageStrip();
    updateTransformButton();
}

async function uploadFile(file) {
    if (!file) {
        return;
    }
    const form = new FormData();
    form.append("file", file);
    const image = await request("/api/images", { method: "POST", body: form });
    await loadImages();
    selectInput(image);
}

// ---------- 変換: 実行 ----------

async function loadProviders() {
    state.providers = await api("GET", "/api/providers");
    const select = $("transform-provider");
    const previous = select.value;
    select.replaceChildren();
    for (const provider of state.providers) {
        const suffix = provider.configured ? `（${provider.model}）` : "（API キー未設定）";
        const option = el("option", { value: provider.name, textContent: `${provider.label}${suffix}` });
        option.disabled = !provider.configured;
        select.append(option);
    }
    // API キーを保存・削除して一覧を作り直しても、選んでいたプロバイダーが使える限りそのままにする
    // （知らないうちに既定のプロバイダーへ戻り、意図しない先に課金されるのを防ぐ）
    const preferred = state.providers.find((item) => item.name === previous && item.configured)
        || state.providers.find((item) => item.default && item.configured)
        || state.providers.find((item) => item.configured);
    if (preferred) {
        select.value = preferred.name;
    } else if (select.options.length > 0) {
        // 使えるプロバイダーが 1 つもないときも、欄を空白にせず先頭（キー未設定の表示）を見せる
        select.selectedIndex = 0;
    }
    fillFilterSelect($("gallery-provider"), state.providers.map((item) => [item.name, item.label]));
    updateTransformButton();
    await loadExamples();
}

function selectedProvider() {
    const provider = state.providers.find((item) => item.name === $("transform-provider").value);
    return provider && provider.configured ? provider : null;
}

/** 変換ボタンを押せるかどうかと、押せない理由を画面に反映する。 */
function updateTransformButton() {
    if (state.transforming) {
        return;
    }
    let reason = "";
    if (!selectedProvider()) {
        reason = "API キーが登録されていません。設定タブで登録してください。";
    } else if (!state.inputImage) {
        reason = "元画像を選んでください。";
    } else if (!$("transform-body").value.trim()) {
        reason = "プロンプトを選ぶか、本文を入力してください。";
    }
    $("transform-run").disabled = reason !== "";
    $("transform-status").textContent = reason;
}

function transformPayload() {
    const prompt = selectedTransformPrompt();
    const payload = {
        input_image_id: state.inputImage.id,
        prompt_body: $("transform-body").value,
        provider: $("transform-provider").value,
        keep_aspect: $("transform-keep-aspect").checked,
    };
    if (prompt) {
        payload.prompt_id = prompt.id;
        payload.prompt_title = prompt.title;
    }
    return payload;
}

/**
 * 変換ボタンが押されたとき。今月の合計が予算に達していれば、実行せずに確認を出す。
 */
async function onRunClick() {
    if (state.transforming) {
        return;
    }
    const summary = await loadSummary();
    if (summary.over_budget) {
        $("budget-confirm-text").textContent =
            `今月の合計（概算 ${money(summary.total_usd)}）が、月の予算 ${money(summary.budget_usd)} に達しています。`
            + "変換すると料金がかかります。";
        $("budget-confirm").hidden = false;
        return;
    }
    await runTransform();
}

async function runTransform() {
    $("budget-confirm").hidden = true;
    if (state.transforming) {
        return;
    }
    // 予算の確認を出している間に、元画像の削除などで変換できない状態になっていたら実行しない
    updateTransformButton();
    if ($("transform-run").disabled) {
        return;
    }
    // 二重に送って課金が重ならないよう、応答が返るまでボタンを止める
    state.transforming = true;
    $("transform-run").disabled = true;
    const startedAt = Date.now();
    const showElapsed = () => {
        const seconds = Math.floor((Date.now() - startedAt) / ELAPSED_TICK_MS);
        $("transform-status").textContent = `変換中… ${seconds} 秒（1〜2 分かかることがあります）`;
    };
    showElapsed();
    const timer = setInterval(showElapsed, ELAPSED_TICK_MS);
    try {
        const transform = await api("POST", "/api/transforms", transformPayload());
        renderResult(transform);
        await loadImages();
        await loadSummary();
        showToast(transform.status === "success" ? "変換が完了しました。" : "変換に失敗しました。",
            transform.status !== "success");
    } finally {
        clearInterval(timer);
        state.transforming = false;
        updateTransformButton();
    }
}

function renderResult(transform) {
    state.resultTransform = transform;
    renderResultActions();
    const succeeded = transform.status === "success";
    $("compare-input").src = transform.input_image.file_url;
    $("compare-input-link").href = transform.input_image.file_url;
    $("compare-output").hidden = !succeeded;
    $("compare-error").hidden = succeeded;
    if (succeeded) {
        $("compare-output").src = transform.output_image.file_url;
        $("compare-output-link").href = transform.output_image.file_url;
    } else {
        $("compare-output-link").removeAttribute("href");
        $("compare-error").textContent = `変換に失敗しました: ${transform.error_message}`;
    }
    $("result-meta").textContent = transformMeta(transform).join("　｜　");
    $("result-card").hidden = false;
    $("result-card").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function transformMeta(transform) {
    return [
        `プロンプト: ${transform.prompt_title}`,
        `${providerLabel(transform.provider)} / ${transform.model}`,
        `概算料金: ${money(transform.cost_usd)}`,
        localDateTime(transform.created_at),
    ];
}

/** 変換画面の結果に対する操作（お気に入り・評価・再変換・詳細）。失敗した変換には出さない。 */
function renderResultActions() {
    const output = state.resultTransform ? state.resultTransform.output_image : null;
    const actions = $("result-actions");
    actions.replaceChildren();
    if (!output || output.deleted) {
        return;
    }
    const detail = el("button", { type: "button", textContent: "詳細を開く" });
    detail.addEventListener("click", guarded(() => openDetail(output.id)));
    actions.append(ratingControls(output), exampleButton(output), reuseButton(output), detail);
}

// ---------- 画像への操作（お気に入り・評価・再変換・削除） ----------

/**
 * お気に入り（♥）と評価（★ 1〜5）のボタンを作る。この 2 つは別々に付けられる。
 * 付いている評価の星をもう一度押すと、未評価に戻る。
 */
function ratingControls(image) {
    const favorite = el("button", {
        type: "button",
        className: "icon favorite",
        textContent: image.favorite ? "♥" : "♡",
        title: image.favorite ? "お気に入りを外す" : "お気に入りにする",
    });
    favorite.setAttribute("aria-pressed", String(image.favorite));
    favorite.addEventListener("click", guarded(() => updateImage(image, { favorite: !image.favorite })));

    const box = el("span", { className: "rating" }, favorite);
    for (let value = 1; value <= RATING_MAX; value += 1) {
        const lit = image.rating !== null && value <= image.rating;
        const star = el("button", {
            type: "button",
            className: "icon star",
            textContent: lit ? "★" : "☆",
            title: value === image.rating ? "評価を取り消す" : `評価 ${value}`,
        });
        star.setAttribute("aria-pressed", String(lit));
        const next = value === image.rating ? null : value;
        star.addEventListener("click", guarded(() => updateImage(image, { rating: next })));
        box.append(star);
    }
    return box;
}

/**
 * プロンプトの作例として登録する・外すボタン。
 * 作例にできるのは、保存済みのプロンプトで変換した結果だけ（どのプロンプトの見本かが決まらないため）。
 */
function exampleButton(image) {
    const button = el("button", {
        type: "button",
        className: "example-toggle",
        textContent: image.example ? "作例を解除" : "作例に登録",
    });
    button.setAttribute("aria-pressed", String(image.example));
    const hasPrompt = image.prompt_id !== null;
    if (image.example) {
        button.title = "このプロンプトの作例から外す";
    } else if (hasPrompt) {
        button.title = "変換画面でこのプロンプトとプロバイダーを選んだときに、見本として表示する";
    } else {
        button.title = "作例にできるのは、保存済みのプロンプトで変換した結果だけです（プロンプトが削除された場合も登録できません）";
        button.disabled = true;
    }
    button.addEventListener("click", guarded(async () => {
        await updateImage(image, { example: !image.example });
        showToast(image.example ? "作例から外しました。" : "作例に登録しました。変換画面でこのプロンプトを選ぶと表示されます。");
    }));
    return button;
}

async function updateImage(image, changes) {
    const updated = await api("PATCH", `/api/images/${image.id}`, changes);
    if (state.resultTransform && state.resultTransform.output_image
        && state.resultTransform.output_image.id === updated.id) {
        state.resultTransform.output_image = updated;
        renderResultActions();
    }
    if (state.detail && state.detail.image.id === updated.id) {
        state.detail.image = updated;
        renderDetailActions();
    }
    // 絞り込み中は、変更によって一覧から外れることがあるので取り直す
    await loadGallery();
    await loadExamples();
}

function reuseButton(image) {
    const button = el("button", { type: "button", textContent: "これを元画像にして再変換" });
    button.addEventListener("click", guarded(() => useAsInput(image)));
    return button;
}

async function useAsInput(image) {
    switchTab("transform");
    await loadImages();
    selectInput(image);
    window.scrollTo({ top: 0, behavior: "smooth" });
    showToast("元画像に設定しました。プロンプトを選んで変換してください。");
}

function deleteButton(image, label = "削除") {
    const button = el("button", { type: "button", className: "danger", textContent: label });
    armDelete(button, guarded(() => deleteImage(image)));
    return button;
}

/** 画像を削除し、その画像を表示している場所をすべて最新にする。履歴と料金は残る。 */
async function deleteImage(image) {
    await api("DELETE", `/api/images/${image.id}`);
    if (state.inputImage && state.inputImage.id === image.id) {
        clearInput();
    }
    const shown = state.resultTransform;
    if (shown && [shown.input_image_id, shown.output_image_id].includes(image.id)) {
        state.resultTransform = null;
        $("result-card").hidden = true;
    }
    if (state.detail) {
        if (state.detail.image.id === image.id) {
            closeDetail();
        } else {
            await openDetail(state.detail.image.id);
        }
    }
    await loadImages();
    await loadGallery();
    await loadPromptResults();
    await loadExamples();
    showToast("画像を削除しました。変換の履歴と料金の記録は残ります。");
}

/**
 * 画像の表示枠を作る。削除済みなら、画像の代わりに「削除済み」と出す。
 */
function imageSlot(image, alt) {
    if (image.deleted) {
        return el("div", { className: "deleted-box", textContent: "削除済み" });
    }
    return el(
        "a",
        { href: image.file_url, target: "_blank", rel: "noopener" },
        el("img", { src: image.file_url, alt }),
    );
}

function thumbOrDeleted(image, alt) {
    if (image.deleted) {
        return el("span", { className: "deleted-box small", textContent: "削除済み" });
    }
    return el("img", { src: image.thumb_url, alt, loading: "lazy" });
}

// ---------- ギャラリー ----------

function galleryQuery() {
    const params = new URLSearchParams({ kind: "result", limit: String(GALLERY_LIMIT) });
    if ($("gallery-favorite").checked) {
        params.set("favorite", "true");
    }
    if ($("gallery-example").checked) {
        params.set("example", "true");
    }
    const selects = { min_rating: "gallery-rating", provider: "gallery-provider", prompt_id: "gallery-prompt" };
    for (const [name, id] of Object.entries(selects)) {
        if ($(id).value !== FILTER_ALL) {
            params.set(name, $(id).value);
        }
    }
    return params.toString();
}

async function loadGallery() {
    state.gallery = await api("GET", `/api/images?${galleryQuery()}`);
    renderGallery();
}

function renderGallery() {
    const grid = $("gallery-grid");
    grid.replaceChildren();
    const count = state.gallery.length;
    $("gallery-count").textContent = count >= GALLERY_LIMIT
        ? `新しい順に ${GALLERY_LIMIT} 件まで表示`
        : `${count} 件`;
    if (count === 0) {
        grid.append(el("p", { className: "hint", textContent: "当てはまる変換結果がありません。" }));
        return;
    }
    for (const image of state.gallery) {
        grid.append(galleryCard(image));
    }
}

function galleryCard(image) {
    const open = el(
        "button",
        { type: "button", className: "gallery-thumb", title: "詳細を開く" },
        el("img", { src: image.thumb_url, alt: `変換結果 #${image.id}`, loading: "lazy" }),
    );
    open.addEventListener("click", guarded(() => openDetail(image.id)));
    const reuse = reuseButton(image);
    reuse.textContent = "再変換";
    reuse.title = "これを元画像にして再変換";
    reuse.classList.add("small");
    const remove = deleteButton(image);
    remove.classList.add("small");
    const exampleSmall = exampleButton(image);
    exampleSmall.classList.add("small");
    return el(
        "div",
        { className: "gallery-card" },
        open,
        galleryCaption(image),
        ratingControls(image),
        exampleSmall,
        el("div", { className: "actions" }, reuse, remove),
    );
}

// サムネイルの下に、作ったときのプロンプトのタイトルとプロバイダーを出す。
function galleryCaption(image) {
    const title = image.prompt_title || "";
    const provider = image.provider ? providerLabel(image.provider) : "";
    return el(
        "div",
        { className: "gallery-caption" },
        el("span", { className: "gallery-caption-title", textContent: title, title }),
        el("span", { className: "gallery-caption-provider", textContent: provider }),
    );
}

// ---------- 詳細（左右比較と変換の連鎖） ----------

async function openDetail(imageId) {
    state.detail = await api("GET", `/api/images/${imageId}/chain`);
    switchTab("gallery");
    $("gallery-list-view").hidden = true;
    $("detail-view").hidden = false;
    renderDetail();
    window.scrollTo({ top: 0 });
}

function closeDetail() {
    state.detail = null;
    $("detail-view").hidden = true;
    $("gallery-list-view").hidden = false;
}

function renderDetail() {
    const { image, steps } = state.detail;
    // この画像を作った変換。取り込んだ元画像を開いたときは、ない
    const transform = steps.length > 0 ? steps[steps.length - 1] : null;

    $("detail-input-figure").hidden = transform === null;
    $("detail-prompt").hidden = transform === null;
    $("detail-output-caption").textContent = transform ? "変換結果" : "取り込んだ元画像";
    $("detail-output-slot").replaceChildren(imageSlot(image, transform ? "変換結果" : "元画像"));
    const size = `${image.width} × ${image.height}`;
    if (transform) {
        $("detail-input-slot").replaceChildren(imageSlot(transform.input_image, "入力画像"));
        $("detail-prompt-title").textContent = transform.prompt_title;
        $("detail-prompt-body").textContent = transform.prompt_body;
        $("detail-meta").textContent = [...transformMeta(transform).slice(1), size].join("　｜　");
    } else {
        $("detail-meta").textContent = [imageName(image), localDateTime(image.created_at), size].join("　｜　");
    }
    renderDetailActions();
    renderChain();
}

function renderDetailActions() {
    const { image } = state.detail;
    const actions = $("detail-actions");
    actions.replaceChildren();
    if (image.deleted) {
        actions.append(el("span", { className: "hint", textContent: "この画像は削除済みです。" }));
        return;
    }
    actions.append(ratingControls(image), exampleButton(image), reuseButton(image), deleteButton(image));
}

function chainNode(image, label) {
    const node = el(
        "button",
        { type: "button", className: "chain-node", title: "この画像の詳細を開く" },
        thumbOrDeleted(image, label),
        el("span", { className: "chain-label", textContent: label }),
    );
    node.classList.toggle("current", image.id === state.detail.image.id);
    node.addEventListener("click", guarded(() => openDetail(image.id)));
    return node;
}

function renderChain() {
    const { image, steps } = state.detail;
    const chain = $("detail-chain");
    chain.replaceChildren();
    if (steps.length === 0) {
        chain.append(chainNode(image, "元画像"));
        chain.append(el("p", { className: "hint", textContent: "取り込んだ元画像です。ここから先の変換はありません。" }));
        return;
    }
    chain.append(chainNode(steps[0].input_image, "元画像"));
    steps.forEach((step, index) => {
        chain.append(el(
            "div",
            { className: "chain-arrow" },
            el("span", { className: "chain-prompt", textContent: step.prompt_title }),
            el("span", { textContent: "→" }),
        ));
        chain.append(chainNode(step.output_image, `変換 ${index + 1}`));
    });
}

// ---------- プロンプトからの逆引き ----------

/** 編集中のプロンプトを使った変換結果を一覧する。新規作成中は出さない。 */
async function loadPromptResults() {
    const card = $("prompt-results-card");
    const promptId = state.selectedPromptId;
    card.hidden = promptId === null;
    if (promptId === null) {
        return;
    }
    const images = await api("GET", `/api/images?kind=result&prompt_id=${promptId}&limit=${GALLERY_LIMIT}`);
    // 取り出している間に別のプロンプトへ切り替わっていたら、古い結果は出さない
    if (state.selectedPromptId !== promptId) {
        return;
    }
    $("prompt-results-count").textContent = images.length === 0
        ? "まだありません。削除した画像と、本文を選ばずに直接入力した変換は含みません。"
        : `${images.length} 件（クリックで詳細を開きます）`;
    const strip = $("prompt-results");
    strip.replaceChildren();
    for (const image of images) {
        const item = el(
            "button",
            { type: "button", className: "strip-item", title: "詳細を開く" },
            el("img", { src: image.thumb_url, alt: `変換結果 #${image.id}`, loading: "lazy" }),
        );
        item.addEventListener("click", guarded(() => openDetail(image.id)));
        strip.append(item);
    }
}

// ---------- 料金 ----------

function monthLabel(month) {
    const [year, number] = month.split("-");
    return `${year} 年 ${Number(number)} 月`;
}

function budgetText(summary) {
    if (summary.budget_usd === null) {
        return "";
    }
    return summary.remaining_usd > 0
        ? `予算 ${money(summary.budget_usd)}（残り ${money(summary.remaining_usd)}）`
        : `予算 ${money(summary.budget_usd)} に到達（超過 ${money(-summary.remaining_usd)}）`;
}

/** 今月の集計を取り直し、画面上部の表示を更新する。 */
async function loadSummary() {
    state.summary = await api("GET", "/api/costs/summary");
    const budget = budgetText(state.summary);
    $("month-cost").textContent = `今月の概算: ${money(state.summary.total_usd)}${budget ? `　｜　${budget}` : ""}`;
    $("month-cost").classList.toggle("over", state.summary.over_budget);
    return state.summary;
}

function costRow(name, entry) {
    return el(
        "tr",
        {},
        el("td", { textContent: name }),
        el("td", { className: "num", textContent: String(entry.count) }),
        el("td", { className: "num", textContent: String(entry.failed_count) }),
        el("td", { className: "num", textContent: money(entry.total_usd) }),
    );
}

function fillCostTable(body, rows, emptyText) {
    body.replaceChildren(...rows);
    if (rows.length === 0) {
        const cell = el("td", { className: "hint", textContent: emptyText });
        cell.colSpan = 4;
        body.append(el("tr", {}, cell));
    }
}

async function loadCosts() {
    const summary = await loadSummary();
    const monthly = await api("GET", "/api/costs/monthly");
    $("cost-heading").textContent = `${monthLabel(summary.month)}の使用料金（概算）`;
    $("cost-total").textContent = money(summary.total_usd);
    $("cost-budget-line").textContent = budgetText(summary) || "月の予算は設定されていません。";
    $("cost-budget-line").classList.toggle("over", summary.over_budget);
    $("cost-analysis-line").textContent = summary.analysis_count > 0
        ? `うち作風の読み取り: ${money(summary.analysis_usd)}（${summary.analysis_count} 回）`
        : "";
    fillCostTable(
        $("cost-providers"),
        summary.providers.map((entry) => costRow(entry.label, entry)),
        "今月はまだ使っていません。",
    );
    fillCostTable(
        $("cost-monthly"),
        monthly.map((entry) => costRow(monthLabel(entry.month), entry)),
        "まだ記録がありません。",
    );
    renderFailures(await api("GET", "/api/costs/failures"));
    // 入力中の値を消さないよう、入力欄を触っていないときだけ保存済みの値を入れる
    if (document.activeElement !== $("budget-input")) {
        $("budget-input").value = summary.budget_usd === null ? "" : String(summary.budget_usd);
    }
}

function renderFailures(transforms) {
    const list = $("failed-list");
    list.replaceChildren();
    $("failed-clear").hidden = transforms.length === 0;
    if (transforms.length === 0) {
        list.append(el("li", { className: "hint", textContent: "失敗した変換はありません。" }));
        return;
    }
    for (const transform of transforms) {
        const head = [
            localDateTime(transform.created_at),
            providerLabel(transform.provider),
            `概算料金: ${money(transform.cost_usd)}`,
            `プロンプト: ${transform.prompt_title}`,
        ].join("　｜　");
        list.append(el(
            "li",
            { className: "failed-item" },
            el("div", { className: "hint", textContent: head }),
            el("div", { className: "error-text", textContent: transform.error_message || "理由は記録されていません。" }),
        ));
    }
}

/** 「失敗した変換」の一覧を空にする。料金の記録と回数は変わらない。 */
async function clearFailures() {
    const result = await api("POST", "/api/costs/failures/clear");
    await loadCosts();
    showToast(`失敗した変換 ${result.cleared} 件を一覧から消しました。料金の記録は残っています。`);
}

async function saveBudget(value) {
    await api("PUT", "/api/settings", { monthly_budget_usd: value });
    $("budget-input").blur();
    await loadCosts();
    showToast(value === null ? "月の予算をなしにしました。" : `月の予算を ${money(value)} にしました。`);
}

async function submitBudget() {
    const value = Number($("budget-input").value);
    if (!$("budget-input").value.trim() || !(value > 0)) {
        throw new Error("予算は 0 より大きい金額（USD）で入力してください。");
    }
    await saveBudget(value);
}

// ---------- 設定: データの置き場 ----------

function renderDataLocation(status) {
    $("location-current").textContent = status.current + (status.is_default ? "（既定の場所）" : "");
    $("location-default").textContent = status.default;
    const pending = $("location-pending");
    pending.hidden = status.pending === null;
    pending.textContent = status.pending === null
        ? ""
        : `次に起動したときから「${status.pending}」を使います。アプリを閉じて、もう一度起動してください。`;
    const missing = $("location-missing");
    missing.hidden = status.missing === null;
    missing.textContent = status.missing === null
        ? ""
        : `設定してあった置き場「${status.missing}」が見つからなかったため、今は既定の場所を使っています。`
            + "ドライブがつながっているか確認して、アプリを起動し直してください。";
    $("location-reset").disabled = status.is_default && status.pending === null && status.missing === null;
}

async function loadDataLocation() {
    const status = await api("GET", "/api/data-location");
    renderDataLocation(status);
    return status;
}

async function changeDataLocation() {
    const path = $("location-input").value.trim();
    if (!path) {
        throw new Error("新しい置き場（フォルダーの場所）を入力してください。");
    }
    const status = await api("PUT", "/api/data-location", { path });
    renderDataLocation(status);
    $("location-input").value = "";
    if (status.pending === null) {
        showToast("置き場は今のままです。");
    } else if (status.copied) {
        showToast("今のデータを新しい場所へ写しました。アプリを起動し直すと切り替わります。");
    } else {
        showToast("その場所にあるデータを使います。アプリを起動し直すと切り替わります。");
    }
}

async function resetDataLocation() {
    const status = await api("DELETE", "/api/data-location");
    renderDataLocation(status);
    showToast(status.pending === null
        ? "既定の場所を使います。"
        : "既定の場所に戻しました。アプリを起動し直すと切り替わります。");
}

/** 起動時に、置き場が見つからず既定の場所で動いていることを知らせる。 */
async function warnIfDataLocationMissing() {
    const status = await loadDataLocation();
    if (status.missing !== null) {
        showToast("設定してあったデータの置き場が見つかりません。既定の場所を使っています（「設定」タブを確認してください）。", true);
    }
}

// ---------- ヘルプ（バージョン・ライセンス） ----------

const LICENSE_FULL_URL = "/static/third_party_licenses.txt";
let aboutLoaded = false;

/** ヘルプを最初に開いたときに、バージョンと同梱ソフトの一覧を読み込む。 */
async function loadAbout() {
    if (aboutLoaded) {
        return;
    }
    const info = await api("GET", "/api/about");
    $("about-version").textContent = `${info.name}　バージョン ${info.version}`;
    $("about-copyright").textContent = info.copyright;
    $("about-license").textContent = info.license;
    $("about-data-dir").textContent = info.data_dir;
    $("about-env-file").textContent = info.env_file;
    $("third-party-list").replaceChildren(...info.third_party.map((item) => el(
        "tr",
        {},
        el("td", { textContent: item.name }),
        el("td", { textContent: item.license }),
    )));
    aboutLoaded = true;
}

/** 同梱ソフトのライセンス全文を、押されたときに読み込んで表示する（もう一度押すと隠す）。 */
async function toggleLicenseFull() {
    const box = $("license-full");
    const button = $("license-full-toggle");
    if (!box.hidden) {
        box.hidden = true;
        button.textContent = "ライセンスの全文を表示";
        return;
    }
    if (!box.textContent) {
        $("license-full-status").textContent = "読み込み中…";
        try {
            const response = await fetch(LICENSE_FULL_URL);
            if (!response.ok) {
                throw new Error("ライセンスの全文を読み込めませんでした。");
            }
            box.textContent = await response.text();
        } finally {
            $("license-full-status").textContent = "";
        }
    }
    box.hidden = false;
    button.textContent = "ライセンスの全文を隠す";
}

// ---------- 設定: API キー ----------

async function loadApiKeys() {
    renderApiKeys(await api("GET", "/api/api-keys"));
}

function renderApiKeys(items) {
    const list = $("api-key-list");
    list.replaceChildren();
    for (const item of items) {
        list.append(apiKeyRow(item));
    }
}

function apiKeyStateText(item) {
    if (!item.configured) {
        return "未登録";
    }
    return item.hint ? `登録済み（末尾 ${item.hint}）` : "登録済み";
}

function apiKeyRow(item) {
    const stateLabel = el("span", { className: "api-key-state", textContent: apiKeyStateText(item) });
    stateLabel.classList.toggle("configured", item.configured);

    // type=password で伏せ字にする。new-password は、ブラウザに保存済みパスワードを自動入力させないための指定
    const input = el("input", {
        type: "password",
        autocomplete: "new-password",
        spellcheck: false,
        placeholder: item.configured ? "新しいキーを入力すると置き換えます" : "API キーを貼り付け",
    });
    input.setAttribute("aria-label", `${item.label} の API キー`);
    const save = el("button", { type: "submit", className: "primary", textContent: "保存" });
    const remove = el("button", { type: "button", className: "danger", textContent: "削除" });
    remove.hidden = !item.configured;

    const form = el("form", { className: "api-key-form", autocomplete: "off" }, input, save, remove);
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        guarded(() => saveApiKey(item, input))();
    });
    armDelete(remove, guarded(() => deleteApiKey(item)));

    return el(
        "li",
        { className: "api-key-item" },
        el(
            "div",
            { className: "api-key-head" },
            el("span", { className: "api-key-label", textContent: item.label }),
            stateLabel,
        ),
        form,
    );
}

async function saveApiKey(item, input) {
    const key = input.value.trim();
    if (!key) {
        throw new Error("API キーを入力してください。");
    }
    await api("PUT", `/api/api-keys/${item.provider}`, { key });
    // 入力したキーを画面に残さない
    input.value = "";
    await afterApiKeyChange(`${item.label} の API キーを保存しました。`);
}

async function deleteApiKey(item) {
    await api("DELETE", `/api/api-keys/${item.provider}`);
    await afterApiKeyChange(`${item.label} の API キーを削除しました。`);
}

/** キーの登録状況が変わったら、設定画面と変換画面のプロバイダー欄の両方を最新にする。 */
async function afterApiKeyChange(message) {
    await loadApiKeys();
    await loadProviders();
    await loadAnalyzers();
    showToast(message);
}

// ---------- 画像から作る（作風の読み取り） ----------

async function loadAnalyzers() {
    state.analyzers = await api("GET", "/api/analyzers");
    const select = $("draft-provider");
    const previous = select.value;
    select.replaceChildren();
    for (const analyzer of state.analyzers) {
        const suffix = analyzer.configured ? `（${analyzer.model}）` : "（API キー未設定）";
        const option = el("option", { value: analyzer.name, textContent: `${analyzer.label}${suffix}` });
        option.disabled = !analyzer.configured;
        select.append(option);
    }
    // 一覧を作り直しても、選んでいたプロバイダーが使える限りそのままにする（意図しない先への課金を防ぐ）
    const preferred = state.analyzers.find((item) => item.name === previous && item.configured)
        || state.analyzers.find((item) => item.default && item.configured)
        || state.analyzers.find((item) => item.configured);
    if (preferred) {
        select.value = preferred.name;
    } else if (select.options.length > 0) {
        select.selectedIndex = 0;
    }
    updateDraftButton();
}

function selectedAnalyzer() {
    const analyzer = state.analyzers.find((item) => item.name === $("draft-provider").value);
    return analyzer && analyzer.configured ? analyzer : null;
}

function renderDraftStrip() {
    // 選んでいたお手本が削除されていたら、選択を外す
    if (state.draftImage && !state.images.some((image) => image.id === state.draftImage.id)) {
        state.draftImage = null;
    }
    const strip = $("draft-strip");
    strip.replaceChildren();
    markStripFilter("draft-strip-filter", state.draftStripKind);
    const images = imagesOfKind(state.draftStripKind);
    if (images.length === 0) {
        strip.append(el("p", { className: "hint", textContent: STRIP_EMPTY_TEXT[state.draftStripKind] }));
    }
    for (const image of images) {
        const label = imageName(image);
        const item = el(
            "button",
            { type: "button", className: "strip-item", title: label },
            el("img", { src: image.thumb_url, alt: label, loading: "lazy" }),
            el("span", { className: "strip-kind", textContent: KIND_LABEL[image.kind] }),
        );
        item.classList.toggle("selected", state.draftImage !== null && state.draftImage.id === image.id);
        item.addEventListener("click", () => selectDraftImage(image));
        strip.append(item);
    }
    $("draft-image-name").textContent = state.draftImage
        ? `お手本: ${imageName(state.draftImage)}（${state.draftImage.width} × ${state.draftImage.height}）`
        : "";
    updateDraftButton();
}

function selectDraftImage(image) {
    state.draftImage = image;
    if (state.draftStripKind !== STRIP_KIND_ALL && state.draftStripKind !== image.kind) {
        state.draftStripKind = image.kind;
    }
    renderDraftStrip();
}

async function uploadDraftFile(file) {
    if (!file) {
        return;
    }
    const form = new FormData();
    form.append("file", file);
    const image = await request("/api/images", { method: "POST", body: form });
    await loadImages();
    selectDraftImage(image);
}

/** 「作風を読み取る」を押せるかどうかと、押せない理由を画面に反映する。 */
function updateDraftButton() {
    if (state.analyzing) {
        return;
    }
    let reason = "";
    if (!state.draftImage) {
        reason = "お手本の画像を選んでください。";
    } else if (!selectedAnalyzer()) {
        reason = "API キーが設定されていません。設定タブで登録してください。";
    }
    $("draft-run").disabled = reason !== "";
    $("draft-status").textContent = reason;
}

async function runDraft() {
    if (state.analyzing) {
        return;
    }
    updateDraftButton();
    if ($("draft-run").disabled) {
        return;
    }
    // 二重に送って課金が重ならないよう、応答が返るまでボタンを止める
    state.analyzing = true;
    $("draft-run").disabled = true;
    const startedAt = Date.now();
    const showElapsed = () => {
        const seconds = Math.floor((Date.now() - startedAt) / ELAPSED_TICK_MS);
        $("draft-status").textContent = `読み取り中… ${seconds} 秒（1 分ほどかかることがあります）`;
    };
    showElapsed();
    const timer = setInterval(showElapsed, ELAPSED_TICK_MS);
    try {
        const draft = await api("POST", "/api/analyses", {
            image_id: state.draftImage.id,
            provider: $("draft-provider").value,
            language: $("draft-language").value,
        });
        renderDraft(draft);
        await loadSummary();
        if (draft.status !== "success") {
            showToast("読み取りに失敗しました。", true);
        } else if (editorIsBlankNew()) {
            applyDraft();
        } else {
            showToast("下書きができました。入力欄に書きかけがあるので、まだ入れていません。");
        }
    } finally {
        clearInterval(timer);
        state.analyzing = false;
        updateDraftButton();
    }
}

/**
 * 読み取りの結果を出す。applied が true のとき（下書きを入力欄に入れ終えたとき）は、
 * すぐ下の入力欄と同じ文章を二重に見せないよう、モデルと料金だけを出す。
 */
function renderDraft(draft, applied = false) {
    const succeeded = draft.status === "success";
    state.draft = succeeded ? draft : null;
    $("draft-result").hidden = false;
    $("draft-result").classList.toggle("failed", !succeeded);
    const heading = applied ? "下書きを入力欄に入れました" : "できた下書き（入力欄にはまだ入れていません）";
    $("draft-result-heading").textContent = succeeded ? heading : "読み取りに失敗しました";
    const cost = `概算料金 ${money(draft.cost_usd)}`;
    $("draft-meta").textContent = succeeded
        ? `${providerLabel(draft.provider)} / ${draft.model}　${cost}`
        : `${draft.error_message}（${providerLabel(draft.provider)} / ${draft.model}、${cost}）`;
    $("draft-title").textContent = succeeded ? (draft.title || "（タイトルなし）") : "";
    $("draft-body").textContent = succeeded ? draft.body : "";
    $("draft-preview").hidden = !succeeded || applied;
}

/** 入力欄が「新しいプロンプト」で、まだ何も書かれていないか。 */
function editorIsBlankNew() {
    return state.selectedPromptId === null
        && !$("editor-title").value.trim()
        && !$("editor-body").value.trim();
}

/** 下書きを、新しいプロンプトとして入力欄に入れる（保存はしない）。 */
function applyDraft() {
    if (!state.draft) {
        return;
    }
    openEditor(null);
    $("editor-title").value = state.draft.title;
    $("editor-body").value = state.draft.body;
    renderDraft(state.draft, true);
    $("editor-title").focus();
    showToast("下書きを入力欄に入れました。内容を確かめて「保存」を押してください。");
}

function bindDraftEvents() {
    const fileInput = $("draft-file");
    $("draft-pick").addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
        guarded(uploadDraftFile)(fileInput.files[0]);
        // 同じファイルを続けて選んでも change が起きるように、選択を空に戻す
        fileInput.value = "";
    });
    $("draft-provider").addEventListener("change", updateDraftButton);
    bindStripFilter("draft-strip-filter", "draftStripKind", renderDraftStrip);
    $("draft-run").addEventListener("click", guarded(runDraft));
    $("draft-apply").addEventListener("click", applyDraft);
}

// ---------- プロンプトの編集 ----------

let disarmEditorDelete = () => {};

function openEditor(prompt) {
    disarmEditorDelete();
    state.selectedPromptId = prompt ? prompt.id : null;
    $("editor-heading").textContent = prompt ? "プロンプトの編集" : "新しいプロンプト";
    $("editor-title").value = prompt ? prompt.title : "";
    $("editor-body").value = prompt ? prompt.body : "";
    $("editor-genre").value = prompt && prompt.genre_id !== null ? String(prompt.genre_id) : GENRE_NONE;
    $("editor-delete").hidden = !prompt;
    // 「画像から下書きを作る」は、新しいプロンプトのときだけ出す
    // （編集中に出すと、今のプロンプトの本文を置き換えるように見えてしまうため）
    $("draft-card").hidden = Boolean(prompt);
    renderPromptList();
    guarded(loadPromptResults)();
}

function editorPayload() {
    const genreValue = $("editor-genre").value;
    return {
        title: $("editor-title").value,
        body: $("editor-body").value,
        genre_id: genreValue === GENRE_NONE ? null : Number(genreValue),
    };
}

let savingPrompt = false;

/** 保存ボタンの連打で、同じプロンプトが 2 件登録されないようにする。 */
async function savePrompt() {
    if (savingPrompt) {
        return;
    }
    savingPrompt = true;
    try {
        await savePromptOnce();
    } finally {
        savingPrompt = false;
    }
}

async function savePromptOnce() {
    const payload = editorPayload();
    if (!payload.title.trim() || !payload.body.trim()) {
        throw new Error("タイトルと本文を入力してください。");
    }
    const isNew = state.selectedPromptId === null;
    const saved = isNew
        ? await api("POST", "/api/prompts", payload)
        : await api("PUT", `/api/prompts/${state.selectedPromptId}`, payload);
    state.selectedPromptId = saved.id;
    await refreshAll();
    openEditor(saved);
    // 変換画面でこのプロンプトを選択中なら、表示している本文も保存後の内容に合わせる
    if (Number($("transform-prompt").value) === saved.id) {
        onTransformPromptChange();
    }
    showToast(isNew ? `「${saved.title}」を登録しました。` : `「${saved.title}」を保存しました。`);
}

async function deletePrompt() {
    const title = $("editor-title").value;
    await api("DELETE", `/api/prompts/${state.selectedPromptId}`);
    openEditor(null);
    await refreshAll();
    // 変換画面の本文は入力中かもしれないので触らない（選択欄だけが最新になる）
    updateTransformButton();
    showToast(`「${title}」を削除しました。`);
}

// ---------- ジャンルの管理 ----------

async function addGenre() {
    const input = $("genre-name");
    const name = input.value.trim();
    if (!name) {
        throw new Error("ジャンル名を入力してください。");
    }
    await api("POST", "/api/genres", { name });
    input.value = "";
    await refreshAll();
    showToast(`ジャンル「${name}」を追加しました。`);
}

async function renameGenre(genre, newName) {
    const name = newName.trim();
    if (!name) {
        throw new Error("ジャンル名を入力してください。");
    }
    if (name === genre.name) {
        return;
    }
    await api("PUT", `/api/genres/${genre.id}`, { name });
    await refreshAll();
    showToast(`ジャンル名を「${name}」に変更しました。`);
}

/** 並びを入れ替え、順番が変わったジャンルだけ並び順を保存し直す。 */
async function moveGenre(index, offset) {
    const reordered = state.genres.slice();
    const [moved] = reordered.splice(index, 1);
    reordered.splice(index + offset, 0, moved);
    for (const [position, genre] of reordered.entries()) {
        if (genre.sort_order !== position) {
            await api("PUT", `/api/genres/${genre.id}`, { sort_order: position });
        }
    }
    await refreshAll();
}

async function deleteGenre(genre) {
    await api("DELETE", `/api/genres/${genre.id}`);
    await refreshAll();
    showToast(`ジャンル「${genre.name}」を削除しました。所属していたプロンプトは未分類になります。`);
}

// ---------- 初期化 ----------

function bindEvents() {
    for (const tab of document.querySelectorAll(".tab")) {
        tab.addEventListener("click", () => {
            // タブを押したときは、詳細を閉じて一覧から見せる
            closeDetail();
            switchTab(tab.dataset.tab);
        });
    }

    $("transform-genre").addEventListener("change", () => {
        renderTransformPrompts();
        onTransformPromptChange();
    });
    $("transform-prompt").addEventListener("change", onTransformPromptChange);
    $("transform-body").addEventListener("input", updateTransformButton);
    $("transform-provider").addEventListener("change", () => {
        updateTransformButton();
        guarded(loadExamples)();
    });
    $("transform-run").addEventListener("click", guarded(onRunClick));
    $("budget-confirm-run").addEventListener("click", guarded(runTransform));
    $("budget-confirm-cancel").addEventListener("click", () => { $("budget-confirm").hidden = true; });
    bindDropZone();
    bindStripFilter("strip-filter", "stripKind", renderImageStrip);

    bindGalleryAndCostEvents();

    $("list-genre").addEventListener("change", guarded(loadPromptList));
    let searchTimer = null;
    $("list-search").addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(guarded(loadPromptList), SEARCH_DEBOUNCE_MS);
    });

    $("prompt-new").addEventListener("click", () => {
        openEditor(null);
        $("editor-title").focus();
    });
    $("prompt-form").addEventListener("submit", (event) => {
        event.preventDefault();
        guarded(savePrompt)();
    });
    disarmEditorDelete = armDelete($("editor-delete"), guarded(deletePrompt));

    $("genre-form").addEventListener("submit", (event) => {
        event.preventDefault();
        guarded(addGenre)();
    });
}

function bindGalleryAndCostEvents() {
    for (const id of ["gallery-favorite", "gallery-example", "gallery-rating", "gallery-provider", "gallery-prompt"]) {
        $(id).addEventListener("change", guarded(loadGallery));
    }
    $("detail-back").addEventListener("click", closeDetail);

    $("budget-form").addEventListener("submit", (event) => {
        event.preventDefault();
        guarded(submitBudget)();
    });
    $("budget-clear").addEventListener("click", guarded(() => saveBudget(null)));
    // 押し間違いで消さないよう、削除と同じ 2 回押しにする
    armDelete($("failed-clear"), guarded(clearFailures), "もう一度押すとクリア");
    $("license-full-toggle").addEventListener("click", guarded(toggleLicenseFull));
    $("location-form").addEventListener("submit", (event) => {
        event.preventDefault();
        guarded(changeDataLocation)();
    });
    $("location-reset").addEventListener("click", guarded(resetDataLocation));
}

function bindDropZone() {
    const zone = $("drop-zone");
    const fileInput = $("file-input");
    const upload = guarded(uploadFile);

    zone.addEventListener("click", () => fileInput.click());
    zone.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            fileInput.click();
        }
    });
    fileInput.addEventListener("change", () => {
        upload(fileInput.files[0]);
        // 同じファイルを続けて選んでも change が起きるように、選択を空に戻す
        fileInput.value = "";
    });
    zone.addEventListener("dragover", () => zone.classList.add("dragging"));
    zone.addEventListener("dragleave", () => zone.classList.remove("dragging"));
    zone.addEventListener("drop", (event) => {
        zone.classList.remove("dragging");
        upload(event.dataTransfer.files[0]);
    });
    // ドロップ先を外したときに、ブラウザが画像ファイルそのものを開いて画面が消えるのを防ぐ
    for (const type of ["dragover", "drop"]) {
        window.addEventListener(type, (event) => event.preventDefault());
    }
}

bindEvents();
bindDraftEvents();
bindLightbox();
guarded(refreshAll)();
guarded(loadProviders)();
guarded(loadAnalyzers)();
guarded(loadImages)();
guarded(loadApiKeys)();
guarded(loadSummary)();
guarded(warnIfDataLocationMissing)();
