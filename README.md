# EasyWallbox Smart Charging

**0.9 beta — Home Assistant custom integration.** Non ancora collaudata con una ricarica completa su auto reale: la prima prova dev'essere supervisionata.

L'integrazione gestisce la pianificazione della carica e una stabilizzazione *lenta* del limite EV tramite le entità del firmware EasyWallbox ESPHome. Non sostituisce il **DPM della wallbox**, che deve rimanere attivo e continua a occuparsi dei picchi elettrici e delle protezioni.

## Architettura

- **ESPHome + BLE**: legge e conferma registri e stati della wallbox; esegue i comandi richiesti.
- **Home Assistant / EasyWallbox Smart Charging**: identifica l'auto, legge SOC e orari, calcola i margini, prende decisioni e invia comandi soltanto dopo le verifiche previste.
- **Tre Shelly EM** nel setup di riferimento: due rami dei consumi domestici e un ramo dedicato alla wallbox. Per la policy si usano soltanto i consumi domestici, escludendo l'EV.
- **La wallbox con DPM attivo** resta l'unico controllore rapido di corrente. Un comando BLE, uno switch o un ACK non dimostrano da soli la potenza effettivamente erogata.

Firmware ESPHome: https://github.com/paolofaz/Easywallbox---Esphome. Questo progetto è separato e non modifica il firmware.

Nessun Docker aggiuntivo, script esterno, fotovoltaico, tariffe dinamiche o decisioni AI.

## Installazione e aggiornamento

Richiede una versione di Home Assistant compatibile con **2026.11** (quality gate su **2026.11.1**) e una EasyWallbox ESPHome già funzionante. Installare tramite HACS/Marketplace come integrazione personalizzata da questo repository, oppure copiare `custom_components/easywallbox_smart` in `config/custom_components/` e riavviare HA.

Per aggiornare da un'installazione esistente, **non eliminare l'integrazione né i suoi dati**: dominio `easywallbox_smart`, config entry ed entità restano gli stessi. Prima dell'aggiornamento fare un backup Home Assistant. La versione manifest è `0.9.0b1`; la release GitHub è una **prerelease beta**, non la v1.0.

Aprire *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → EasyWallbox Smart Charging* e completare il config flow grafico. In caso di installazione preesistente, usare le Opzioni.

### Entità richieste

Selezionare le sette entità obbligatorie della **stessa** wallbox ESPHome: Connection BLE, Car Connected, Charging, Start-Stop, Charge power richiesto, limite EV confermato e DPM confermato. Specificare il valore DPM normale atteso, la potenza EV predefinita, le sorgenti Shelly del consumo domestico **senza EV** e lo Shelly EV separato. Sono disponibili fonti opzionali per Charge State, Session Energy, Session Duration e relè fisico di alimentazione.

Configurare uno o più profili auto con sensore cavo, SOC, capacità batteria, rendimento AC, orari feriali/festivi e target SOC da entità o fisso. È possibile selezionare un pulsante di aggiornamento dati veicolo e, se voluto, lo Stop SOC gestito da questa integrazione. Nel setup di riferimento: Fiat 500e e Kia EV3.

**Valori predefiniti per nuove installazioni:** 4,2 kW per la sessione e 4,4 kW come DPM configurato. Non sono un dimensionamento per altri impianti; verificare sempre limiti e dati reali. Le configurazioni esistenti non vengono sovrascritte.

### Evitare comandi concorrenti

Prima del primo collaudo, verificare che le vecchie automazioni HA che comandavano *Charge power* o *Start-Stop* non siano contemporaneamente attive. Lo Stop SOC Fiat legacy, in particolare, non deve duplicare quello dell'integrazione. Conservare l'automazione precedente come riferimento fino alla migrazione collaudata, ma non lasciarle comandare indipendentemente lo stesso dispositivo.

## Come funziona

