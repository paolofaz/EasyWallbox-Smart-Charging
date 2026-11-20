# EasyWallbox Smart Charging — Release Candidate

**Versione codice: 0.3.0rc1 · Home Assistant 2026.11+ · branch `RC`.**
Custom integration nativa Python. Nessun container, script esterno o modifica
del firmware ESPHome. Il DPM **rimane sempre attivo** e conserva il controllo
rapido dei sovraccarichi. Johnny non è una protezione elettrica.

**RC non collaudata sull'impianto reale.** GitHub CI, hassfest e test isolati
controllano il codice; il primo collaudo con una vera sessione deve confermare
la sequenza BLE, la risposta Shelly, la proprietà dei limiti e il comportamento
dopo riavvio. La release precedente e il branch `main` restano disponibili.

## Principio fondamentale

Johnny governa **una sola wallbox e un solo veicolo alla volta**.
Moduli separati: planner (SOC/partenza), stabilizzatore lento Johnny,
esecutore **unico** di comandi Home Assistant, laboratorio isolato.
L'esecutore usa esclusivamente le entità ESPHome già esposte:

- **`number` Charge power:** scrive il limite EV in kW; `sensor` Power set
  è il riscontro del valore letto dalla wallbox.
- **`switch` Start-Stop:** OFF scrive DPM **0 A**; ON recupera
  l'ultimo DPM positivo tramite il firmware ESPHome. È il metodo
  Start-Stop già provato sul firmware. **Non** spegne il DPM Active.
- **`binary_sensor` Charge Enabled** e **`sensor` Limit house power
  set -DPM-** verificano l'effetto della richiesta. `Command status`
  distingue richiesto, confermato e non riuscito. **Una chiamata HA
  riuscita non equivale a un effetto elettrico verificato**.

### Ciclo di vita della ricarica

| Evento/stato | Azione RC autorizzata |
|---|---|
| Prima connessione, cavo già OFF all'avvio di HA | Nessun comando; non inventare una transizione |
| Cavo della wallbox **ON → OFF** | Dopo conferma **30 secondi** con Shelly EV **<30 W**, DPM Active e BLE affidabili: una sola richiesta `Start-Stop OFF`, se il controllo reale è stato abilitato e il DPM positivo corrisponde alla configurazione |
| Fine sessione in Manuale | Torna **Automatico** allo scollegamento, senza interferire con la sessione manuale appena conclusa |
| Wallbox parcheggiata | `Charge Enabled OFF` e DPM 0 A confermati; nessun altro comando finché non viene collegata un'auto |
| Cavo **OFF → ON** | Attende 20 secondi, identifica Fiat/Kia, chiede al massimo un aggiornamento dati per auto (entrambe soltanto se non sa quale sia collegata) |
| Dati aggiornati | Verifica SOC, target, partenza, resa, capacità e tempo residuo. Senza dati coerenti **non avvia** |
| Avvio posticipato | Rimane a DPM 0 A finché è prudente attendere; l'ultimo inizio utile anticipa l'orario desiderato quando necessario |
| È ora di iniziare | Verifica o imposta il limite EV a **4,0 kW**, attende conferma, quindi **una sola richiesta Start-Stop ON** e verifica il DPM positivo |
| In carica | Solo Johnny può cambiare `number.Charge power`; **mai Start-Stop** durante la ricarica |
| Target raggiunto | Non riavvia; alla disconnessione prepara la wallbox per la sessione successiva |
| Dati incerti, BLE perso, risposta contraddittoria | Nessuna nuova scrittura, diagnosi e riconciliazione manuale; **mai retry ciechi** |

Una richiesta `Start-Stop OFF` è consentita anche con cavo scollegato
**esclusivamente sulla transizione ON→OFF verificata**. In tutte le altre
condizioni a cavo scollegato Johnny non scrive nulla.

