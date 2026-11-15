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


## 2026-11-15 — M2: prima custom integration HA, ancora NON rilasciata

### Codice aggiunto e ragioni
- `manifest.json` (versione pre-release **0.1.0b1**, non tag/release), `hacs.json`, `const.py`.
- `config_flow.py`: due fasi GUI, entità Shelly/ESPHome selezionabili; profili 1..N auto con SOC, target, capacità utile, potenza prudente, rendimento e partenza feriali/weekend.
- `sources.py`: distingue W/kW, valori invalidi, stringhe `unknown`/`unavailable`, calcolo della partenza in Europe/Rome dal **giorno della partenza**.
- `coordinator.py`: listener eventi HA; i **due Shelly casa** sono ascoltati soltanto quando è attestata la ricarica; timer puntuali per conferma del carico, quiete o budget, niente monitor periodico ogni 2 minuti; non raccoglie né conserva campioni grezzi. Letture identiche non sono trattate come buchi dello storico, ma la validità live richiede stato disponibile e un dato recentemente riportato.
- `sensor.py`: tre sensori virtuali (sessione, piano, stabilizzatore) con attributi esplicativi. Nessun nuovo sensore di potenza duplicato; la pubblicazione è condizionata a differenze nel riepilogo.
- `translations/{it,en}.json`, `docs/LOVELACE.md` con card native e avviso chiarissimo **SIMULAZIONE — NESSUN COMANDO**.
- `brand/icon.png`: immagine quadrata PNG **256×256** in brand locale dell'integrazione, prima diffusione con la prossima release ufficiale autorizzata.
- Modificato `__init__.py` per lifecycle HA e protezione config entry obsolete senza cancellazioni/migrazioni automatiche. Adeguata gestione eccezioni a pattern 2026.11 (errore non recuperabile per vecchia configurazione).

### Verifiche eseguite
- GitHub Actions [M1 offline tests](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43719548835) **success** sulle versioni Python **3.12 e 3.13**: **23 unit test** passati (15 core + 8 sorgenti/safety), compileall di `core.py`.
- I nuovi moduli HA, le traduzioni e `hacs.json` sono stati scritti ma **non è stata ancora eseguita una installazione/registrazione su HA reale**, né un test hassfest/Marketplace. Verifica offline della sintassi Python dei moduli M2 eseguita localmente; non confondere questa prova con il runtime.
- Nessun servizio `hass.services.async_call`, comando BLE/auto, aggiornamento DPM, salvataggio campioni o modifica `.storage`. Nessun commit su main, firmware o branch storici.

### Limitazioni e verifiche prima di v0.1
- L'adapter HA simula il supervisore soltanto **durante una carica già attiva**; planner di avvio/attesa e modalità Manuale/Pausa/Carica subito/override di sessione rimangono da completare. Attualmente `mode=AUTO` è preimpostato nel simulatore HA, non un controllo operativo.
- TTL delle letture Shelly live attualmente prudenziale (20 min) e Shelly EV (5 min): verificare realmente i tempi di aggiornamento e distinguere valore costante da integrazione disconnessa; sincronizzazione tra due Shelly da misurare.
- Lo SOC che aggiorna ogni ~15 min e il budget calcolato dalla stima iniziale non sono ancora calibrati con l'energia EV reale della sessione.
- Non esiste una migrazione provata dalla vecchia `0.0.13`; non installare questa beta sopra l'istanza abituale senza backup e procedura concordata. `ConfigEntryError` segnala esplicitamente l'incompatibilità invece di sovrascrivere vecchie opzioni.
- Da verificare su HA reale: Config Flow, entry/unload, UI Lovelace, nomi entità, assenza scritture per campione nel Recorder, restart, dati indisponibili, confronto replay 7 sere, branding nel Marketplace.
- Alla prossima revisione della fonte 03 aggiungere la milestone M2 verificata e lo SHA prima di chiudere la release; parametri numerici restano candidati.

### Correzione M2 del blocco scadenza (15/11)
- La prima versione dell'adapter ricalcolava la prossima partenza a ogni evento, rischiando di spostare l'obiettivo al giorno seguente dopo una deadline mancata. Corretto: `_active_departure` resta fissata all'interno della sessione fino a disconnessione/cambio auto.
- Aggiunto test statico regressione; 24 test attesi in CI (15 M1 + 9 M2). L'esito va verificato sul nuovo commit prima di dichiararli superati.


