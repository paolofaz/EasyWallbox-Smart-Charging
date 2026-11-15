# NOTE_SVILUPPO — nuova base stabilizzatore-m1

## 2026-11-15 — Primo core offline puro

### Origine e confini
- Branch `stabilizzatore-m1` creato dal commit iniziale `main` `a5c2d20f24b562542692e92bfac745967e2229d4`, non dal vecchio prototipo.
- Sorgenti progettuali: `03_FONTE_EASYWALLBOX_SMART_STABILIZZATORE_2026-11-14.md`, `EASYWALLBOX_STUDIO_STABILIZZATORE_7SERE_2026-11-14.md` e fonti storiche 02/evcc.
- Nessuna installazione HA, nessun firmware modificato, nessun DPM cambiato, nessun servizio chiamato. v0.1 resta totalmente read-only.

### Modifiche
- Core deterministico `SessionSnapshot`, `HouseSnapshot`, `LimitSnapshot`, `Plan`, `CoreState` e `Proposal`.
- Supervisore `NORMAL/LIMITED`: carico casa senza wallbox; doppia osservazione; cap una sola volta all'innesco; quiete, ripristino diretto e cooldown; veto sulla flessibilità; budget cumulativo.
- Per gestione prudente di dati mancanti, la quiete ricomincia dopo un intervallo non attendibile e il costo energetico del cap viene valutato come **limite superiore** sul tempo trascorso, non come misura AC reale. Nessuna nuova azione su sensore non valido.
- Proprietà simulata distinta da limite ESPHome realmente confermato. Modifica manuale rilevata => ritirare la proposta, senza ripristinare ciecamente.
- Parametri candidati del replay configurabili come oggetto interno di test; nessun pannello di settaggio HA ancora disponibile.

### Test
- **15 test unitari locali superati** in Python, usando `python -m unittest discover -s tests -v`.
- Compresi phon, pausa phon, ferro on/off, lavastoviglie con pausa lunga, cucina, partenza urgente e budget esaurito, lettura non disponibile, gap di trigger, quiete interrotta, manuale/pausa, override, stop/restart, due veicoli ambigui, limite già basso e conferme diverse.
- Nessuna CI né installazione in HA dichiarata verificata finché non risultano prove.

### Osservazioni emerse
- Con SOC congelato troppo a lungo, il planner può perdere il margine e proporre ripristino: in HA servirà il SOC effettivamente aggiornato o un'integrazione prudente dell'energia erogata con provenienza esplicita, senza inventare precisione.
- L'utente conferma che la mancanza di righe negli storici dei due Shelly è dovuta tipicamente a consumo invariato; questa ipotesi è consentita al **replay**. Nell'uso live serve distinguere stabilità da sensore che non comunica.
- Sul ferro di un'ora, il budget può comunque imporre il ripristino prima della quiete: è comportamento deliberato del planner, non un difetto del regolatore.
- La stima di perdita `spent_kwh_upper_bound` sovrastima volutamente il costo della limitazione quando il DPM avrebbe già ridotto la potenza. In futuro confrontare budget prudente e costo modellato con misure Shelly.

### Problemi aperti / prossimo passo
- Taratura non approvata: 1,5/1,0 kW; 10 min; margini cap; 25% del margine; DPM modellato 4,3 kW; soglie per “urgente”.
- Config flow sensori configurabili per altri utenti, adapter HA eventi e qualità dei due Shelly asincroni, lettura SOC/energia, test DST, costo e limiti reale/misurato.
- Confrontare test completi con replay storico 7–13/11 (CSV non disponibili nel repository), workflow CI e installazione HA.
- Definire in versione attuativa una riconciliazione sicura di cap dopo restart/stop, mai con retry ciechi.
- La piattaforma GitHub richiede sempre un branch predefinito; l'accesso GitHub qui non espone un comando per eliminare i branch. La rimozione dei rami storici resta da completare separatamente, senza modificare main nel frattempo.
