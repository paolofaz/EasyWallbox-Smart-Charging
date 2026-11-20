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


## 2026-11-15 — M4 in sviluppo: stima automatica potenza e casa universale

### Richiesta dell'utente / revisione requisiti
- Rifiutata la necessità di inserire manualmente una **potenza sostenibile prudente**: con DPM attivo la Fiat/Kia possono assorbire ad es. 2 kW di giorno o 4 kW di sera. La stima deve derivare da dati reali, con provenienza indicata e senza rappresentare come garantita la potenza futura.
- Confermati nel firmware ESPHome main (letto, **non modificato**) i sensori `Session Energy` in kWh da AD p[22] e `Session Duration` in minuti da AD p[23]. Contatori di sessione, non statistiche storiche. Lo Shelly wallbox resta la fonte della potenza attuale.
- Richiesta UI generica: un elenco di **uno o più sensori domestici** da sommare, separando lo Shelly EV; nessun vincolo per piano terra/primo. Chiarire che `target_entity` è un'entità percentuale di target SOC opzionale, solo letta, diversa dal SOC reale; senza entità si usa il target fisso.
- Niente archivio persistente delle ultime 5 sessioni in questa prima fase: complessità e dati non giustificati. Nessun firmware, BLE aggiuntivo o controllo elettrico.

### Modifiche al SOLO ramo di sviluppo
- Nuovo `rate_estimator.py` puro: stima `shelly_instant` mentre carica; dopo almeno 30 minuti e due campioni coerenti crescenti dei contatori ESPHome, media kWh/min combinata come **65% potenza corrente + 35% media sessione**; valori candidati da verificare, non produzione. Resetta alla disconnessione/reset contatori e non usa counters stale o l'attuale setpoint come media reale.
- `coordinator.py`: stima da Shelly e contatori con unità e freschezza verificate; session snapshot alimentata dal valore stimato. I contatori sono ascoltati solo con i normali eventi HA, nessun polling BLE. Ascolto dei sensori casa solo in carica effettivamente confermata; uno o più misuratori da `house_power_sources`.
- `core.py`: `HouseSnapshot.sources_kw` sommabile senza assumere due piani fissi, con retrocompatibilità dei test puri precedenti.
- `config_flow.py`: form multi-selector per consumi domestici; Session Energy/Duration opzionali ma accoppiati; campo di potenza sostenibile rimosso sia dalla configurazione veicolo sia dalle sue opzioni. Nuovo menu Opzioni per cambiare fonti domestiche, contatori, e singolo veicolo. `validation.py` valida il nuovo schema e conserva le entry create con la **0.1.0** (legacy del solo ultimo rilascio, NON 0.0.13), che avevano `house_downstairs` e `house_upstairs`; queste possono essere riconfigurate via Opzioni senza modificare `.storage`.
- `departure_policy.py`: quando non esiste ancora una stima reale, l'assenza di dati **non** autorizza un'attesa: se il SOC è valido suggerisce virtualmente `start_now` per consentire la misurazione. Se ESPHome dichiara `Charging` ma Shelly non conferma potenza, mostra dati insufficienti, senza proporre un nuovo Start.
- `sensor.py`: attributi diagnostici della stima/potenza media/provenienza; aggiornamenti di sintesi soltanto a cambi significativi, non per singolo campione Shelly.
- Traduzioni IT/EN e `strings.json` riformulate per i nuovi campi e target SOC.
- Sviluppo identificato da `manifest.json` **0.2.0b1**: **nessuna pubblicazione**, `main` e la release Marketplace `0.1.0` restano invariati. Non fonderli senza nuova autorizzazione.
- Vedi `docs/STIMA_AUTOMATICA_E_CONSUMI_UNIVERSALI.md`.

### Verifiche e limiti
- Test incrementali aggiunti per power estimation (avvio, 30 min, contatori che si azzerano, dispositivi assenti, cambio sessione), configurazione 1..N sensori casa, Opzioni su config entry 0.1.0, coordinator HA mock e priorità alla sicurezza. CI va verificata sull'ultima HEAD e su Python 3.12/3.13.
- **Non ancora provato su HA reale**: comportamento Session Energy/Duration durante primo avvio, pause e reboot; effettiva validità timestamp, UI grafica multi-selector e Recorder; coefficienti 65/35 da calibrare. La media sessione NON è garanzia che DPM e auto manterranno la stessa potenza.
- Nessun dato di sessione viene scritto in file o `.storage`, nessuna entità di potenza duplicata, nessun servizio wallbox, nessun comando Start/Stop e DPM sempre attivo.


### Verifica CI M4 dopo implementazione e documentazione

- Commit verificato `874dcbb0cb5f58eb1aeeb4a5d730dbf2f58a3849`: [126 test offline con HA simulato su Python 3.12/3.13 — SUCCESS](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43758723542), [hassfest — SUCCESS](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43758723611), [HACS Marketplace validation — SUCCESS](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43758723561).
- Test aggiuntivi su target raggiunto senza velocità osservata, energia residua calcolabile senza stima del tempo, e discordanza tra wallbox `Charging` e potenza Shelly.
- **Nessun test su HA reale eseguito**: la validazione formale non certifica il comportamento dei sensori di sessione in presenza di stop, pausa, DPM o BLE offline.
- Prossima eventuale pubblicazione richiede **autorizzazione esplicita**: `main`, release e tag `0.1.0` sono rimasti invariati; la M4 è soltanto sul branch di sviluppo.


## 2026-11-15 — M4: target SOC esclusivo, scelta da entità HA e test per sabato 21/11

**Decisione dell'utente:** usare preferibilmente le entità di target SOC già presenti in Home Assistant per Fiat 500e e Kia EV3; un singolo target attivo per automobile, senza dover mantenere un valore manuale duplicato. L'utente prevede di non ricaricare l'auto prima di sabato 21 novembre 2026. **Non** svolgere test elettrici anticipati o promettere verifiche in background.

### Implementazione (solo su `stabilizzatore-m1`)