## 2026-11-15 — M2 seconda iterazione, planner partenza/attesa (sola simulazione)

### Modifiche effettive
- Nuovo `departure_policy.py`: contratto `DepartureAdvice` (action, reason, latest_safe_start, next_check_at); raccomanda `wait` solo con casa impegnata e slack valido, `start_now` quando è tranquilla o la partenza richiede priorità, `insufficient_data` su fonti inadatte; niente comandi.
- Collegato il planner al `coordinator.py`. Caricamento della casa **solo come snapshot** in attesa; ascolto eventi Shelly casa soltanto in ricarica effettiva. Un timer puntuale rivaluta l'attesa, senza oltrepassare `latest_safe_start`; scadenze puntuali di SOC e potenza EV rendono inattuali gli input anche senza eventi futuri.
- `sensor.py` espone la proposta avvio/attesa e diagnostica `latest_safe_start` / ragione del consiglio nei soli tre sensori già previsti. Nessuna entità di potenza duplicata.
- `OptionsFlowWithReload` secondo API HA 2026.11: scelta del veicolo e modifica di partenza feriale/weekend, target predefinito, potenza sostenibile ed efficienza, senza alterare entity_id originali. Il target letto dall'auto rimane distinto e prevale sul default.
- Aggiunto `strings.json` autorevole in inglese, aggiornate traduzioni IT/EN per il flow.
- Creati `tests/test_departure_policy.py` e `tests/test_m2_contract.py`, includendo casi di arrivo limite, pausa/manuale core, dati mancanti e asset brand.

### Test e verifica
- GitHub Actions **40 test offline passati** su Python 3.12 e 3.13 al 15 novembre; nessun `hassfest` o test runtime HA ancora eseguito. I test contrattuali della GUI sono statici, **non** sostituiscono il click su Home Assistant.
- La politica di attesa contiene un controllo ogni massimo 5 min **solo con auto identificata collegata e attesa giustificata**, non un campionamento in idle. I tempi sono candidati interni, non profilo approvato di produzione.
- Restano non implementati come funzioni operative: modalità sessione Manuale/Pausa, Carica subito, obiettivo temporaneo e riconciliazione del riavvio. `session.mode` resta AUTO nell'adapter, quindi non presentare il suggerimento di avvio come garanzia di rispettare una pausa manuale.
- La precedente config entry 0.0.13 resta intoccata; migrazione e rollback non collaudati. Non rilasciare, non sostituire l'integrazione della casa, non fare merge su main.
- Soglie modello 1,5/1,0 kW, quiete 10 min e budget 25% dello slack **non sono parametri di produzione approvati**.


## 2026-11-15 — M3: macchina di sessione e modalità utente simulate

### Modifiche effettive (branch `stabilizzatore-m1`)
- Nuovo `session_policy.py` **puro**, con per-session `SessionControl(session_id, mode, phase, reason)`. Modi AUTO, MANUAL, PAUSE, CHARGE_NOW; modalità interna RECONCILE per ripristino HA senza prova di intenzione precedente. La fase è un'**osservazione**, non un effetto dedotto dai comandi UI.
- Il primo collegamento dopo un bootstrap HA con auto già collegata entra in **RECONCILE**: nessuna proposta di avvio/cap fino a scelta esplicita. Se HA parte con cavo realmente scollegato e l'auto viene collegata dopo, modalità AUTO di default.
- Manuale e Pausa restano attive per l'intera sessione, non si cancellano con `unknown`, `unavailable` o ritardi di uno dei sensori. Solo uno scollegamento comprovato da wallbox **e** sensori auto chiude la sessione; cambio di veicolo senza disconnessione confermata richiede riconciliazione.
- Opzione Carica subito: override esplicito della sessione che propone un avvio immediato virtuale e disabilita i cap facoltativi; non comanda alcun dispositivo. Una selezione manuale successiva può cambiarla; scollegamento la cancella.
- Modificati `coordinator.py` per riconciliazione delle evidenze di collegamento, `departure_policy.py` per modalità e bilanciamento reale al 100% SOC; `core.py` veto cap per riconciliazione/Carica subito. Il selettore HA `select.py` espone solo le scelte locali; registrato in `PLATFORMS`. Traduzioni IT/EN e `strings.json` aggiornati.
- Il sensore di sessione mostra il **vero stato di ricarica osservato** anche se l'utente ha selezionato PAUSE (simulata); espone modo, fase e ragione. Non scambia un UI toggle per un effetto elettrico.
- Documentato il selettore in `docs/LOVELACE.md` con avvisi inequivocabili.