Il comando `number.set_value` a 4,0 kW **prima** dell'avvio è
un'eccezione intenzionale: la wallbox è parcheggiata e l'auto non sta ancora
caricando, quindi non deve ereditare un cap ridotto dalla sessione precedente.
Prima di `Start-Stop ON` vengono verificati tanto il limite EV
quanto l'identità e il fabbisogno della macchina.

### Refresh auto e firmware

Nel Config Flow, per **ciascuna auto**, configurare il relativo pulsante
`Update data` / `Deep Refresh` e, se disponibile, l'entità che riporta
la data reale dell'ultimo aggiornamento. **Non esistono entity_id fissati
nel codice.** Dopo 20 secondi dalla connessione Johnny invia una sola
`button.press` all'auto identificata; se ancora sconosciuta, una a
Fiat e una a Kia. Attende fino a **120 secondi**, senza retry.
**Premere un pulsante non significa ricevere dati nuovi**: il planner
attende un timestamp originario aggiornato, oppure un nuovo report SOC
dopo la richiesta. Il laboratorio H24 non preme i pulsanti delle auto.

Il Config Flow richiede anche il pulsante ESPHome **Refresh data**:
legge una volta i registri BLE per avere un DPM aggiornato. Se la carica
è rimasta posticipata per ore e il DPM letto è obsoleto, una seconda
richiesta **soltanto al momento dell'avvio** evita di fidarsi di un
readback vecchio. Non esiste polling BLE aggiuntivo continuo.

### DPM: configurazione distinta dall'osservazione

Il limite nominale DPM è configurato in Home Assistant (es. **4,4 kW**).
Johnny usa **sempre questo valore positivo per i calcoli**, anche se
la wallbox parcheggiata segnala **0 A**. Il sensore DPM reale non è
il parametro matematico: prova che la pausa è davvero a zero o che
l'avvio ha ripristinato il limite positivo atteso. Se un limite
positivo diverso viene rilevato, il controllo non lo corregge
silenziosamente. Il firmware converte le potenze in decimi di
ampere nominali usando 230 V: l'active power Shelly non è
una misura della pinza DPM.

## Regole Johnny RC

Valori predefiniti (modificabili nei limiti ammessi dal firmware):
**base 4,0 kW**, **boost 4,2 kW**, **DPM 4,4 kW**, pavimento EV **1,4 kW**.

| Caso | Condizione e azione |
|---|---|
| Forte | Pressione DPM nominale almeno **0,6 kW** per ~2 minuti di nuovi campioni Shelly; per cicli intermittenti, memoria 5 min, 2 accensioni, 120 s osservati e area ≥2,4 kW·min |
| Primo cap forte | 75º percentile *discreto* delle letture alte negli ultimi 3 min, margine 0,2 kW, passi da 0,2 kW per difetto, minimo 1,4 |
| Moderato | Casa 450–1100 W, pressione ≥100 W per **10 minuti osservati negli ultimi 12** → riduzione di 0,4 kW |
| Già LIMITED | Pressione residua ≥250 W per **5 minuti osservati sugli ultimi 7**, ancora presente; nuova discesa di 0,4 kW solo dopo ≥10 min dall'ultimo cambio; massimo due correzioni |
| Ripristino | 15 minuti **documentati** di margine sufficiente per la potenza originaria; ritorno diretto alla base, senza gradini |
| Planner | Nessuna nuova riduzione facoltativa se il budget è esaurito o il margine di partenza è a rischio; il DPM mantiene il controllo rapido |
| Boost urgente | **Solo** con margine prudenziale ≤60 min e casa <150 W per 15 minuti: 4,0→4,2 kW |
| Isteresi boost | Uscita quando casa >200 W; oppure, se margine ≥75 min stabile, rientro alla base. No boost con informazioni SOC incerte |

I timer non creano nuove misure Shelly. I cambi fisici del cap devono
attendere conferma ESPHome; nessun comando viene ripetuto per
tentare di inseguire i picchi.

## Dashboard, opzioni e Recorder