- Nuova costante `target_mode` con due opzioni esclusive: `entity` (predefinita) oppure `fixed`. `config_flow.py` separa i dati auto dalla schermata `target`: compare **solo** l'entità Home Assistant o **solo** il valore fisso, mai entrambi. Stessa struttura nelle Opzioni: possibile passare da fisso a entità o viceversa senza reinstallazione.
- Scelta in italiano/inglese con `SelectSelector` nativo di Home Assistant, `SelectSelectorConfig(translation_key="target_mode")`; traduzioni in `selector.target_mode.options` di `strings.json`, `translations/it.json` e `translations/en.json`. Seguito pattern ufficiale Home Assistant.
- Nuovo `target_policy.py` puro: determina un'unica sorgente effettiva. Se il metodo scelto è `entity`, legge un valore percentuale 1–100% da `sensor`, `number` o `input_number` e **non** applica alcun fallback a `target_default` se la lettura è `unknown`, `unavailable`, invalida o non percentuale. In metodo `fixed` usa soltanto il valore numerico. Nessun comando all'auto.
- Compatibilità con le entry create dalla **0.1.0**: in assenza del nuovo campo, se era stata configurata `target_entity` essa mantiene la precedenza, altrimenti vale `target_default`. Se la 0.1.0 conservava entrambi, l'entità resta prioritaria anche se non disponibile. Nessuna migrazione della vecchia 0.0.13 e nessuna modifica manuale di `.storage`.
- `validation.py`: vieta di salvare entrambi i target nelle nuove schede che dichiarano `target_mode`, e valida anche la configurazione effettiva dopo gli override. `coordinator.py` ascolta gli eventi dell'entità target **effettivamente scelta dalle Opzioni**, non una fonte obsoleta precedentemente salvata.
- Nuovi test puri e fake-HA per transizioni entità/fisso, salvare un solo target, tenere leggibili le entry 0.1.0, valori `unknown` e `unavailable`, percentuale fuori intervallo, unità non percentuale, aggiornamenti dell'entità e listener corretti dopo un cambio nelle Opzioni.
- `docs/CHECKLIST_COLLAUDO_2026-11-21.md` prepara le verifiche **solo in lettura** per il prossimo sabato; nessun test sulla wallbox reale è stato effettuato in questa iterazione.

### Confini

- Il branch è sempre `stabilizzatore-m1`, manifest `0.2.0b1` in sviluppo; `main` e la GitHub Release Marketplace `0.1.0` **restano invariati** fino a nuova autorizzazione esplicita.
- DPM sempre attivo, zero chiamate verso servizi di wallbox/ESPHome/auto; niente modifica alle automazioni Fiat esistenti.
- Test reali del flusso GUI, target SOC, timer, contatori Session Energy/Duration e stima potenza restano **da svolgere** su HA e durante la successiva ricarica ordinaria. Non attribuire validità produttiva ai soli test simulati.


## 2026-11-15 — M4: replay offline pattern ferro da stiro, prima del dato reale

**Contesto:** l'utente riferisce che in casa è in corso una sessione di stiratura e invierà un pattern del ferro. L'auto non dovrebbe essere caricata prima di sabato 21/11. Non sono stati ricevuti campioni reali in questa fase; non attribuire ai dati sintetici un'origine osservata.

- Ho ricontrollato `core.py` e `tests/test_core.py`: esisteva già un caso ferro sintetico con 4 minuti di carico e 4 minuti di pausa, che dimostrava un unico `reduce` senza `restore` durante cicli ravvicinati.
- Aggiunto `tests/household_replay.py`: lettore CSV puramente offline di **potenza casa esclusa EV** con timestamps timezone-aware e qualità del campione. Rifiuta ordinamento temporale errato, misure negative/non finite, unità errate e missing spacciato per zero. `replay_trace` richiama solo `core.evaluate` con una sessione EV **ipotetica** esplicitamente costruita; nessun I/O, comando o polling BLE.
- Aggiunti **10 test** `tests/test_household_replay.py` con carichi sintetici (ferro termostatico, quiete continua, qualità stale/unknown, gap tra campioni, potenza 0 vera, cambio unità W/kW e scenario senza EV). Le soglie di prova non vengono modificate automaticamente dai test.
- **157 test** complessivi Python 3.12/3.13 passati su GitHub Actions al commit `06abbd9a19c0c57b6a373fbb059dfe4fbdf0d45d` (CI [43762858948](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/runs/43762858948)).
- La guida `docs/REPLAY_CARICHI_DOMESTICI.md` spiega screenshot/CSV, unità, quale sensore inviare, e salvaguardia privacy: non committare dati reali domestici sul repository pubblico.
- **Non modificati** algoritmi di protezione DPM, firmware, controller HA, controlli reali, `main` o release Marketplace `0.1.0`; il codice sperimentale è solo `stabilizzatore-m1`.
- **Da fare:** analizzare il pattern reale appena l'utente lo invierà, distinguendo un ramo da totale casa; confrontare la curva con proposte virtuali del core, senza tarare soglie su un solo caso e senza confondere simulazione di auto con auto realmente in carica.


## 2026-11-15 — M4: secondo campione domestico e confronto anti-oscillazione

**Nuovo input ricevuto in chat (non pubblicato):** un secondo tracciato di potenza domestica da un solo ramo, immediatamente successivo al primo. L'utente ha indicato a voce un secondo carico domestico sostanzialmente costante. L'analisi è stata eseguita localmente e **nessun CSV grezzo** contenente orari domestici è stato inviato al repository.

### Diagnosi / nessuna modifica alla policy attiva
- Un carico domestico intermittente può produrre una **potenza totale sostenuta inferiore alla soglia M4 fissa di 1,5 kW**, pur avendo margine ridotto rispetto a un cap richiesto EV di 4 kW su un modello DPM di 4,3 kW. Il regolatore lento allora non propone riduzioni e delega gli adattamenti al DPM.
- Un replay locale delle due tracce concatenate, con 200 W di altri consumi **assunti**, modello DPM 4,3 kW, EV ipotetico 4 kW, target 80%, partenza 07:00, SOC iniziale 70%, mantiene la simulazione in modalità NORMAL durante il secondo episodio. Nessun evento BLE reale è stato generato.
- La sola riduzione della soglia di attivazione a 1,3 kW in un replay **sperimentale** porta a una limitazione virtuale di 2,4 kW; non implica che quel cap sia ottimale né che sia desiderabile in produzione. Con SOC ipotetico 40% e target 80%, il planner non concede margine di sacrificio e non propone la limitazione.
- Sono state aggiunte regressioni **sintetiche, prive di date o tracce private del reale campione**, in `tests/test_hairdryer_candidate.py`: la soglia esistente non riconosce il carico sotto-soglia, una soglia candidata più bassa produce una sola proposta stabile con ampio slack, mentre basso margine e potenza EV non attendibile vietano la riduzione. Il codice `core.py` e la policy attiva **non sono stati modificati**.

### Decisione architetturale ancora da verificare
- Il criterio primario è la **raggiungibilità del target SOC** e poi il compromesso fra energia di ricarica aggiuntivamente sacrificata, frequenza di intervento effettivo del DPM e numero di scritture BLE. Non è giustificato assumere che ogni scrittura BLE provochi usura elettrica rilevante; distinguere comandi al dispositivo, persistenza interna e manovre elettromeccaniche.
- Valutare tre fasce di margine (*ampio, intermedio, scarso/nullo*); mantenere il DPM sempre attivo. Evitare soglie più basse per default senza dati sul reale comportamento della wallbox durante l'episodio.
- Il replay osserva solo potenza domestica: non misura carico del DPM, potenza EV reale né numero di comandi/writes DPM. L'eventuale vantaggio del cap virtuale è quindi un'**ipotesi** da confermare alla prima carica ordinaria.
- Non fare merge, non pubblicare release, non alterare il firmware o le automazioni precedenti.


