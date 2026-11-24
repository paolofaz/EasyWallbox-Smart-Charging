
## 24 novembre 2026 — prova 09:23–09:52 e correzione archivio RC5

### Dati della prova reale
- Diario decisions_2026-11-24(1).jsonl, 255 eventi della versione 1.0.0rc4. Auto Kia EV3, target iniziale 80%, poi 90%, SOC misurato 80→80,5% prima dello scollegamento. L'utente riferisce circa 81% dopo la lettura cloud: il diario termina prima della sua reimpostazione a 80%.
- NORMAL 4 kW, LIMITED 2,2 kW alle 09:31:42 con 1,94 kW casa, conferma 09:31:45; NORMAL 4 kW alle 09:46:50, conferma 09:46:54. Protezione DPM e anti-oscillazione coerenti; nessun cambiamento alle soglie.
- Il controller riconosce 'session_close / cable_unplugged' alle 09:52:04. La card utente non mostrava il record, ma il diario RC4 NON registra eventi archivio: il file non permette di distinguere fra contatori mancanti, record non scritto o risposta UI già caricata.

### Debolezze identificate nell'archivio RC4
- `_pair()` richiedeva due letture recenti con scarto timestamp massimo 4 s. HA può aggiornare i due sensori in eventi diversi e lo stato_changed non è emesso a ogni report identico; nessuna coppia accettata significa archivio vuoto anche con ricarica reale.
- La logica precedente sommava i segmenti solo al reset simultaneo dei due contatori, scartando le discese di uno solo.
- La card `_loaded` richiedeva apertura o click 'Aggiorna': una riga realmente salvata poteva non comparire sul dashboard già aperto.
- Sono possibili ulteriori cause specifiche della prova: mappature opzionali `Session Energy`/`Session Duration` mancanti dopo un aggiornamento, sensori `unavailable` o durata/energia effettiva sotto soglia. Non affermiamo una causa certa per la sessione 09:23→09:52 senza `.storage` o nuovi log dell'archivio.

### Correzione su main per RC5
- Contatori ora indipendenti: accumulano il delta reale di energia e minuti di ciascun sensor, con salvataggio dei progressivi in `.storage`, senza sincronizzazione forzata dei timestamp.
- Reset di un contatore non azzera l'altro; recupero dei progressivi dell'attiva salvati in RC4, senza attribuire l'intero contatore nonzero preesistente alla nuova sessione (conserva solo incrementi osservati e marca 'partial_observed').
- Salvataggio sempre e solo dopo distacco fisico verificato, con soglie minime di energia/durata; nessun comando BLE aggiunto.
- Nuovi eventi JSONL 'archive_configured_at_start' e 'verified_unplug_archive_status' con enabled, active, progressivi, stato sensori e risultato; pagina WebSocket aggiunge archive_status e la card rende visibile eventuale scarto per contatori insufficienti.
- Card aggiornata automaticamente dalla sola API read-only, massimo ogni 30 s quando HA le passa uno stato, mantenendo il pulsante Aggiorna.
- Test per timestamp indipendenti, reset solo kWh, contatori iniziali nonzero e motivazione dell'archivio disabilitato, oltre a tutti i test esistenti. Richiesto collaudo su Home Assistant: ricarica >0,2 kWh, distacco del cavo, verifica riga e conferma che nessuna riga compaia durante Pause.

### Pubblicazione RC5
- Candidate solo per collaudo reale, non 1.0.0 stabile. Dopo quality gate completo, pubblicazione prerelease `v1.0.0rc5` dal commit di release. Nessuna modifica ESPHome e nessun comando DPM numerico.
- La precedente RC4 può mostrare storico vuoto per cache e/o per mancati accoppiamenti di contatori; non possiamo distinguerli nel diario RC4. La RC5 include la diagnostica necessaria.

### Limitazioni e rollback
- La sessione del 24/11, se non archiviata da RC4, non può essere recuperata con accuratezza dal solo diario delle decisioni. Il recupero dei record precedenti non è garantito.
- Continuità durante distacco e nuovo collegamento interamente in BLE offline non dimostrabile: conservare marca di qualità parziale, non attribuire a un'auto non identificata dati inventati.
- Non toccati firmware ESPHome, Start-Stop, DPM numerico, ETA e policy NORMAL/LIMITED. Per rollback restare su versione RC4/0.9.2b1 con rispettive mappature, tenendo conto della diversa semantica Charge Enabled; meglio backup .storage prima dell'aggiornamento.