### Test verificati
- GitHub Actions `M1-M2 offline checks` (nome storico workflow): **74 test** su Python 3.12 e 3.13 superati, inclusi 17 test di dominio sessione, 10 prove dinamiche di coordinator con API HA mock e 2 test del selettore HA mock, oltre ai 45 test preesistenti/potenziati. Eseguiti compileall e controllo JSON.
- La prova dinamica usa stubs locali delle API eventi e non equivale all'esecuzione con Home Assistant reale 2026.11.x; hassfest, Recorder, Config/Options Flow e traduzioni UI non sono ancora collaudati sull'istanza vera.
- Nessun servizio HA invocato per wallbox/auto, nessun BLE, nessun DPM 0 A/Start-Stop, nessun logger di campioni, nessun comando ESPHome. Firmware, main, rami storici e automazioni legacy invariati. Nessun merge, PR, issue o release.

### Limitazioni / prossima verifica
- In v0.1 il modo sessione è **RAM-only**: su riavvio con cavo presente si richiede un'esplicita selezione in RECONCILE, non si pretende di ricordare quale modo fosse selezionato prima. La Pausa non viene convertita automaticamente in Auto dopo il riavvio.
- Il motivo di un arresto fisico non si può desumere unicamente da `charging=False`. Il software deve continuare a distinguere stop manuale, fine auto, target software, cavo staccato e telemetria ignota senza inventare uno stato confermato.
- Non ancora realizzati override temporanei della deadline e modalità speciali con persistenza; nessun controllo attuativo autorizzato.
- Test HA dal vivo e percorso di migrazione con backup della vecchia config entry 0.0.13 restano bloccanti per v0.1. I valori del modello e i limiti non sono tarati per produzione.

## 2026-11-15 — Validazione ufficiale Home Assistant della base M3

- Verificato il branch `stabilizzatore-m1`: la macchina a stati della sessione e il selettore simulato sono già presenti; non duplicati. `session_policy.py` distingue AUTO, MANUAL, PAUSE, CHARGE_NOW, RECONCILE, stato del collegamento e ricarica effettivamente osservata. Il riavvio con auto già collegata richiede nuova conferma; nessun comando reale è inviato.
- Aggiunto `.github/workflows/validate-ha.yml`: `home-assistant/actions/hassfest@master` su push al solo branch di sviluppo, più avvio manuale.
- **Prima esecuzione hassfest fallita** esclusivamente per l'ordine delle chiavi del `manifest.json` (dopo `domain`, `name`, chiavi alfabetiche). Ripristinato l'ordine corretto nel commit `50279602868cf795cf5f64849251bd7c50ffbade`. **Seconda esecuzione hassfest riuscita**: [run 43728553871](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43728553871).
- Aggiunta verifica offline regressione `test_manifest_keys_are_hassfest_ordered` in `tests/test_m2_contract.py`. Rieseguire la CI sull'ultimo commit e riportarne l'esito esatto (la precedente suite contava 74 test).
- HACS/Marketplace action da rimandare finché il default branch contiene solo LICENSE: il validatore HACS consulta il ramo predefinito, quindi una verifica sul ramo di sviluppo darebbe un risultato fuorviante. Non cambiare default/main e non pubblicare release senza consenso.
- **Non equivale a test runtime HA**: sono ancora da verificare su una istanza HA reale Config Flow, Options Flow, select, Recorder e migrazione della vecchia 0.0.13. DPM, ESPHome, automazioni legacy, `main` e altri branch non modificati.

## 2026-11-15 — M3 preflight legacy 0.0.13 e rollback documentato

### Verifica di partenza
- Letti direttamente da GitHub i file attuali su `stabilizzatore-m1` (base HEAD `f57988fd3f077abcc414b09406433bbd544666b6`) e gli schemi storici di `sviluppo-test`/`rifondazione-evcc` manifest `0.0.13`.
- Il Config Flow legacy aveva `VERSION=3` e profili `connected`/`default_target_soc`; il nuovo aveva `VERSION=1` e `cable`/`target_default`: conversione automatica non giustificata e rischiosa.
- Verificati i pattern API HA 2026.11: `async_setup_entry` e `async_unload_entry` possono restituire `None` o generare `ConfigEntryError`; `async_unload_platforms_or_raise` è supportato dalla documentazione ufficiale.

