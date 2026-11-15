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