## 2026-11-15 — M4: prova locale di soglia dinamica per la pressione DPM

**Mandato:** provare in laboratorio la soglia di ingresso dinamica, con tre fasce di margine SOC e costo energetico, senza modificare la versione simulata in esercizio e senza introdurre comandi BLE.

- **Riferimento elettrico modello: DPM confermato 4,4 kW, non 5,2 kW** di tolleranza temporanea del contatore. Pressione modellata: `max(0, casa + limite EV confermato - DPM confermato)`.
- Un nuovo innesco non deriva dal semplice `DPM - EV + 0,2 kW`: serve una **riduzione teorica DPM significativa**, almeno 0,6 kW in fascia ampia / 0,8 kW in fascia intermedia, sostenuta da letture distinte e attendibili per circa 2 / 3 minuti. La fascia urgente o con dati insufficienti vieta nuovi cap opzionali.
- Sperimentate localmente varianti con cap da ultimo campione o massimo degli ultimi 3 minuti, margine prudenziale, quiete diversa, costo energetico massimo per sessione e limite alla frequenza delle proposte. Verificati anche setpoint auto diversi (4,0 e 2,0 kW): una soglia dinamica evita di limitare l'auto quando il DPM dispone già di sufficiente margine.
- Il replay ha evidenziato il **tradeoff non monotono**: ridurre l'energia sacrificata può aumentare i minuti teorici nei quali il DPM deve modulare; ridurre questi ultimi può aumentare le coppie di cambi virtuali. Non dichiarare validata una taratura basata su un solo episodio.
- **15 test sintetici locali passati** della nuova policy candidata: fasce, dati stantii, pressione, setpoint, target urgente, quiete, min-cap, budget, riconciliazione e divieto di nuove azioni in modalità manuale/pausa. Gli script di laboratorio e le tracce private **non sono stati committati**; questi 15 test **non fanno parte della CI GitHub**.
- Aggiunto `docs/STUDIO_SOGLIA_DPM_DINAMICA.md` con formule, ipotesi, criteri e condizioni necessarie per adottare una nuova policy, senza dati grezzi di consumi domestici o informazioni di presenza in casa.
- **Non modificati:** `core.py`, `coordinator.py`, ESPHome, DPM, automazioni Fiat, `main`, release Marketplace `0.1.0`. Il ramo rimane `stabilizzatore-m1` e la versione in sviluppo `0.2.0b1`.
- **Aperto:** servono replay su tracce domestiche ulteriori, confronto su più valori SOC e potenze EV, lettura del limite DPM reale confermato e collaudo di una ricarica ordinaria prima di decidere le soglie. Lo studio delle sette sere è un precedente **storico**, non un test ripetuto della nuova policy senza i relativi CSV grezzi.


## 2026-11-16 — Johnny v1 scelto, implementato e collegato al simulatore

**Richiesta:** terminare la fase di alternative teoriche e consegnare un sistema semplice e testabile. Obiettivi prioritari: target SOC entro partenza, riduzione preventiva *lenta* e stabile durante i consumi domestici intermittenti, pochi cambi di limite virtuali e nessuna sostituzione del DPM. Esclusi orari predefiniti (cucina), device identification, controlli rapidi e rampa a gradini.

**Modifiche concrete nel branch `stabilizzatore-m1`:**
- Creato `custom_components/easywallbox_smart/johnny_policy.py`, riduttore puro, **SIMULAZIONE ONLY**. Tre fasce automatiche da `plan()` (wide >120 min, medium >45 min, urgente / ignoto altrimenti), pressione DPM dinamica `max(0, casa+limite_EV_confermato-limite_DPM)`. Soglie iniziali wide 0,6 kW persistente 120s, medium 0,8 kW persistente 180s, richiedendo report realmente nuovi (non il medesimo campione rivalutato da un timer).
- Una sola proposta di cap per episodio, basata su un quantile alto delle misure recenti, senza micro-regolazioni; minimo 1,4kW e variazione utile >=0,6kW. Ripristino per quiete 18min (wide) o 8min (medium), cooldown 10min. Se target è a rischio o l'energia extra teoricamente sacrificata supera il budget **cumulativo e bloccato** per sessione, ripristino virtuale. Se non ci sono dati coerenti, non iniziare nuovi cap opzionali.
- `coordinator.py` ora invoca **solo** Johnny v1; la funzione `core.evaluate` legacy rimane per il momento **soltanto come regressione offline**, non due supervisori attivi in HA. Aggiunti timestamp composito dei sensori Shelly, non confondere timer con un nuovo campione, e limite DPM osservato.
- `const.py`, `config_flow.py`, `validation.py`, traduzioni IT/EN: sorgente DPM opzionale `dpm_confirmed` (ESPHome `Limit house power set -DPM-` già presente nel firmware), anche modificabile dalle Opzioni. Se selezionata e indisponibile **nessun fallback silenzioso**. Se non configurata, usa il modello numerico della configurazione e lo segnala. Default per nuove configurazioni 4,4kW; i valori già salvati non sono cambiati automaticamente.
- `sensor.py`: negli attributi dello stabilizzatore `margin_band`, `dpm_limit_kw`, `dpm_limit_source` e `estimated_dpm_pressure_kw`, senza nuove entità/Recorder rumoroso.
- Creato `tests/test_johnny_policy.py` (20 test puri) e aggiunti 3 test HA mock, riguardanti sorgente DPM, fallback esplicito, valori `unavailable`, fasce, pressione, persistenza, anti-oscillazione, cap, recupero partenza e spesa energetica conservativa.
- Aggiornati `README.md` e `docs/JOHNNY_V1_POLICY.md`, che espone valori, decisioni, punti da verificare e limiti delle analisi precedenti.