Config Flow grafico: sensori Shelly **domestici** (escluso il ramo EV),
Shelly wallbox, cavo collegato alla wallbox, Charging, Telemetry Fresh,
DPM Active, Fault, Charge Enabled, Start-Stop, Command status,
Charge power, Power set, DPM confermato, Refresh data, DPM
di riferimento, base e boost, uno o più veicoli con SOC, target
(esclusivamente entità o fisso), capacità, efficienza, potenza di
pianificazione prudenziale e orari feriali/weekend.

Controlli nativi in Lovelace: **Automatico/Manuale**, **Controllo reale**,
**Avvio posticipato**, ora desiderata, override della prossima partenza,
**Carica subito**, pausa della *gestione* (non stop fisico della carica),
ripresa e annullamento override, **Laboratorio H24**.
Dashboard: [`docs/LOVELACE_RC.yaml`](docs/LOVELACE_RC.yaml).
Dopo l'installazione sostituire i segnaposto con gli entity_id reali
generati dal tuo Home Assistant.

Due soli sensori diagnostici di RC (stato e planner) pubblicano
**cambi di significato**, non ogni nuovo watt o countdown al secondo.
Le misure originali restano nei rispettivi Shelly/ESPHome.
La configurazione e le preferenze sono salvate tramite lo Store HA;
non si scrive ogni campione nel Recorder.

## Laboratorio H24

Una **auto artificiale sempre collegata e sempre in carica**, completamente
isolata dall'esecutore reale, riceve i dati domestici; confronta scenario
ordinario e scenario urgente a 45 minuti. Produce un JSONL **privato**
per giornata in
`/config/easywallbox_smart_lab/rc_shadow_YYYY-MM-DD.jsonl`,
massimo 2 MB/file, senza comandi BLE o alle auto. Non inserire cronologie
domestiche o file `.storage` in un repository pubblico.

## Riavvii e condizioni di sicurezza

- Il riavvio HA **non cambia il DPM fisico**. Johnny osserva
  `Charge Enabled` e il sensore di DPM; una pausa verificata di cui
  ha salvato la provenienza può essere riconosciuta, ma **non**
  genera un avvio cieco. L'abilitazione **Controllo reale torna OFF
  dopo ogni riavvio o reload** e richiede un nuovo consenso utente.
- In Manuale Johnny non invia comandi; al passaggio ON→OFF confermato
  torna in Automatico e, se il controllo reale era abilitato,
  può parcheggiare dopo le verifiche.
- Alla perdita di SOC, cavo, BLE, DPM, Shelly o dopo un ACK
  mancante, si sospendono nuove scritture e si mostra il motivo.
- Un `Start-Stop ON` recupera l'ultimo DPM memorizzato nel
  firmware, non forza un numero inventato; deve essere verificato
  contro il riferimento DPM configurato.

**Controllo reale**: interruttore OFF di default. Prima di accenderlo
disabilitare le automazioni concorrenti che scrivono lo stesso
`Charge power` / `Start-Stop`; il flag del Config Flow è una
conferma dell'utente, non una verifica tecnica dell'impianto.

## Installazione RC e rollback

Questa è una **prerelease per un primo collaudo supervisionato**.
Prima sostituire/rimuovere la vecchia integrazione e la vecchia
config entry: RC richiede nuove entità e non migra automaticamente
la beta 0.2.0b5. Conservare una copia della versione precedente,
senza modificare manualmente `.storage`.
Non aggiornare `main` e non modificare ESPHome.
Seguire [`docs/CHECKLIST_COLLAUDO_RC.md`](docs/CHECKLIST_COLLAUDO_RC.md)
per prova in sola lettura, prova supervisionata e rollback.

Se pubblicata come prerelease GitHub da questo branch, l'installazione
tramite **Impostazioni → Marketplace → repository custom**
richiede di attivare **Pre-release** per il repository e di
riavviare Home Assistant dopo l'installazione.