# NOTE SVILUPPO — EasyWallbox Smart Charging

## 24 novembre 2026 — preparazione 1.0 release candidate

### Fonte
Analizzati `decisions_2026-11-23(5).jsonl` e `decisions_2026-11-24.jsonl` della ricarica reale Kia EV3 (47→80% circa, fine intorno alle 04:20). Confermati due cicli LIMITED→NORMAL nella seconda parte della notte. DPM resta proprietario del controllo rapido. Non si modificano soglie, tempi o livelli della policy in questa revisione.

### Correzione 1: storico sessioni
- Un record **solo** dopo `Car Connected=OFF` con evidenza `Cable Unplugged` e `Charging=OFF`, mentre BLE è valido.
- Nessun record al reset con cavo ancora collegato, né in `Pause`.
- Somma persistente dei segmenti di contatori `Session Energy` e `Session Duration` tramite .storage; durata in ore/minuti in interfaccia.
- Riconoscimento automobile solo da profilo identificato dal controller; se non verificato, `Non identificata`. Identità conflittuali non assegnate.
- BLE perso / riavvio HA non archivia né azzera progressi. Marca la qualità dell'osservazione `partial_observed` se c'è stata discontinuità.
- Ignora i vecchi frammenti creati dalla beta da un reset senza prova fisica di completamento. Non tenta di inventare/conciliare l'energia del 23/11: l'utente ha autorizzato a rinunciarvi.
- Rischio aperto: se la wallbox è stata scollegata e un'altra auto ricollegata *interamente* durante una perdita BLE non osservata, la continuità non è dimostrabile. Non si devono dedurre sessioni certe da dati incompleti. Verificare questo caso sul campo.

### Correzione 2: potenza contrattuale vs DPM fisico
- La vecchia chiave interna `expected_dpm_kw` diventa visivamente **Potenza massima contrattuale** (*Contracted power limit*). Rimane per la compatibilità con le installazioni e viene usata **soltanto** per pianificatore/stabilizzatore.
- La lettura numerica `Limit house power set -DPM-` viene rimossa dai sette ruoli ESPHome richiesti. Il nuovo ruolo obbligatorio è `Charge Enabled`, conferma indipendente che il DPM fisico è a zero o positivo, ottenuta dal firmware.
- Smart Charging non imposta né ripristina mai il valore numerico del DPM. Quando previsto dalle funzioni esistenti invia solo `switch.turn_on` / `switch.turn_off` a `Start-Stop`; ESPHome resta proprietario del ripristino del proprio ultimo valore positivo e dei suoi fallback.
- Il controller richiede una lettura *successiva* al comando per confermare `Charge Enabled`, oltre ai controlli su BLE, cavo, telemetria e Shelly dove previsti.
- **Aggiornamento HA**: dopo passaggio da 0.9.x occorre associare il nuovo `Charge Enabled` in Opzioni → Wallbox; senza questa associazione il controller non viene avviato. Non dedurre entity_id.

### Collaudo richiesto prima di 1.0 stabile
1. Unit test Python 3.12/3.13: reset contatori in momenti diversi, più segmenti, stale al replug, pausa, riavvio e perdita BLE, archivio unico a unplug; vecchi record senza prova scartati.
2. Runtime Home Assistant 2026.11.1, Hassfest, HACS validation.
3. Test reale: DPM fisico 4,6 kW, valore contrattuale 4,4 kW, auto 4 kW, `Charge Enabled` valido; Start-Stop con conferma ON/OFF. **Verificare fallback `dpm_default` ESPHome, presente sul firmware pubblico a 6 kW**, prima di utilizzare Start/Stop reale con il nuovo DPM.
4. Controllare il distacco reale e la somma dello storico; recupero dopo spegnimento HA/BLE.
5. Rollback: ripristinare 0.9.2b1 e impostare il DPM effettivo e il DPM atteso al medesimo valore prima di riabilitare il controllo automatico.