**Validazione:** GitHub Actions **184 test offline** passati su Python 3.12/3.13 (run `43849708285` sul codice collegato prima dell'ultimo aggiornamento README) e validazione hassfest e Marketplace precedentemente verdi sul branch. Ricontrollare la CI dopo questo aggiornamento del diario. I test sono con mock HA, non su un'installazione reale. Pattern del 15/11 privati non inclusi nel repository; studio delle 7 sere è preesistente e **non** una conferma quantitativa della nuova esatta taratura.

**Confini mantenuti:** nessuna scrittura BLE, modifica firmware o wallbox, nessuna modifica al limite fisico DPM, alle automazioni legacy Fiat, a `main` o alla release Marketplace `0.1.0`. Manifest del branch `0.2.0b1` non pubblicato. Le verifiche reali a veicolo collegato restano da svolgere, rispettando il fatto che la prossima ricarica ordinaria è prevista non prima di sabato 21 novembre.


## 2026-11-16 — Johnny v1: replay continuo 7 giorni e nuova taratura quiete

- Ricevuti in chat i due CSV `history-6(1).csv` (sopra) e `history-7(1).csv` (sotto), dati Nov 9–15, 2026. Analisi **solo locale** e riservata; nessun campione domestico o tracciato orario è stato pubblicato sul repository.
- Griglia 1 minuto, 168h, entrambi i Shelly entro 180 secondi: **8.876/10.080 minuti (88,1%)** ricostruibili. Escluse le righe iniziali aggregate, rispettati `unknown`/`unavailable`. Auto ipotetica che richiede 4 kW, DPM fisso modellato a 4,4 kW; **un'unica sessione virtuale**, senza azzeramento giornaliero.
- Per testare entrambe le fasce con “batteria infinita”, il laboratorio mantiene artificialmente sempre wide o medium e **esclude il budget SOC**, pur replicando gli inneschi, il cap virtuale stabile, la quiete, il cooldown e il limite minimo della macchina Johnny v1. I dati NON mostrano che un SOC reale sarebbe rimasto ampio/intermedio per 168h.
- Originale a 180s di freschezza: **wide** conferma 120s/quiete 18min: 53 cambi virtuali, perdita extra contro DPM ideale 48,10 kWh, 196 minuti di forte pressione DPM residua; **medium** conferma 180s/quiete 8min: 62 cambi, 16,39 kWh, 293 minuti residui. DPM-only: 643 min di forte pressione (proxy, non comandi reali).
- Sensibilità quiete: wide 15min **59 cambi, 38,37 kWh, 173min**; medium 10min **61 cambi, 21,26 kWh, 258min**. Scelte di test adottate perché rappresentano un compromesso migliore sui campioni disponibili, senza pretendere ottimalità universale.
- Modificati **soltanto due valori** in `johnny_policy.py`: finestra di quiete wide 18→15min, medium 8→10min; modificato anche il costo minimo di episodio della stessa fascia per coerenza. Invariati 120/180s prima della riduzione, DPM, cap minimo, isteresi, cooldown e convalida dati.
- Aggiunti/aggiornati test `tests/test_johnny_policy.py` per tempi di ripristino 15/10min; aggiornato `docs/JOHNNY_V1_POLICY.md`. Nessun cambio a `main` o firmware e **nessuna scrittura BLE**.
- **Limitazione scoperta:** il costo virtuale di un cap in presenza di letture Shelly mancanti può crescere molto, perché il controllo non usa dati `unknown` per dichiarare quiete. Va progettato e verificato comportamento di gestione telemetria prolungatamente assente, prima di consentire un controllo reale.
- **Da verificare:** nuova CI automatica, collaudo Home Assistant reale e prima sessione EV reale. Non trasferire i numeri delle sette giornate H24 alla carica notturna tipica.


## 2026-11-16 — Verifica aggiuntiva: sette sessioni di carica notturne indipendenti

- Obiettivo: controllare la taratura già introdotta (**fascia ampia conferma 2min/quiete 15min; intermedia conferma 3min/quiete 10min**) in **sette sessioni distinte 18:00–08:00**, anziché in una singola carica virtuale infinita. Nessuna modifica ai limiti reali, al firmware, al DPM o alla policy.
- Replay privato sui due Shelly di casa (escluso il ramo wallbox) per notti 9–15 novembre; 5.316/5.880 minuti validi (**90,4%**) con TTL dei campioni 180 secondi. Nessun CSV grezzo, timeline dei consumi o eventi domestici pubblicati.
- Ipotesi illustrative di Kia EV3 virtuale: EV max 4 kW, DPM ideale 4,4 kW, capacità utilizzabile 77 kWh, rendimento AC 90%, partenza 08:00, target 80%, riserva 30 minuti. SOC ricalcolato dalla potenza EV simulata e riportato al planner circa ogni 15 minuti; potenza sostenibile di piano ipotizzata costante 4 kW. Quando manca un campione, ai fini della raggiungibilità si accredita **zero energia in modo prudenziale**, a Johnny e al DPM-only.
- **Fascia iniziale ampia, SOC 60%→80%**: 14 riduzioni virtuali, 10 ripristini (24 variazioni), 1.045 min totali con cap, 18,08 kWh di energia teoricamente differita durante la limitazione; 7/7 target entro le 08:00, ritardo medio ~47 minuti rispetto al DPM ideale. In **4/7** test il target è raggiunto con cap virtuale ancora attivo: la simulazione si disattiva senza emettere una manovra fisica, ma prima dell'eventuale futuro controllo reale sarà **obbligatoria** una fase di riconciliazione/ripristino sotto ownership e conferma.
- **Fascia iniziale intermedia, SOC 25%→80%**: 7 riduzioni + 7 ripristini, 144 min con cap, 1,18 kWh differiti; 6/7 target entro le 08:00, un caso non dimostrabile anche con solo DPM per dati assenti. Sei ripristini su sette derivano dal budget energetico conservativo anziché dal timer di quiete.
- Sensibilità delle finestre di quiete e conferma: non emergono motivi sufficienti per modificare subito 2/15 (ampio) e 3/10 (intermedio). Le soglie più lente riducono le proposte, ma possono lasciare maggiore pressione teorica al DPM; quiete più lunga con margine intermedio ha peggiorato il numero di target dimostrabili nel replay prudenziale.
- **Limiti metodologici:** controfattuale con DPM istantaneo e ricarica massima assunta 4 kW, non controllo del firmware; il vero estimatore di potenza EV può reagire diversamente alla modulazione, e i buchi storici possono spostare gli orari finali. La replica locale della macchina a stati è stata utilizzata al posto di un test HA con veicolo collegato; i numeri non sono una misura di scritture BLE, manovre del contattore o SOC reale.
- Il test e gli output dettagliati sono conservati in chat **fuori dal repository pubblico**. Risultato: policy invariata sul branch di sviluppo, non pronta per il controllo reale senza gestione dell'uscita dalla sessione e della perdita telemetria.


## 2026-11-16 — Johnny v1: chiusura dei due casi bloccanti simulati

**Mandato:** dopo il replay 7 notti, gestire il cap virtuale che rimane aperto a fine carica e la telemetria domestica assente a lungo, senza modificare le tarature 2/15 e 3/10, senza toccare wallbox o DPM reale.

### Implementato su `stabilizzatore-m1`

1. In `johnny_policy.py` la fine di carica con veicolo identificato, intent AUTO, wallbox `Charging = OFF`, `Telemetry Fresh = ON` e limiti coerenti emette una **singola proposta virtuale `restore`** del cap originale; anche `target_reached` e `CHARGE_NOW` producono un motivo diagnostico esplicito. La proposta **non è un comando e non prova l'effetto elettrico**.
2. Se la sessione cambia, il cavo si scollega, l'utente assume proprietà Manuale/Pausa, c'è contraddizione (Shelly EV a zero ma wallbox ancora `Charging = ON`), manca la freschezza della telemetria o cambiano limiti/DPM, Johnny **non propone ripristini automatici alla cieca**: ritorna `retire` con motivo di riconciliazione. Nessun retry.
3. `coordinator._make_session` non cancella più `self.state` prima che il riduttore osservi un distacco verificato o un cambio veicolo: lo stato e la proprietà dell'episodio precedente vengono chiusi nella transizione pura, **mai trasferiti alla nuova sessione**.
4. In caso di Shelly indisponibile o obsoleto, il conteggio della quiete viene annullato. Un cap virtuale ancora attivo viene proposto per ripristino dopo **8 minuti dall'ultimo report DOMESTICO attendibile**, non al primo campione mancante. Il coordinatore HA programma la verifica alla scadenza delle letture (3min) e della soglia di recupero (8min), senza polling continuo. Se i limiti o la sessione non sono verificati, vale la riconciliazione.
5. `core.SessionSnapshot` include l'attributo opzionale `wallbox_telemetry_fresh`; `coordinator.py` lo ricava dal sensore esistente; nessuna entità nuova. `sensor.py` rende visibili `last_virtual_transition_reason`, `last_virtual_transition_at` e `last_trusted_house_report`, senza falsificare un riscontro BLE. Le transizioni diagnostiche restano leggibili anche dopo `inactive` all'interno della stessa sessione.

**Regressioni introdotte:** carica terminata con wallbox+telemetria coerenti; target raggiunto ancora in carica; Carica subito; pausa/manuale; nuovo veicolo; cavo scollegato; sensori contraddittori; vecchio `Charging=OFF` non fresco; mancanza DPM o limiti; Shelly unknown breve vs perdita oltre 8 minuti; timer di scadenza Shelly senza nuovi eventi HA; cooldown dopo ripristino. Test isolati Python e adapter HA mock; verifiche CI al commit finale.

**Nessuna modifica** a `main`, versione Marketplace `0.1.0`, firmware ESPHome, limite DPM, automazioni Fiat, orari/target o taratura Johnny. Nessuna scrittura BLE o cambio reale della wallbox. **Ancora da verificare in HA reale:** aggiornata installazione di test, osservabilità di `Telemetry Fresh` e `Charging` durante fine carica e DPM-paused, comportamento allo stop/cambio cavo, conferma dei tempi, persistenza del report e rollover di sessione al riavvio. Il passaggio futuro ai comandi supervisionati richiede esplicita autorizzazione e riconciliazione richiesta/conferma/effetto.


## 2026-11-16 — Finestra mobile 5 minuti, carichi intermittenti e DPM=0

**Richiesta dell'utente:** riconoscere carichi con cicli ON/OFF più brevi dei 2/3 minuti di conferma, senza inseguire picchi, dopo confronto su 7 giorni/7 notti; inoltre gestire `sensor.wallbox_limit_house_power_set_dpm=0` quando la ricarica è messa in pausa e preparare architettura di avvio differito, cap sessione, manuale/automatico e Lovelace.

**Evidenza offline privata precedente all'implementazione:** 7 giorni con 8.876 minuti validi su 10.080, DPM ipotetico 4,4kW, EV 4kW, scenario batteria infinita per la sola prova sensibilità. Ampio: 59 cambi sia senza sia con memoria; pressione forte modellata 174→173min. Intermedio: 61→63 cambi, pressione forte 259→250min, energia differita +0,64 kWh. Ricariche notturne 18–08 con SOC sintetici e budget: la variante selezionata non peggiorava il target (7/7 ampio, 6/7 intermedio; nel caso insufficiente mancano minuti di misura). Sintetici 30/60/75s e fasi diverse: recupero cicli 60s ON/60s OFF, niente interventi per picco isolato 110s o oscillazioni marginali. Si tratta di replay controfattuale, non validazione su wallbox fisica né conteggio BLE.

**Codice implementato e collegato in `stabilizzatore-m1`:**
- `johnny_policy.py`: nuova via rolling **5 minuti** oltre alla conferma continua preesistente di 120/180 secondi; almeno due burst, due minuti alti di intervalli comprovati con gap tra campioni <=150s, pressione integrata >=2,4/3,2kW·min, e lettura nuova/attualmente alta; niente memoria durante gap lunghi, dopo cooldown e fra sessioni. Quiete 15/10min e cooldown 10min invariati. Il cap forte viene limitato a minimo EV 1,4kW e il DPM resta esclusivo sulle modulazioni ulteriori.
- DPM osservato = **0**: nessuna proposta di riduzione, nessun riavvio; reason `dpm_zero_paused_or_unresolved`, oppure `dpm_zero_requires_reconciliation` se un cap virtuale era attivo. `None` resta distinto da `0`. `coordinator.py` in AUTO collegata ma non in carica mostra `dpm_zero_pause_origin_unverified` e non propone `start_now` soltanto perché il planner ritiene disponibile un margine. Un DPM positivo confermato, compreso **4,8kW**, viene letto dinamicamente senza forzare il valore storico 4,4.
- Test di regressione aggiunti a `tests/test_johnny_policy.py` e `tests/test_coordinator_session_smoke.py`: cicli continui e intermittenti su entrambe le fasce, singolo 110s, oscillazioni, campione duplicato, gap >150s, potenze domestiche 3kW, DPM0, change while limited e Auto/Manuale/Pausa; controllo DPM4.8.
- Aggiornati README e `docs/JOHNNY_V1_POLICY.md` con dati di confronto, limiti e decisioni di architettura.

**Proposte dell'utente registrate ma NON ancora implementate:** `not_before` per singola sessione (es. 16→18), `max_ev_kw` come limite massimo EV della sessione (es. 3,8kW), dashboard Lovelace condizionale Manuale/Automatica con pulsanti Carica subito/Pausa/Riprendi, SOC target e avviso di irraggiungibilità. Richiedono in fase futura ownership unica, logica di riconciliazione origine pausa (manuale/Johnny/ignoto), memorizzazione sicura ultimo DPM positivo confermato, conferme BLE e distacco automazioni legacy concorrenti. STOP nativo problematico: evitare sostituzioni senza collaudo. **Non introdurre nessun comando reale in questa fase.** Aggiornare la fonte principale quando tali proposte saranno approvate.

**Sicurezza:** nessuna modifica firmware EasyWallbox/ESPHome, DPM fisico, automazioni legacy, main, release Marketplace o servizi HA. Analisi e CSV privati non sono stati committati. Test CI finali e HACS da verificare all'ultimo commit; collaudo con auto reale ancora necessario.


## 2026-11-16 — Field-test `0.2.0b2`: due Johnny virtuali e registri JSONL

**Richiesta approvata dall'utente:** potenza iniziale EV e massimo ordinario configurabili; una versione test con due Johnny in parallelo (wide / medium) alimentati solo dai consumi veri Shelly, auto perennemente in carica virtualmente, nessun comando reale, file di log da analizzare dopo qualche giorno.

### Implementazione su `stabilizzatore-m1`

- `const.py`, `validation.py`, `config_flow.py`: valori iniziali predefiniti **3,6 kW** e **4,0 kW**, configurabili da Config Flow e Opzioni, step 0,2 kW, gamma 1,4–6 kW, iniziale <= massima. Nuova voce Opzioni **Field test a due scenari**, attivabile esplicitamente (default **OFF**, reload automatico).
- `shadow_lab.py` puro: due `SessionSnapshot` *synthetic* indipendenti, senza usare stato di carica, SOC, cavo o limiti reali delle auto. Slack di riferimento artificiale **180 min wide / 90 min medium**, continuamente mantenuto con partenza mobile. Baseline EV sempre = massimo ordinario configurato, non implementa nuova rampa; il valore iniziale è memorizzato per il futuro controllo sessione. Budget virtuale impostato convenzionalmente molto ampio **solo per questa prova infinita**: ciò evita che in una sessione di giorni la policy smetta di agire dopo poche ore, e **non** significa che i due scenari rappresentino una sessione reale raggiungibile.
- `coordinator.py`: sottoscrizione agli Shelly attiva mentre il laboratorio è acceso **anche con auto scollegata**. Ogni nuovo report domestico e ogni decisione notevole producono una riga comparativa wide/medium. Timer soltanto per scadenze di validità e policy; no inseguimento dei picchi, nessun comando wallbox. Usa limite DPM positivo confermato, eventualmente ultimo positivo visto nel processo o modello DPM esplicito se il sensore è 0/indisponibile, indicando sempre l'origine nel registro. **DPM=0 resta uno stato di pausa, non una autorizzazione a riprendere**.
- `shadow_log.py`: JSON Lines per giorno locale in `/config/easywallbox_smart_shadow/shadow_YYYY-MM-DD.jsonl`, scrittura soltanto tramite executor di HA, max 2 MB/file, nessuna cancellazione di vecchi dati. Log privato locale, senza SOC reale, nomi auto o credenziali. Gestione errori tramite attributo `shadow_log_status`. In memoria dopo un riavvio si inizializzano due shadow indipendenti, senza fingere continuità della proposta; i file esistenti si accodano.
- `sensor.py`: solo in laboratorio appaiono due sensori read-only aggiuntivi `shadow_wide`, `shadow_medium`, con azione, cap, motivo, origine DPM e stato log. Non ci sono duplicati di controllori della wallbox.
- `manifest.json`: versione **0.2.0b2** solo branch dev. `__init__.py` aspetta la chiusura del worker log durante unload. `strings.json` e traduzioni IT/EN aggiornate.
- Nuovi test `tests/test_shadow_lab.py`, `tests/test_shadow_log.py` e smoke test del coordinatore in modalità auto scollegata; test di opzioni, validazione, eventuali errori e protezione da scritture reali. Suite CI python 3.12/3.13, hassfest e HACS.
- `.github/workflows/shadow-test-package.yml`: pacchetto di installazione **di prova** da scaricare come artifact GitHub Actions `easywallbox-shadow-0.2.0b2`. Non è una release Marketplace, non sposta il branch `main`. Istruzioni dettagliate in `docs/JOHNNY_SHADOW_FIELD_TEST_0_2_0B2.md`.
- Preservati DPM fisico, firmware ESPHome e automazioni Fiat esistenti; nessun servizio BLE, avvio, stop o potenza reale comandata dal test.

**Prova futura:** installare manualmente il pacchetto beta (backup della 0.1.0); attivare il laboratorio nelle Opzioni; lasciarlo registrare per più giorni e condividere solo i file `shadow_*.jsonl`. Confrontare count `reduce/restore`, durata dei cap, potenza teorica EV e pressione DPM; annotare reboot HA e tratti `house_data_quality != ok`. Prima di ogni futura fase di comando reale è necessaria autorizzazione esplicita, ownership unica e verifiche confermate. Documentazione fonte principale del progetto da aggiornare quando anche la gestione dei comandi sarà stabilita.



## 2026-11-16 — Correzione volume log dual-shadow (0.2.0b2, sviluppo)

**Segnalazione field test:** nei primi ~3 minuti il laboratorio ha registrato 43
righe per consumi domestici nell'intervallo 0,53–0,61 kW, mentre wide e
medium erano invariabilmente NORMAL/hold/4,0 kW. La frequenza dei report
Shelly era corretta per la policy ma non utile come frequenza di scrittura:
con 2 MB/giorno il file rischiava di saturarsi dopo poche ore.
Il test è stato disabilitato dall'utente prima della correzione.

**Correzione effettuata nel solo branch `stabilizzatore-m1`:**
- `shadow_log.ShadowLogSampler` comprime i report in memoria. Quando non
  ci sono eventi, scrive al massimo un riepilogo ogni 60 secondi su nuovi
  refresh; registra subito una riga per cambi di azione/stato/cap,
  qualità dati e valore/origine DPM; mantiene i report identici per timestamp
  fuori dal conteggio. Nessun rallentamento dell'algoritmo Johnny.
- Ogni riga aggiunge `log_kind` e `house_window` con numero di report,
  minimo/massimo/media, primo/ultimo timestamp. In fase di unload viene
  registrato l'eventuale intervallo parziale, senza I/O sull'event loop.
  Conservati file giornalieri privati, limite 2 MB e assenza di polling.
- Test regressione: 43 report a 4 s -> 3 righe periodiche/iniziali
  più eventuale `end`, preservando 43 campioni nel conteggio aggregato;
  eventi significativi e stale immediati; timestamp duplicati;
  cambio DPM; rotazione giorno e stima volume 24 h. Non si conserva
  l'ordine temporale esatto di tutti i campioni: per il replay puntuale
  restano necessari i dati Shelly originali.
- README e guida al laboratorio aggiornati. Il logger non cambia
  le decisioni di `johnny_policy.py`, il planner o il modello DPM.

**Osservazione sul primo log:** `dpm_model_kw=4.4` e
`dpm_model_source=configured_model`: il confronto a 4,8 kW richiede
configurare il modello corretto oppure verificare e selezionare l'entità
ESPHome del limite DPM confermato. Con EV virtuale 4,0 kW e casa
0,5–0,6 kW, il totale teorico 4,5–4,6 kW non supera 4,8 kW, mentre
supererebbe 4,4 kW. Non trattare questi numeri come attuazione elettrica.

**Verifiche:** GitHub Actions sul commit di test `51394eb8` superate
(offline Python 3.12/3.13, hassfest, HACS, pacchetto dual-shadow).
Controllare la CI della HEAD definitiva. Non ancora riprovato
su Home Assistant reale. Nessun comando BLE, nuovo controllo della
wallbox, modifica del firmware, del DPM o delle automazioni legacy;
`main` e release Marketplace 0.1.0 invariati.


## 2026-11-19 — Johnny V2: terzo laboratorio virtuale in Home Assistant (0.2.0b3)

**Richiesta:** dopo i log 16–19/11, una giornata di confronto dal vivo tra V1 Ampio, V1 Intermedio e un Johnny V2 sperimentale, con scrittura JSONL distinta e valutazione dei risultati il giorno seguente. Nessun comando alla wallbox. L'utente può archiviare i vecchi log **solo dopo backup**; conservare per confronto il dataset originario. Il V2 non è ancora la politica reale definitiva.

**Modifiche nel solo `stabilizzatore-m1`:**
- Nuovo `shadow_v2.py` (solo Python puro): terza macchina a stati virtuale che riutilizza la policy Ampio per il carico forte e testa un *buffer* −0,4 kW con 3 minuti di pressione modesta verificata (casa 0,5–1,1 kW, pressione ≥0,1 kW), quiete 10 minuti con casa ≤0,35 kW e cooldown 10 minuti. In Limited forte: massimo due correzioni aggiuntive −0,4 kW se la pressione residua ≥0,25 kW persiste 5 minuti, distanziate almeno 10 minuti. Minimo EV 1,4 kW. Nuovi timestamp Shelly obbligatori per conferme, dati ignoti non interpretati come 0.
- `shadow_lab.py` genera la terza sessione EV **sintetica inesauribile** indipendente, in parallelo ai due Johnny V1 invariati. Nessuna previsione di consumi, SOC/partenza reali, nessun comando fisico.
- `coordinator.py` aggiorna tutti e tre gli scenari sulle medesime letture Shelly, `sensor.py` mostra un terzo sensore di diagnosi, `shadow_log.py` scrive il nuovo formato **`shadow_v2_YYYY-MM-DD.jsonl`** con `wide`, `medium`, `v2`; file storici `shadow_*.jsonl` preservati. Riepiloghi ogni 60 s e transizioni immediate, max 2 MB/giorno, nessun polling veloce.
- Versione beta aggiornata a `0.2.0b3`; workflow test/package, test V2 e guida di installazione/rollback specifica aggiornati.
- Reboot nel laboratorio V2: reset **esplicito** (`virtual_state_reset_on_this_row`). La persistenza minima del cap **elettricamente confermato** rimane requisito futuro, non implementato in una versione senza comandi.

**Sicurezza e limiti:** `main`/Marketplace 0.1.0, ESPHome, DPM reale, automazioni Fiat, Home Assistant installato e modalità manuale invariati. Nessun comando BLE e nessuna promessa di beneficio elettrico confermato. La formula di pressione resta un confronto controfattuale con DPM modello; V2 è un candidato a taratura, non una politica approvata per la produzione.

**Verifiche:** test nuovi su buffer, aumento sostenuto, dati obsoleti, DPM aggiornato, log separati, nessuna attuazione; controllare GitHub Actions sulla HEAD prima di consegnare il pacchetto. **Test HA sul campo non ancora eseguito**, serviranno JSONL di oggi per calibrazione.

**Problemi aperti:** valutare cap graduale e cuscinetto su DPM modello 4,4 e 4,8 kW; energia rinunciata vs modulazione DPM; singola policy operativa, budget reale SOC/partenza, ripresa dopo reboot con riconciliazione del limite effettivo, manual override e gestione dei comandi in una futura release supervisionata autorizzata.


## 2026-11-20 — Johnny V2 ampere-aware, una sola policy shadow (0.2.0b5)

**Motivo / evidenza:** dopo i replay del 16–20/11 e la rilettura dei CSV della sera 13/11, è stato chiarito che EasyWallbox **non riceve valori in watt**. ESPHome comunica i limiti attraverso decimi di ampere negli indici BLE 174 (EV) e 158 (DPM). Gli slider sono kW *nominali* calcolati a 230 V; le misure Shelly EM sono invece watt di potenza attiva con tensione RMS reale. Le precedenti differenze 100–150 W fra richiesta EV 4,0 kW e Shelly 3,85–3,90 kW possono essere dovute almeno in parte ai 223–225 V reali, non necessariamente a un cuscinetto interno fisso. Il DPM misura la corrente della fase generale a valle del contatore e gestisce i picchi autonomamente.

**Decisioni utente per il prossimo test:** DPM di riferimento **4,4 kW** ed EV massimo nominale **4,2 kW**. Il firmware `int((kW / 0.23) * 10 + .5)` codifica rispettivamente **191** e **183** (19,1 A e 18,3 A). La differenza di disponibilità è quindi **0,8 A**, equivalente a circa 184 W nominali, non automaticamente 200 W effettivi. Al contatore, per 19,1 A e 240 V, la potenza apparente può arrivare a circa 4,58 kVA prima del fattore di potenza e dell'intervento DPM; nessuna garanzia che il display DPM = 4,4 kW implichi P rete <=4,4 kW. Il manuale consiglia un limite commisurato a potenza contrattuale e impianto. **Non viene effettuata alcuna modifica elettrica remota**; il limite concreto dovrà essere verificato sul campo e con l'installatore.

**Codice su `stabilizzatore-m1`, nessun controllo reale:**
- `shadow_v2.py`: nuova conversione `wallbox_raw_deciamps` equivalente al firmware, `wallbox_requested_amps`, corrente equivalente della casa da `Shelly W / 230 V`, esplicitamente **stima**, non reale corrente CT perché gli Shelly danno P attiva mentre carichi domestici hanno tensioni e fattori di potenza variabili. Pressione teorica espressa rispetto agli ampere BLE quantizzati. Base carichi forti Ampio riutilizzata solo come reducer puro, non come secondo controllore live.
- Il coordinator espone una **sola simulazione V2** con riferimento fisso nominale DPM 4,4 kW (19,1 A), senza le due policy shadow Ampio/Intermedio e senza il precedente confronto virtuale 4,4/4,6. DPM osservato/modello effettivo distinto dal riferimento fisso. L'utente deve impostare `max_charge_kw=4.2` dalle Opzioni: dopo upgrade la precedente opzione 4,0 resta preservata finché non la cambia. Nessuna scrittura all'EV reale o al DPM.
- V2 prova ingresso cuscinetto casa >=0,45 kW, pressione equivalente >=0,10 kW per 3 minuti; riduzione nominale 0,4 kW, uscita dopo quiete 10 minuti su pressione originaria <=0,18 kW. Carico forte: Ampio 0,6 kW/2 minuti e memoria 5 min, quiete 15 min. Massimo due correzioni aggiuntive 0,4 kW se pressione residua >=0,25 kW per 5 minuti, con gap minimo 10 minuti.
- Unico sensore diagnostico V2 read-only. Logger nuovo `shadow_v2_amps_YYYY-MM-DD.jsonl`, append-only, periodico ogni minuto ed eventi significativi, max 2 MB/giorno. Campi per corrente BLE, equivalente domestica, origine DPM, qualità fonte e stato V2. File storici non sovrascritti.
- Aggiornati manifest beta 0.2.0b5, workflow, UI IT/EN, test di conversione, comportamento 4,2/4,4, persistente leggero, logger e smoke HA (flush asincrono atteso senza sleep arbitrario), README e guida con rollback.

**Non implementato:** persistito un limite reale, comandati Start/Stop/DPM, verificata tensione al contatore, effettuato replay perfetto con campioni Shelly raw, introdotti sensori nuovi o cambiato firmware/main. Nessuna attività BLE frequente. La futura supervised release dovrà verificare di chi sia il limite, la conferma ESPHome, i watt effettivi Shelly, manual override, DPM zero, conclusione sessione, riavvii e anti-oscillazione con consenso separato.

**Verifiche:** nuovi test puri e coordinatore mock + CI da confermare sulla HEAD. Installazione 0.2.0b5 e prova su HA personale ancora **non eseguite**. Non trattare le eventuali riduzioni virtuali come effetto elettrico verificato.

## 2026-11-20 — M4, primo preflight del controllo reale supervisionato (NON ATTUATIVO)

- Verificata la HEAD iniziale del branch stabilizzatore-m1: 9c91ea6e618ccc537a6d80f10bf89e5fa6f0d7eb; beta 0.2.0b5 in sola simulazione.
- Il passaggio di consegne contiene il riepilogo dell'avvio 10:47–10:49 ma **non** i JSONL finali del 20/11. Nessuna validazione delle soglie V2, dei restore o degli adjust è stata dichiarata.
- Aggiunto custom_components/easywallbox_smart/control_guard.py, puro e NON importato dal coordinatore HA: conversione nominale kW→decimi di A, proposta fail-closed, verifica limitata di DPM/ESPHome/Shelly, distinzione richiesto/confermato e vincolo di ownership per ogni ripristino. Ogni offer richiede approvazione umana; nessuna esecuzione e nessuna persistenza.
- Introdotti tests/test_control_guard.py (15 unit test **locali** superati; CI da controllare dopo la pubblicazione) e docs/M4_CONTROLLO_SUPERVISIONATO_GUARD.md.
- Il recupero post riavvio è volutamente bloccante: un record anche coerente non sblocca automaticamente un restore; persistenza HA, session_id duraturo, approvazione e invio comandi sono ancora DA IMPLEMENTARE e testare.
- Non modificati coordinatore, session_policy, shadow_v2, manifest, main, firmware ESPHome, automazioni esistenti, DPM o configurazioni HA personali. Nessun controllo elettrico abilitato.
- Verifica post-pubblicazione su HEAD c2910b1182214c686c78c82f3636ef02bc4cd161: i 4 workflow GitHub Actions sono riusciti (M1-M2 offline checks, Home Assistant integration validation, Marketplace HACS validation, Johnny V2 single-policy ampere-aware shadow test package). I 15 test del guard erano già stati eseguiti in locale; il test complessivo è confermato anche dal workflow offline. Nessuna esecuzione su HA personale e nessun test fisico.
- Prossimi passi: ottenere il JSONL definitivo, validare V2 e il budget planner reale, verificare gli entity_id di conferma/qualità e progettare adapter con singolo proprietario, verifica reale Shelly, timeout e rollback prima di chiedere consenso alla prova attuativa.

## 2026-11-20 — Banco prova AUTO_READY e ora di inizio preferita (simulazione isolata)

- Dall'analisi del JSONL 10:47–13:21 risultano una riduzione forte alle 11:03:20 da 4,2 a 2,8 kW nominali, un ripristino alle 11:18:24, zero adjust, dati Shelly generalmente validi. L'utente ha confermato che il carico 11:00–11:03 era la macchinetta elettrica del caffè. Non sono dati di ricarica reale: il laboratorio simula una vettura infinita.
- Confermata in codice la distinzione: **2 minuti** circa per ingresso forte via policy Ampio; **3 minuti** per buffer moderato. Conservati 15 minuti per quiete del carico forte; il ripristino parziale a 10 + totale a 15 è stato valutato ma non adottato (una scrittura BLE aggiuntiva a fronte di recupero teorico ridotto, nel solo episodio del caffè circa 0,067 kWh).
- Creato `start_routine.py` puramente deterministico e NON importato in HA: offre una sola proposta di armamento DPM 0 con auto scollegata, e solo con opzione esplicita; dopo il collegamento, attesa opzionale fino a ora di inizio desiderata se il latest_safe_start lo permette, altrimenti avvio subito; ordine EV limite e conferma prima di ripristinare il DPM originario; stop target e Manuale non richiedono nuovi comandi.
- Previsti veto per dati/collegamento incerti, DPM non attivo, BLE offline, modifica manuale, proprietà della pausa incerta, mancata conferma di comando, e anti-retry per i tre passaggi. Questa infrastruttura NON garantisce la sicurezza elettrica né provvede a protezioni del circuito, compito del DPM.
- Aggiunti `tests/test_start_routine.py` con regressioni, e `docs/BANCO_PROVA_AUTO_READY_2026-11-20.md` con decisioni da approvare e blocchi del futuro executor.
- Non modificati coordinatore HA, selettore Lovelace, manifest 0.2.0b5, switch fisico, firmware, main o automazioni legacy. Il codice simula un protocollo proposto: **nessuna autorizzazione al controllo reale**.
- La verifica GitHub Actions dei nuovi test deve essere controllata sul commit finale. Prossimo passo: testare la routine su snapshot HA reali in read-only; poi definire persistenza minima, interlock e consenso prima di qualsiasi comando fisico.