### Sviluppo effettivo
- Nuovo `preflight.py`: pure funzioni `inspect`/`is_legacy` e codici di esito senza dati privati. Blocca valori non validi, sorgenti Shelly duplicate, ruoli errati, automobili ambigue/duplicate e parametri incoerenti; **non** consulta `.storage`, non esegue servizi, non migra.
- `config_flow.py`: `VERSION=3` come legacy, ma riconoscimento **per struttura**; entry esistente (anche priva di `unique_id`) blocca una seconda integrazione; UI rifiuta Shelly duplicati e dati non coerenti senza creare un'entry parziale.
- `__init__.py`: prima di creare listener/timer verifica l'entry; le legacy e quelle incomplete sollevano `ConfigEntryError` con motivi privi di entity_id/nomi privati. Nessun aggiornamento di data/options/versione. Se il setup non completa, i listener allocati sono liberati; unload ora usa `async_unload_platforms_or_raise`.
- Traduzioni IT/EN e `strings.json` aggiornate, `docs/INSTALLAZIONE_PROVA_E_ROLLBACK.md` specifica backup, istanza HA isolata senza dispositivi reali, test e ripristino della directory effettivamente installata. Non installare due versioni nello stesso dominio sulla HA di casa.
- Nuovi test `test_preflight.py` (13) e `test_entry_guard.py` (5) per classificazione old/new, invarianza della vecchia entry e cleanup errori.

### Verifiche concluse e stato
- CI offline (Python 3.12/3.13) con **93 test superati** al commit `d9acca54511de807e97b3a5fe888d443e48334a8` (run [43730371513](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43730371513)); hassfest [43730371551](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43730371551) **superato**. Verificare nuovamente HEAD successivo per documentazione.
- Tutte le prove sui file HA di produzione **non effettuate**: Config Flow reale, test con storici Shelly reali, Backup/Restore, dashboard, Recorder e comportamento su hardware. Nessuna release, main, ESPHome, DPM o automazione Fiat toccati.
- M3 non supporta ancora una conversione guidata `0.0.13 -> 0.1`. Da progettare/approvare esplicitamente solo dopo prove su HA isolata; niente migrazioni cieche. Le impostazioni di M1 del simulatore rimangono candidate, non valori collaudati di produzione.

### Correzione conclusiva della protezione legacy
- Aggiunto controllo preventivo anche a `OptionsFlow` (`async_step_init` e `async_step_vehicle`): una entry storica 0.0.13 o incompleta causa `async_abort(legacy_or_invalid_entry)` prima dell'accesso a campi mancanti. Nessuna modifica di opzioni o configurazione.
- Aggiunte traduzioni IT/EN e controllo regressione statico. Suite salita a **94 test**, superati su Python 3.12/3.13 ([workflow 43730875739](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43730875739)); hassfest ufficiale riuscito sullo stesso commit ([43730875735](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43730875735)). Il test runtime HA resta da eseguire.


## 2026-11-15 — Decisione successiva: reinstallazione pulita confermata

**Nuovo fatto operativo comunicato dall'utente:** la vecchia versione 0.0.13 è stata **completamente rimossa** dalla sua Home Assistant. Non serve migrare alcuna config entry; la nuova versione si installa dall'inizio con Config Flow. Questa decisione sostituisce le raccomandazioni precedenti sul mantenimento della vecchia entry e sul relativo preflight. Non implica che le automazioni Fiat legacy vadano rimosse: rimangono in produzione e non sono state toccate.