### Aggiornamento ETA richiesto per la 1.0 (24/11)
- La proposta di Claude è stata adottata e resa più prudente: un solo rate domestico su un'ora proiettava il forno acceso su tutta la notte e talvolta spariva.
- Doppio regime: P_libera = mediana di almeno 20 campioni EV in NORMAL con casa ≤0,3 kW; ripiego provvisorio min(0,96 × base, potenza contrattuale - 0,2 kW). P_ora = Shelly EV ultimi 10 minuti, comprese pause; usata solo nei primi 30 minuti del futuro, poi P_libera.
- Energia residua: coefficiente kWh/% SOC appreso solo nella sessione e soltanto dopo almeno 5 punti SOC con Shelly continuo, esclusi gap e outlier, variazione massima ±15% rispetto al profilo. Nessun apprendimento permanente dopo una singola notte.
- Previsione in blocchi di 10 minuti, variazioni ordinarie limitate a ±15 minuti. Cambio auto, target o base ricomincia la previsione. Attributi diagnostici: qualità, potenza libera, recente e orario teorico a potenza libera.
- NON toccati il modello prudente estimate_ac_kw, il margine di partenza, il budget LIMIT, i comandi BLE né le soglie STRONG/MODERATE/quiet.
- Test dedicati di forecast e controller; replay iniziale mostra meno picchi durante carichi forti, ma nelle prime ore le previsoni restano incerte e i numeri di Claude non sono prova generale. Necessario il collaudo reale.
### Non introdotto in questa revisione
- Modifica manuale della potenza mentre è in LIMITED: criticità riconosciuta, non cambiata.
- ETA: restano rinviate l'analisi dei carichi per fascia oraria e la calibrazione persistente per automobile: servono più sessioni valide.
- Margine falsamente urgente dopo carichi domestici e margine ignoto dopo riavvio: da testare offline prima di modificare la policy.
- Nessun cambiamento al firmware ESPHome né a soglie STRONG/MODERATE/quiet di 15 minuti.

### Esito qualità automatica in preparazione RC3
- Una esecuzione completa del gate su main (commit 83008fb8cd674659120e55b1845ed98814befce1) ha superato Python 3.12/3.13, Home Assistant runtime, Hassfest e HACS; commit successivo ha corretto l'arrotondamento ETA vicino alla fine.
- Aggiunti test per campioni liberi esclusivamente in NORMAL, pause a zero potenza, apprendimento SOC senza gap, stima temporizzata e carichi temporanei.
- Il gate di pubblicazione deve nuovamente riuscire sul commit di release finale; nessun tag pubblico significa pubblicazione non dimostrata.
- Risultati di replay: nelle prime ore la stima può restare troppo ottimista poiché i futuri carichi e la vera energia AC/SOC non sono noti. Non assimilare il test offline di Claude a convalida generale.
### Correzione RC4 — archiviazione dopo ore in attesa del distacco
- Verificato che il firmware emette BLE Connection quando si connette, senza obbligo di ripubblicare lo stesso ON ogni due minuti. Anche Charging=OFF può essere invariato dalla fine della ricarica (es. 04:20) fino al distacco fisico (es. 08:30).
- Nella RC3 la verifica di freschezza a 2 minuti per questi stati stabili rischiava di scambiare una connessione sana per BLE offline, impedendo il salvataggio finale. In RC4 gli stati BLE/cavo/Charging della stessa epoca possono rimanere stabili; i contatori numerici continuano a richiedere letture sincronizzate recenti e il distacco necessita Charge State Cable Unplugged.
- Aggiunto test che invecchia artificialmente il timestamp dei flag di 4 ore e verifica che la ricarica sia archiviata una sola volta quando il cavo viene davvero scollegato.
- La release v1.0.0rc3 e stata pubblicata, ma va considerata superata: il prossimo candidato consigliato e v1.0.0rc4, solo dopo quality gate completo. Il collaudo fisico resta necessario.
### Stato
Implementazione su main autorizzata per questa occasione dall'utente. Verifica completa in corso; non dichiarare stabile fino ai test automatici e alla prova sul campo.