- **Automatica**: legge stato fisico, dati auto e Shelly; calcola il margine rispetto alla partenza; in condizioni verificate può ridurre il limite EV con una policy lenta e anti-oscillazione.
- **Manuale**: la gestione automatica lascia la sessione all'utente sino alla disconnessione fisica.
- **Avvio posticipato**: da predisporre prima di collegare l'auto, se desiderato; usa il meccanismo di pausa DPM0 già funzionante. Non anticipa automaticamente l'ora scelta.
- **Potenza desiderata sessione**: slider conforme a min/max/step esposti da ESPHome. La preferenza non equivale a un comando scritto o a potenza misurata.
- **Target SOC**: un target fisso o una entità HA, con Stop SOC soltanto per auto abilitate e con conferme indipendenti.
- **Riavvio HA e BLE**: verifica le prove di sessione e il limite precedentemente confermato senza ripetere comandi alla cieca. Se non può riconciliare un LIMITED o un override in sicurezza, blocca i nuovi comandi. Lo sblocco ordinario avviene dopo il distacco fisico confermato; non esiste uno switch UI dedicato a forzarlo.

Il supervisore non segue i picchi secondo per secondo. Un LIMITED può rientrare in NORMAL dopo 15 minuti *osservati* di headroom nominale, o in caso di urgenza con effettiva opportunità di potenza. La condizione di quiete è attualmente `DPM - casa - baseline ≥ −0,02 kW`; è **da verificare sui dati reali**, non va modificata preventivamente.

## Interfaccia

Sono disponibili entità di stato, pianificatore/avvisi, auto identificata, fase stabilizzatore, stime di energia e completamento, selezione modalità, orari, slider potenza sessione e, ove configurato, slider SOC. Non vengono duplicati i sensori di corrente/potenza Shelly o gli stati BLE. È disponibile una card storico sessioni per Lovelace: l'integrazione registra la risorsa JavaScript ma **non crea una dashboard**.

Un avviso di limite precedente mostra l'**ultimo valore confermato**, non una lettura attuale: verificare sempre il valore effettivo di ESPHome e le misure Shelly prima di intervenire.

## Diario diagnostico — attivabile dalle Opzioni

In **Impostazioni → Dispositivi e servizi → EasyWallbox Smart Charging → Configura → Diario diagnostico** è disponibile il flag **“Scrivi il diario delle decisioni su disco”**.

- **Attivo di default** per il primo collaudo della beta 0.9; può essere disattivato anche in seguito.
- Quando è attivo, produce file JSONL giornalieri sotto `/config/easywallbox_smart/decision_logs/decisions_YYYY-MM-DD.jsonl`, con eventi, decisioni, comandi richiesti, conferme e motivazioni.
- Quando è disattivo, **non vengono registrati nuovi eventi**; il salvataggio dell'opzione ricarica l'integrazione. I file già esistenti non vengono cancellati e gli eventuali eventi già in scrittura possono terminare durante il cambio.
- Il diario usa una coda limitata, scrittura serializzata e permessi locali restrittivi. Non provoca nuove letture o comandi BLE. Evitare di pubblicare i log: possono contenere orari, identificativi e dati d'utilizzo.

Questa impostazione è destinata a rimanere disponibile anche dopo la beta, senza legare l'attivazione a una versione software.

## Collaudo e sicurezza

La beta è passata attraverso prove automatiche del controller, del config flow, della logica di potenza, dei blocchi di sicurezza e dei riavvii, nonché verifiche Hassfest e su Home Assistant. **Un test automatico non conferma un effetto elettrico**.

La prima ricarica deve essere supervisionata, con DPM attivo, misure ESPHome/Shelly attendibili e senza automazioni concorrenti. Dopo la carica analizzare il diario JSONL e gli eventuali dati esportati dagli Shelly: ingressi/uscite LIMITED, guadagno di energia utile, frequenza di comandi BLE, gap nei report e freschezza SOC. Solo dopo i test reali sarà valutata la promozione a **1.0 stabile**.

[Checklist del primo collaudo](docs/COLLAUDO_BETA.md) · [Licenza](LICENSE)