### Codice aggiornato (branch `stabilizzatore-m1` soltanto)
- `config_flow.py`: nuova entry schema **VERSION=1**; un solo setup della wallbox e configurazione multi-auto completamente grafica. Controlli per contatori duplicati, auto con sensori ripetuti, orari invalidi e input incompleti.
- `__init__.py`: setup/unload lineare delle piattaforme simulate con gestione errori e rilascio di listener/timer.
- `validation.py`: unico validatore puro per i **nuovi** mapping e le opzioni; nessun accesso alla HA o comandi di dispositivo, nessuna conversione dei formati precedenti.
- Eliminati `preflight.py`, `tests/test_preflight.py`, `tests/test_entry_guard.py` e vecchia guida migrazione. Introdotti `tests/test_validation.py`, `tests/test_fresh_install.py` e `tests/test_clean_config_flow.py` (mock del percorso UI).
- `strings.json` e traduzioni IT/EN corrette per i nuovi errori, README riscritto, nuova guida `docs/INSTALLAZIONE_DA_ZERO.md`.
- Ricontrollato in sola lettura il firmware ESPHome main: gli stati `Car Connected`, `Charging`, `Telemetry Fresh` e lo slider number `Charge power` (kW) sono già previsti, e il limite `Power set` va selezionato fra i sensori della wallbox; non modificato ESPHome.
- Il ramo predefinito `main` non è aggiornato, quindi per il primo test si usa **installazione manuale dal branch di sviluppo**, non HACS/Marketplace; nessuna release.

### Verifiche svolte
- GitHub Actions: **99 test** offline e con HA simulato passati su Python 3.12 e 3.13; Config Flow a due veicoli e Options Flow provati con API fake.
- Hassfest: validazione ufficiale riuscita sul branch aggiornato; compilazione sintattica e traduzioni JSON verificate in CI.
- **NON svolto:** installazione sulla HA reale, interazione con vere entità Shelly/ESPHome/Fiat/Kia, verifica Recorder live e comportamento nella casa. Non presentare questa base come release collaudata.

### Limiti ancora aperti
- v0.1 solo simulazione: nessun comando a wallbox/auto, no BLE aggiuntivo, DPM sempre attivo, automazioni esistenti invariate.
- Dopo restart con auto già collegata, richiesta conferma esplicita della modalità prima di valutare l'automatismo (virtuale).
- Eccezioni temporanee di partenza e taratura budget/soglie restano future attività da approvare/verificare.


## 2026-11-15 — Pubblicata la prima release Marketplace 0.1.0

**Autorizzazione dell'utente:** installazione diretta da Marketplace, ripartenza pulita senza tag/release precedenti; già rimossa la vecchia 0.0.13. L'autorizzazione alla release ha comportato aggiornare `main` con il codice precedentemente verificato (senza modificare firmware, DPM o automazioni HA).

- `manifest.json` versione **0.1.0**, categoria `energy.ev_charging`, `hacs.json` per Home Assistant 2026.11+, BRAND locale incluso.
- Nuova CI `validate-marketplace.yml`: `hacs/action@main` categoria integrazione senza esenzioni; validazione superata sul ramo di sviluppo.
- Nuova CI `publish-v0.1.0.yml`: primo rilascio **una tantum**, vincolato alla stringa di commit `release: publish v0.1.0 to Marketplace`; esegue 99 test Python, hassfest e HACS, poi crea tag + GitHub Release con `gh release create`. I futuri push su main **non** pubblicano automaticamente altre versioni.
- `main` avanzato per fast-forward al commit `2e90c64bbd8f2f2e4eb2174c90ac5ee1b714e9e6`, basato sul tree verificato di `stabilizzatore-m1`; nessun merge PR, nessuna issue.
- **Workflow release [43754953906](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43754953906) concluso SUCCESS**. HACS validation su main [43754953951](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43754953951) SUCCESS.
- Verificato via API GitHub il tag `0.1.0` -> commit `2e90c64`, la release pubblica non draft, non prerelease: [EasyWallbox Smart Charging 0.1.0](https://github.com/paolofaz/EasyWallbox-Smart-Charging/releases/tag/0.1.0).
- Verificati i file al tag: `manifest.json` `version: 0.1.0`, `hacs.json`, PNG BRAND e codice installabile nel percorso `custom_components/easywallbox_smart`.
- **Installazione dell'utente non ancora eseguita**, quindi non dichiarare runtime HA collaudato. Marketplace richiede aggiunta repo tramite **Settings → Marketplace → Add from link**: non è ancora inclusa nel catalogo pubblico.
- La release 0.1.0 resta **solo simulazione, senza nessun comando wallbox/auto**, con DPM originale attivo e automazioni esistenti intatte.

Per i prossimi cambi: operare nuovamente sul branch `stabilizzatore-m1`; ogni futura pubblicazione di `main` richiede nuovo consenso esplicito dell'utente e una nuova release/tag, senza sovrascrivere la 0.1.0.
