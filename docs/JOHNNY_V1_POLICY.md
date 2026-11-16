# Johnny v1 — decisione implementata sul branch di sviluppo

**Stato:** custom integration Home Assistant in **sola simulazione**. Nessun servizio HA verso la wallbox, nessuna scrittura BLE, nessun controllo dell'auto. Il DPM fisico resta sempre l'unico controllo rapido e la protezione elettrica.

## Obiettivi e priorità

1. **Target SOC entro l'ora di partenza**: il planner legge SOC, target, capacità utilizzabile, efficienza, orario e velocità di ricarica stimata da Shelly/sessione ESPHome. Se i dati non consentono di stimare la raggiungibilità, Johnny non avvia nuove limitazioni opzionali.
2. **Aiutare il DPM durante i carichi intermittenti persistenti**: stimare la pressione sul DPM, attendere misure nuove e coerenti prima di suggerire un unico limite EV stabile, invece di seguire ogni picco.
3. **Poche variazioni di limite**: nessun rialzo graduale. Un cap virtuale per episodio e un ripristino diretto dopo quiete sufficiente, costo cumulativo massimo o necessità della partenza. Le proposte **non equivalgono a scritture**.
4. **Semplicità**: nessuna fascia oraria di cucina, riconoscimento elettrodomestici, IA, PV, tariffa dinamica o nuovo polling BLE.

## Algoritmo scelto per la prima prova

Pressione teorica: `max(0, consumo_casa_senza_EV + limite_EV_confermato − limite_DPM)`. È una stima del lavoro **potenziale** del DPM, non una misura dei suoi comandi.

La preferenza è leggere il limite DPM da `Limit house power set -DPM-` già esposto dal firmware ESPHome (nuovo campo configurabile `dpm_confirmed`). Il vecchio valore di modello `dpm_model_kw` resta utilizzabile solo se **nessuna** entità DPM è stata selezionata, e viene identificato come modello; in nuova configurazione il valore precompilato è 4,4 kW, non i 5,2 kW di tolleranza temporanea del contatore. Se una sorgente DPM selezionata diventa `unknown` o `unavailable`, niente fallback silenzioso al valore statico.

| Fascia da SOC, target e partenza | Condizione per proporre riduzione | Ripristino per quiete | Budget conservativo della sessione |
|---|---|---|---|
| **Ampio**, slack oltre 120 minuti | Pressione DPM >=0,6 kW per >=120 secondi, con letture **distinte** | 15 min di pressione <=0,4 kW | 25% dell'energia equivalente allo slack stimato |
| **Intermedio**, slack oltre 45 e fino a 120 min | Pressione >=0,8 kW per >=180 secondi, letture distinte | 10 min di pressione <=0,4 kW | 10% dell'energia equivalente allo slack |
| **Urgente**, slack <=45 min, target non raggiungibile o dati ignoti | Nessuna nuova limitazione opzionale | Ripristina cap virtuale posseduto se necessario | Nessun nuovo budget |

Parametri e durate **sono scelte iniziali della simulazione**, non tarature hardware validate. Il budget è fissato al primo intervento della sessione e non viene ricaricato artificialmente ai cicli successivi. È contabilizzato come **limite superiore** `(limite_originale − cap) × tempo`, anche durante letture mancanti; la perdita EV reale può essere inferiore perché il DPM avrebbe già limitato la potenza.

Il limite candidato si calcola da un quantile alto (75° percentile approssimato) delle letture nuove degli ultimi tre minuti, meno un margine 0,2 kW nella fascia ampia / 0,1 kW in quella intermedia, arrotondato a multipli di 0,2 kW. Non proporre mai meno di 1,4 kW, né una riduzione inferiore a 0,6 kW dal limite EV confermato. **Una volta proposto, il limite non viene ricalcolato a ogni variazione Shelly.** Al ripristino seguono almeno 10 minuti di cooldown.

Sorgente consumo domestico: somma di 1..N Shelly di casa **escludendo** lo Shelly EV, tutti attendibili e riportati entro 3 minuti. Il timer HA NON è trattato come un nuovo campione di carico: due verifiche con lo stesso `last_reported` non possono confermare falsamente un episodio. Il sistema non anticipa l'accensione di un phon e non garantisce assenza di picchi elettrici.

## Evidenze considerate, non risultati di un nuovo collaudo

