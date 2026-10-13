/* Wellness app web UI: evening Yes/No review, day timeline, insights. Vanilla JS, no build step. */
(() => {
  const $ = (sel) => document.querySelector(sel);
  const app = $("#app");
  const state = {
    view: "review",
    token: localStorage.getItem("wellness_token") || new URLSearchParams(location.search).get("token") || "",
    date: localDateStr(new Date()),
    day: null,
  };
  if (state.token) localStorage.setItem("wellness_token", state.token);

  function localDateStr(d) {
    const p = (n) => String(n).padStart(2, "0");
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  }
  function shiftDate(s, n) {
    const d = new Date(s + "T00:00:00");
    d.setDate(d.getDate() + n);
    return localDateStr(d);
  }
  function toast(msg) {
    const t = $("#toast");
    t.textContent = msg;
    t.classList.add("show");
    setTimeout(() => t.classList.remove("show"), 1600);
  }
  async function api(path, opts = {}) {
    const res = await fetch("/api" + path, {
      ...opts,
      headers: { "Content-Type": "application/json", "X-Api-Token": state.token, ...(opts.headers || {}) },
    });
    if (res.status === 401) {
      if (state.view !== "settings") { state.view = "settings"; render(); }
      throw new Error("token");
    }
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  }
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  // ------------------------------------------------------------ views
  async function loadDay() {
    state.day = await api(`/days/${state.date}`);
  }

  async function renderReview() {
    $("#dateLabel").textContent = state.date;
    app.innerHTML = `<div class="empty">読み込み中…</div>`;
    try {
      await loadDay();
    } catch (e) {
      app.innerHTML = `<div class="empty">サーバーに接続できません<br><small class="muted">${esc(e.message)}</small></div>`;
      return;
    }
    const d = state.day;
    const cards = d.cards || [];
    if (!cards.length) {
      app.innerHTML = `
        <div class="card">
          <p class="q">まだ今日の推定ができていません</p>
          <p class="ev">収集データ: ${summarizeMetrics(d.metrics)}</p>
          <button class="primary" id="inferBtn">今日を推定する</button>
          <button class="ghost" id="prevBtn">前の日を見る</button>
        </div>`;
      $("#inferBtn").onclick = async () => {
        $("#inferBtn").textContent = "推定中…";
        $("#inferBtn").disabled = true;
        try { await api(`/days/${state.date}/infer`, { method: "POST" }); } catch (e) { toast("失敗: " + e.message); }
        renderReview();
      };
      $("#prevBtn").onclick = () => { state.date = shiftDate(state.date, -1); renderReview(); };
      return;
    }
    const pending = cards.filter((c) => !c.answer);
    const done = cards.filter((c) => c.answer);
    const pct = Math.round((done.length / cards.length) * 100);
    let html = `<div class="progress"><i style="width:${pct}%"></i></div>`;
    if (d.summary) html += `<p class="sub" style="margin:0 0 12px">${esc(d.summary)}</p>`;

    if (pending.length) {
      const c = pending[0];
      const scale = c.kind === "mood";
      html += `
        <div class="card" data-id="${c.id}">
          ${c.time_label ? `<span class="time">${esc(c.time_label)}</span>` : ""}
          <p class="q">${esc(c.question)}</p>
          <p class="ev">${esc(c.evidence?.text || "")} <small class="muted">(確信度 ${Math.round((c.confidence || 0) * 100)}%)</small></p>
          <div class="opts ${scale ? "scale" : ""}">
            ${c.options.map((o) => `<button data-opt="${esc(o)}" class="${o === c.proposed ? "proposed" : ""}">${esc(o)}</button>`).join("")}
          </div>
          <div class="row free">
            <input class="note" id="noteInput" placeholder="選択肢にない答えは自由に入力して送信" enterkeyhint="send" maxlength="300">
            <button id="noteSend" class="send">送信</button>
          </div>
          <p class="ev" style="margin:6px 0 0">選択肢を押すと、入力した文は補足メモとして一緒に保存されます。</p>
        </div>
        <p class="sub" style="text-align:center">残り ${pending.length} 枚</p>`;
    } else {
      html += `
        <div class="card">
          <p class="q">今日の確認は終わりです</p>
          <p class="ev">${done.length}枚に答えました。おつかれさまでした。</p>
          ${d.status !== "reviewed" ? `<button class="primary" id="completeBtn">完了にする</button>` : ""}
          <button class="ghost" id="reinferBtn">推定をやり直す(未回答のみ)</button>
        </div>`;
    }
    if (done.length) {
      html += `<div class="card"><p class="sub" style="margin:0 0 6px">回答済み</p>` +
        done.map((c) => `<div class="done"><span>${esc(c.question)}</span><b>${esc(c.answer)}</b></div>`).join("") + `</div>`;
    }
    html += `<button class="ghost" id="prevBtn">前の日(${shiftDate(state.date, -1)})</button>`;
    app.innerHTML = html;

    const submitAnswer = async (id, answer, note) => {
      try {
        await api(`/cards/${id}/answer`, { method: "POST", body: JSON.stringify({ answer, note }) });
      } catch (e) { toast("保存失敗"); return; }
      renderReview();
    };
    app.querySelectorAll(".opts button").forEach((b) => {
      b.onclick = () => submitAnswer(b.closest(".card").dataset.id, b.dataset.opt, $("#noteInput")?.value?.trim() || null);
    });
    // Free text: the typed sentence becomes the answer itself (e.g. "カレーうどん", "行っていない").
    const sendFree = () => {
      const input = $("#noteInput");
      const text = input?.value?.trim();
      if (!text) { toast("入力してから送信してください"); input?.focus(); return; }
      submitAnswer(input.closest(".card").dataset.id, text, null);
    };
    $("#noteSend") && ($("#noteSend").onclick = sendFree);
    $("#noteInput") && ($("#noteInput").onkeydown = (ev) => { if (ev.key === "Enter") { ev.preventDefault(); sendFree(); } });
    $("#completeBtn") && ($("#completeBtn").onclick = async () => { await api(`/days/${state.date}/complete`, { method: "POST" }); toast("保存しました"); renderReview(); });
    $("#reinferBtn") && ($("#reinferBtn").onclick = async () => { await api(`/days/${state.date}/infer?force=true`, { method: "POST" }); renderReview(); });
    $("#prevBtn").onclick = () => { state.date = shiftDate(state.date, -1); renderReview(); };
  }

  function summarizeMetrics(m = {}) {
    const parts = [];
    if (m.sleep_hours) parts.push(`睡眠 ${Number(m.sleep_hours).toFixed(1)}h`);
    if (m.steps) parts.push(`${m.steps}歩`);
    if (m.payment_count) parts.push(`決済 ${m.payment_count}件`);
    if (m.meeting_count) parts.push(`会議 ${m.meeting_count}件`);
    if (m.screen_minutes) parts.push(`スマホ ${m.screen_minutes}分`);
    return parts.join(" / ") || "まだ届いていません";
  }

  async function renderDay() {
    $("#dateLabel").textContent = state.date;
    app.innerHTML = `<div class="empty">読み込み中…</div>`;
    await loadDay();
    const d = state.day, m = d.metrics || {};
    const tile = (v, l) => `<div class="m"><div class="v">${v ?? "–"}</div><div class="l">${l}</div></div>`;
    let html = `
      <div class="row" style="margin-bottom:12px">
        <button id="dPrev">‹</button><div style="flex:1;text-align:center">${d.date} <small class="muted">${esc(d.status)}${d.backend ? " · " + esc(d.backend) : ""}</small></div><button id="dNext">›</button>
      </div>
      <div class="metrics">
        ${tile(m.sleep_hours != null ? Number(m.sleep_hours).toFixed(1) + "h" : null, "睡眠")}
        ${tile(m.hrv_avg != null ? Math.round(m.hrv_avg) : null, "HRV")}
        ${tile(m.resting_hr ?? null, "安静時心拍")}
        ${tile(m.steps ?? null, "歩数")}
        ${tile(m.exercise_minutes ? m.exercise_minutes + "分" : null, "運動")}
        ${tile(d.condition ?? null, "調子(自己評価)")}
      </div>`;
    if (d.summary) html += `<div class="card"><p style="margin:0">${esc(d.summary)}</p></div>`;
    html += `<div class="card"><p class="sub" style="margin:0 0 6px">タイムライン(推定)</p>`;
    if (d.timeline?.length) {
      html += `<ul class="tl">` + d.timeline.map((t) => `<li><span class="t">${esc(t.time)}${t.end ? "<br>" + esc(t.end) : ""}</span><span class="cat-${esc(t.category)}">${esc(t.label)}<span class="tag">${Math.round((t.confidence || 0) * 100)}%${t.source ? " · " + esc(t.source) : ""}</span></span></li>`).join("") + `</ul>`;
    } else {
      html += `<p class="ev">まだ推定していません。</p><button class="primary" id="inferBtn2">この日を推定する</button>`;
    }
    html += `</div>
      <div class="card"><p class="sub" style="margin:0 0 6px">収集された生データ(AIへの入力)</p><pre>${esc(d.context_text)}</pre></div>`;
    app.innerHTML = html;
    $("#dPrev").onclick = () => { state.date = shiftDate(state.date, -1); renderDay(); };
    $("#dNext").onclick = () => { state.date = shiftDate(state.date, 1); renderDay(); };
    $("#inferBtn2") && ($("#inferBtn2").onclick = async () => { $("#inferBtn2").textContent = "推定中…"; await api(`/days/${state.date}/infer`, { method: "POST" }); renderDay(); });
  }

  async function renderInsights() {
    $("#dateLabel").textContent = "直近28日";
    app.innerHTML = `<div class="empty">読み込み中…</div>`;
    const rows = await api("/insights");
    let html = `<p class="sub" style="margin:0 0 12px">事実と相関だけを出します。「どうすればいい?」は、あなたが聞いたときにだけ答えます。</p>`;
    if (!rows.length) html += `<div class="empty">まだ十分なデータがありません<br><small class="muted">2週間ほど続けると最初の傾向が出ます</small></div>`;
    html += rows.map((r) => `
      <div class="card insight">
        <p class="q" style="font-size:16px">${esc(r.statement)}</p>
        <p class="ev">${esc(r.evidence?.text || "")}</p>
        <div class="c">${r.period_start} 〜 ${r.period_end} · n=${r.n_samples} · 確信度 ${Math.round(r.confidence * 100)}%</div>
      </div>`).join("");
    html += `<button class="ghost" id="genBtn">いま再計算する</button>`;
    app.innerHTML = html;
    $("#genBtn").onclick = async () => { $("#genBtn").textContent = "計算中…"; await api("/insights/generate", { method: "POST" }); renderInsights(); };
  }

  async function renderSettings() {
    $("#dateLabel").textContent = "";
    let status = null;
    try { status = await api("/status"); } catch (_) {}
    app.innerHTML = `
      <div class="card">
        <p class="q">接続</p>
        <div class="row"><input id="tokenInput" type="password" placeholder="APP_TOKEN" value="${esc(state.token)}"><button id="saveToken">保存</button></div>
        <p class="ev" style="margin-top:8px">${status ? `最終受信: ${esc(status.last_ingest_utc || "なし")} (UTC)<br>` + Object.entries(status.event_counts).map(([k, v]) => `${esc(k)}: ${v}`).join(" · ") : "未接続"}</p>
      </div>
      <div class="card">
        <p class="q">朝のひとこと</p>
        <p class="ev">キーボードのマイクで話すだけ。例「わりとすっきり」「頭が重い」</p>
        <div class="row"><input id="noteText" placeholder="今朝の体感"><button id="noteBtn">記録</button></div>
      </div>
      <div class="card">
        <p class="q">いつもの習慣</p>
        <p class="ev">登録しておくと、確認が「はい」1回で済みます。</p>
        <div class="row"><input id="rExercise" placeholder="運動 例: 月水金 朝 筋トレ30分"></div>
        <div class="row" style="margin-top:8px"><input id="rBreakfast" placeholder="朝食 例: コンビニのおにぎりとコーヒー"></div>
        <button class="primary" id="saveRoutines">保存</button>
      </div>
      <div class="card">
        <p class="q">カレンダー</p>
        <button class="ghost" id="calSync">いま同期する</button>
      </div>
      <div class="card">
        <p class="q">覚えている場所</p>
        <p class="ev">自宅は深夜の位置から自動で決まります。それ以外は一度だけカードで聞き、答えを覚えます。</p>
        <div id="placesList" class="ev">読み込み中…</div>
        <button class="ghost" id="detectPlaces">自宅・職場をいま推定し直す</button>
      </div>`;
    try {
      const r = await api("/settings/routines");
      $("#rExercise").value = r.exercise || "";
      $("#rBreakfast").value = r.breakfast || "";
    } catch (_) {}
    const renderPlaces = async () => {
      try {
        const r = await api("/settings/places");
        const items = r.items || [];
        $("#placesList").innerHTML = items.length
          ? items.map((p) => `<div class="done"><span>${esc(p.label)} <small class="muted">${p.source === "auto" ? "自動" : "回答"} · ${Number(p.lat).toFixed(3)},${Number(p.lon).toFixed(3)}</small></span><button class="mini" data-lat="${p.lat}" data-lon="${p.lon}">忘れる</button></div>`).join("")
            + `<p class="ev" style="margin:8px 0 0">店名の照合: ${r.poi_source === "osm" ? `OpenStreetMap (タイル ${r.poi_tiles.length} 枚)` : "オフ"}</p>`
          : "まだありません(位置情報が数日分たまると自宅が決まります)";
        $("#placesList").querySelectorAll("button.mini").forEach((b) => {
          b.onclick = async () => { await api(`/settings/places?lat=${b.dataset.lat}&lon=${b.dataset.lon}`, { method: "DELETE" }); renderPlaces(); };
        });
      } catch (_) { $("#placesList").textContent = "取得できません"; }
    };
    renderPlaces();
    $("#detectPlaces").onclick = async () => { $("#detectPlaces").textContent = "推定中…"; try { await api("/settings/places/detect", { method: "POST" }); } catch (_) {} $("#detectPlaces").textContent = "自宅・職場をいま推定し直す"; renderPlaces(); };
    $("#saveToken").onclick = () => { state.token = $("#tokenInput").value.trim(); localStorage.setItem("wellness_token", state.token); toast("保存しました"); renderSettings(); };
    $("#noteBtn").onclick = async () => { const t = $("#noteText").value.trim(); if (!t) return; await api("/notes", { method: "POST", body: JSON.stringify({ text: t }) }); $("#noteText").value = ""; toast("記録しました"); };
    $("#saveRoutines").onclick = async () => { await api("/settings/routines", { method: "PUT", body: JSON.stringify({ exercise: $("#rExercise").value.trim(), breakfast: $("#rBreakfast").value.trim() }) }); toast("保存しました"); };
    $("#calSync").onclick = async () => { try { const r = await api("/calendar/sync", { method: "POST" }); toast(`取り込み ${r.inserted}件`); } catch (e) { toast("失敗: ICS URL未設定?"); } };
  }

  function render() {
    document.querySelectorAll("nav button").forEach((b) => b.classList.toggle("active", b.dataset.view === state.view));
    ({ review: renderReview, day: renderDay, insights: renderInsights, settings: renderSettings })[state.view]().catch((e) => {
      if (e.message !== "token") app.innerHTML = `<div class="empty">エラー<br><small class="muted">${esc(e.message)}</small></div>`;
    });
  }
  document.querySelectorAll("nav button").forEach((b) => (b.onclick = () => { state.view = b.dataset.view; render(); }));
  render();
})();