### Pubblicazione condizionata 1.0.0rc4 con ETA informativa
Tag previsto: `v1.0.0rc4`, prerelease. La GitHub Action `publish-rc` pubblica **solo se** hanno successo test Python (3.12 e 3.13), Home Assistant 2026.11.1, Hassfest e HACS. La pubblicazione non è una prova di funzionamento reale del DPM né di una sessione archiviata dalla wallbox; resta obbligatorio il collaudo fisico prima di chiamare la versione stabile.

**RC4 trigger:** commit con messaggio di release finale e gate automatico; eventuale tag pubblicato soltanto dopo tutti i quality checks. Nessun aggiornamento al firmware ESPHome. La nuova ETA a due regimi è stata ora implementata su main, ma non è ancora collaudata sul campo.

## RC5 — gate finale di pubblicazione
Il commit di release avvia nuovamente 276 test automatici (Python 3.12/3.13), Hassfest, HACS e runtime HA 2026.11.1. La prerelease viene pubblicata esclusivamente se tutti i job passano. La prova fisica del salvataggio dopo il distacco rimane da eseguire.

## 24 novembre 2026 — 1.0.0, archivio su cumulativi firmware ESPHome

- Autorizzata pubblicazione stabile 1.0.0 su main, senza RC. Il firmware di riferimento è Easywallbox---Esphome, commit cb3a802968286b21a83a2b22d6d21c314f202c0c (contatori pubblici cumulativi, reset dopo 60s di distacco confermato o 5 minuti senza telemetria dopo distacco già osservato). Non modificato il repository firmware.
- SessionArchive non calcola più delta o segmenti: conserva gli ultimi valori assoluti kWh/min, identificazione veicolo ed evidenza del distacco. Chiusura solo alla coppia di zeri valida dopo distacco, non al primo cable OFF. Una sola pubblicazione a zero non cancella la precedente lettura. Replug con totali ancora positivi annulla la chiusura. Perdita BLE da collegato non chiude; fallback accetta gli zeri ESPHome anche con BLE offline se c'era evidenza del distacco.
- Salvati data del distacco osservato e data del reset; qualità parziale per discontinuità o timeout. Nessun timer HA parallelo e nessun comando o sensore BLE aggiuntivo. Restano le soglie di archiviazione 0,2 kWh e 2 minuti.
- Persistenza con la chiave precedente e snapshot di sessione/righe nello stesso documento. Mantenute le righe completate valide; scartati i frammenti beta da reset grezzo; non migrato l'accumulatore RC5 ancora aperto (i nuovi valori hanno diversa semantica e sommarli sarebbe rischioso). Aggiornare con cavo scollegato e cumulativi a zero, backup HA prima. Eventuali discontinuità non osservabili non vengono ricostruite.
- Corretto il listener dell'archivio con @callback per eseguire aggiornamenti, task di salvataggio e notifiche nel loop HA. La mancanza del decoratore nelle versioni precedenti era una causa plausibile, non dimostrata, delle mancate registrazioni. Aggiunta prova nel vero HA Core: eventi di stato, primo unplug senza riga, reset indipendenti, archivio 5,2 kWh/83 min e persistenza dopo reload.
- Diagnostica firmware_session_closed e awaiting_firmware_reset, card aggiornata e cache bust versione 1.0.0. README descrive migrazione, semantica e rollback.
- ETA, margine prudente, controllo Start-Stop/Charge Enabled, gestione DPM e algoritmo NORMAL/LIMITED restano invariati rispetto alla RC5. Nessuna nuova funzione elettrica.
- Limite aperto: se HA perde completamente il distacco e l'azzeramento prima del nuovo collegamento, non esiste identificativo persistente della sessione chiusa nel firmware per recuperarla senza ambiguità. La perdita BLE o un reboot non provano l'effettivo scollegamento; eventuali progressivi anomali non vengono sommati. La precisione reale dei contatori ESPHome e i riavvii fisici richiedono ancora collaudo.
- Quality gate per 1.0.0: suite Python 3.12/3.13, Hassfest, HACS e HA Core 2026.11.1. Il job di pubblicazione stabile parte solo dal commit di release dopo tutti i controlli. Non dichiarare collaudato ciò che è stato soltanto simulato.