- Studio delle 7 sere 7–13/11: soglie fisse precedenti con quiete 15–20 minuti hanno ridotto il numero di cambi virtuali rispetto a quiete di 10, ma possono consumare budget troppo presto. Era una logica differente: **non** è un replay numerico di Johnny v1.
- Dati del 15/11: 125 campioni del piano superiore tra 20:30 e 22:57, piano inferiore stimato 200 W costanti su indicazione dell'utente; ultimo phon compreso. Il replay del laboratorio aveva mostrato che una soglia fissa casa1,5 kW poteva non intercettare la modulazione DPM del phon, mentre una soglia dinamica si adattava al setpoint dell'auto. Il 75° percentile, i 15/10 minuti di quiete e il budget scelti **non sono stati ancora collaudati nella casa reale**.
- Esperimento ipotetico DPM con 5 secondi di ritardo: nessun controllore lento può garantire l'assenza del primo picco imprevisto; la scelta del cap stabile può influenzare picchi successivi, **non sostituire il DPM**.
- Le tracce domestiche originali sono PRIVATE e non sono state committate su GitHub.

## Implementazione e verifiche

- Modulo puro `custom_components/easywallbox_smart/johnny_policy.py` con stato per sessione, fascia, limiti, budget, isteresi, timestamp e motivi delle proposte.
- **Unico collegamento HA:** `coordinator.py` richiama la nuova funzione di valutazione; il vecchio `core.evaluate` rimane temporaneamente soltanto per test/regressioni, **non** è un secondo supervisore attivo.
- `core.py` conserva `plan` e i tipi dati, estesi con timestamp del consumo e limite DPM.
- `config_flow.py` e Options Flow possono leggere un sensore DPM confermato; `sensor.py` mostra la fascia e il limite usato, senza entità supplementari.
- Test: `tests/test_johnny_policy.py` per simulazione pure Python e `tests/test_coordinator_session_smoke.py` per l'adattatore Home Assistant finto.
- **Ancora da verificare**: Config Flow reale su Home Assistant, clock, aggiornamento Shelly, stima dell'energia dopo pausa, comportamento Session Energy e Duration in ricarica, eventuali correzioni a 18/8min dopo la prima sessione reale.

## Criteri per il collaudo e rollback

Nella prima ricarica ordinaria, confrontare timestamp e proposte di Johnny con consumo domestico, potenza effettivamente misurata dallo Shelly EV, limite DPM e SOC; segnare `reduce`, `restore`, `hold`, fascia, costo stimato. Non forzare carichi né Stop/Start. Se il limite DPM non è attendibile, restare in simulazione senza nuove riduzioni.

Nessuna modifica a firmware ESPHome o alle automazioni Fiat. Branch `stabilizzatore-m1` e manifest `0.2.0b1` non pubblicato; `main` e Marketplace `0.1.0` restano invariati. Il rollback dalla futura versione di test sarà possibile mantenendo la release pubblicata 0.1.0 come riferimento. La migrazione reale a controllo supervisionato richiederà discussione, test hardware e autorizzazione esplicita.

## Replay continuo sette giorni (9–15 novembre 2026) — aggiornamento 16/11

Ricevuti due nuovi CSV HA (`sensor.assorbimento_sotto` e `sensor.assorbimento_sopra`), **non caricati su GitHub**. Sono 168 ore di calendario, di cui 8.876/10.080 minuti con entrambi gli Shelly attendibili se si consente una validità del dato di 180 secondi (**88,1%**). Righe aggregate iniziali e valori `unknown`/`unavailable` non vengono trattati come potenza istantanea zero.

