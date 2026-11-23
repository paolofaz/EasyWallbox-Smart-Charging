/* EasyWallbox Smart Charging prior iterations -- user-placeable on-demand paginated history.
 * The card NEVER subscribes to full session arrays, and never writes to EV.
 * The integration registers the JS resource; the user chooses the dashboard.
 */
class EasyWallboxSessionHistoryCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({mode: "open"});
    this._config = null;
    this._ha = null;
    this._offset = 0;
    this._size = 20;
    this._result = null;
    this._pending = false;
    this._error = "";
    this._loaded = false;
  }

  setConfig(config) {
    if (!config || (config.page_size !== undefined &&
        (!Number.isInteger(Number(config.page_size)) ||
         Number(config.page_size) < 1 || Number(config.page_size) > 100))) {
      throw new Error("page_size deve essere un intero tra 1 e 100");
    }
    this._config = config;
    this._size = Number(config.page_size || 20);
    this._offset = 0;
    this._loaded = false;
    this._render();
    if (this._ha) this._fetch();
  }

  set hass(hass) {
    this._ha = hass;
    if (this._config && !this._loaded && !this._pending) this._fetch();
  }

  getCardSize() { return 4; }

  async _fetch() {
    if (!this._config || !this._ha || this._pending) return;
    this._pending = true;
    this._loaded = true;
    this._render();
    try {
      const request = {type: "easywallbox_smart/sessions",
                       offset: this._offset, limit: this._size};
      if (this._config.entry_id) request.entry_id = this._config.entry_id;
      this._result = await this._ha.callWS(request);
      this._error = "";
    } catch (err) {
      this._error = String(err && err.message || err);
    } finally {
      this._pending = false;
      this._render();
    }
  }

  _move(next) {
    this._offset = next;
    this._fetch();
  }

  _render() {
    if (!this._config) return;
    const title = this._config.title || "Storico ricariche";
    const root = this.shadowRoot;
    root.innerHTML = `
      <style>
        ha-card { display: block; }
        .body { padding: 12px 16px 16px; }
        .heading { font-size: 18px; font-weight: 500; padding: 16px 16px 0; }
        .scroll { overflow-x: auto; }
        table { border-collapse: collapse; width: 100%; min-width: 300px; font-size: 14px; }
        th,td { padding: 8px 4px; border-bottom: 1px solid var(--divider-color); text-align: right; }
        th:first-child,td:first-child { text-align: left; }
        th { font-weight: 500; color: var(--secondary-text-color); }
        .footer { display: flex; align-items: center; gap: 8px; margin-top: 12px; justify-content: flex-end; }
        button { font: inherit; color: var(--primary-text-color); background: var(--card-background-color);
          border: 1px solid var(--divider-color); border-radius: 6px; padding: 6px 9px; cursor: pointer; }
        button:disabled { opacity: .45; cursor: default; }
        .message { color: var(--secondary-text-color); padding: 12px 0; }
      </style>
      <ha-card>
        <div class="heading"></div>
        <div class="body">
          <div class="message" id="message"></div>
          <div class="scroll"><table>
            <thead><tr><th>Reset rilevato</th><th>kWh</th><th>Minuti</th></tr></thead>
            <tbody id="rows"></tbody>
          </table></div>
          <div class="footer">
            <span id="paging"></span>
            <button id="prev">Precedenti</button>
            <button id="next">Successive</button>
            <button id="refresh">Aggiorna</button>
          </div>
        </div>
      </ha-card>`;
    root.querySelector(".heading").textContent = title;
    const msg = root.querySelector("#message");
    const data = this._result;
    msg.textContent = this._error ||
      (this._pending ? "Caricamento…" :
       data ? "Sessioni conservate: " + data.count +
              " · totali osservate: " + data.total_observed : "");
    const rows = root.querySelector("#rows");
    if (data && Array.isArray(data.sessions)) {
      for (const s of data.sessions) {
        const tr = document.createElement("tr");
        let stamp = "—";
        try {
          if (s.detected_reset_at)
            stamp = new Intl.DateTimeFormat("it-IT", {
              dateStyle: "short", timeStyle: "short"
            }).format(new Date(s.detected_reset_at));
        } catch (_) { /* invalid timestamp displayed as dash */ }
        for (const value of [stamp, s.energy_kwh, s.duration_min]) {
          const cell = document.createElement("td");
          cell.textContent = String(value ?? "—");
          tr.appendChild(cell);
        }
        rows.appendChild(tr);
      }
      if (!data.sessions.length && !this._error && !this._pending)
        msg.textContent = "Nessuna sessione archiviata.";
    }
    const paging = root.querySelector("#paging");
    paging.textContent = data && data.count ?
      `${this._offset+1}–${Math.min(this._offset+this._size,data.count)} / ${data.count}` : "";
    const prev = root.querySelector("#prev");
    const next = root.querySelector("#next");
    prev.disabled = this._pending || this._offset === 0;
    next.disabled = this._pending || !data || !data.has_more;
    prev.onclick = () => this._move(Math.max(0,this._offset-this._size));
    next.onclick = () => this._move(this._offset+this._size);
    root.querySelector("#refresh").onclick = () => this._fetch();
  }
}
if (!customElements.get("easywallbox-session-history-card")) {
  customElements.define("easywallbox-session-history-card", EasyWallboxSessionHistoryCard);
}
window.customCards = window.customCards || [];
if (!window.customCards.some(x => x.type === "easywallbox-session-history-card")) {
  window.customCards.push({type: "easywallbox-session-history-card",
    name: "EasyWallbox - Storico ricariche",
    description: "Storico paginato caricato su richiesta, senza attributi giganti."});
}