Laboratorio di una **sola sessione EV ipotetica** a 4 kW, DPM 4,4 kW, stati non resettati a mezzanotte e fasce *wide*/*medium* mantenute artificialmente costanti. Per soddisfare l'assunzione di «batteria infinita», nel **solo laboratorio** è stato escluso il budget di energia sacrificabile; questa è un'analisi di sensibilità della macchina a stati, non una sessione realistico/SOC del planner. I valori riportati sono stime su minuti campionati, DPM ideale senza ritardo, non attività reale del DPM.

| Fascia | Quiete originale | Cambi virtuali originali | Extra kWh originali | Quiete scelta | Cambi nuovi | Extra kWh nuovi |
| --- | --- | ---: | ---: | --- | ---: | ---: |
| Ampio, conferma 120s | 18 min | 53 | 48,10 | **15 min** | 59 | **38,37** |
| Intermedio, conferma 180s | 8 min | 62 | 16,39 | **10 min** | 61 | **21,26** |

Stima dei minuti con modulazione DPM teorica di almeno 0,6 kW: senza cap 643; ampio 18 min: 196, ampio 15 min: 173; intermedio 8 min: 293, intermedio 10 min: 258. Il numero dei cambi **non** equivale a scritture BLE, perché l'integrazione è solo simulazione.

**Scelta per Johnny v1:** aggiornare unicamente quiete **ampio da 18 a 15 min**, **intermedio da 8 a 10 min**; mantenere conferma 120/180s e cooldown 10min, senza introdurre fasce orarie o gradini. La sensibilità all'età massima dei dati (120s/150s/180s) è elevata; se il cap resta attivo durante telemetria mancante, l'energia teoricamente sacrificata può crescere molto. Prima del controllo reale richiede una specifica politica di sicurezza per dati assenti/obsoleti e monitoraggio in HA reale.

Se si applicasse letteralmente il budget bloccato della prima riduzione per un'unica sessione di 7 giorni, la fascia *medium* con soli 90 minuti di slack si esaurirebbe quasi subito e non rappresenterebbe una settimana infinita: **non equiparare il replay senza budget al comportamento automatico reale**.

Nessun firmware, DPM fisico, `main` o release pubblicata modificati.


## 16/11/2026 — Robustezza simulatore: uscita sessione e perdita Shelly

**Già implementato nel ramo `stabilizzatore-m1`, SOLO SIMULAZIONE.** Conferma carico 2/3 minuti, quiete 15/10 minuti e cooldown 10 minuti **invariati**.

### Uscita dal limite opzionale senza effetti elettrici fittizi

- **Target raggiunto** (SOC attendibile) mentre la wallbox segnala ancora ricarica, oppure **ricarica terminata con wallbox `Charging = OFF` verificato, `Telemetry Fresh = ON`, auto identificata e limiti ancora coerenti**: emette una singola proposta virtuale `restore` al limite originale, con motivo specifico. **Non dichiara ripristinata la wallbox** e non scrive via BLE.
- **Carica subito esplicito** durante un cap virtuale: propone il ripristino, solo con identità/proprietà e setpoint coerenti.
- **Pausa, Manuale, cambio veicolo, disconnessione, limite richiesto/confermato incongruente o stato di carica contraddittorio**: emette `retire` con causa di riconciliazione; **nessun ripristino automatico non autorizzato**. La vecchia sessione non trasferisce il proprio cap alla successiva.
- Il coordinatore HA **non azzera prematuramente lo stato virtuale** quando viene osservato un distacco o cambio auto; lascia al riduttore puro la possibilità di emettere il messaggio di riconciliazione. La modalità utente Manuale/Pausa non viene mai annullata automaticamente.
- Gli attributi del sensore **Stabilizzatore** riportano l'ultima transizione virtuale e relativo timestamp per la diagnosi, anche dopo il successivo passaggio a `inactive`. Sono *eventi di decisione* e non conferme BLE.

### Mancanza prolungata dei consumi domestici

- Per autorizzare una nuova riduzione tutti gli Shelly selezionati devono essere attendibili e freschi; `unknown` e `unavailable` non significano zero.
- Un cap virtuale già attivo **non viene ripristinato alla prima lettura mancante**. La perdita interrompe il conteggio della quiete.
- Dopo **8 minuti dall'ultima lettura domestica complessivamente attendibile** il simulatore propone un `restore` del limite opzionale con motivo `house_telemetry_timeout_restore_proposed`, **purché sessione e proprietà restino coerenti**. Il DPM fisico rimane attivo. Se le informazioni elettriche o la sessione sono ambigue, si richiede riconciliazione e non si presume una scrittura consentita.
- Home Assistant programma una **scadenza singola** per la freschezza dei sensori, più la scadenza di recupero se Johnny è limitato; **nessun polling di controllo continuo**. Un timer che rilegge lo stesso campione non dimostra una nuova accensione.
- Dopo il ripristino virtuale si mantiene il cooldown ordinario di 10 minuti; ulteriori riduzioni richiedono di nuovo report freschi e persistenti.

### Limite esplicito prima di qualsiasi attuazione

Le proposte `restore` e `retire` non costituiscono attuazione confermata. Quando e **soltanto quando** si discuterà di comandi supervisionati, serviranno un unico proprietario del limite, memorizzazione di richiesta e riscontro, riconciliazione al riavvio, gestione delle disconnessioni BLE, conferma dell'effetto e nessun retry cieco. Durante i dati incoerenti non autorizzare nuove riduzioni né dedurre un effetto elettrico.

**Test:** regressioni del riduttore puro e del coordinatore HA con fake sensori, auto, limiti e timer. Nessuna prova attuale sulla wallbox reale. `main`, firmware ESPHome, automazioni legacy e DPM fisico invariati.
