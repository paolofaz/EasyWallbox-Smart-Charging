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
### Stato
Implementazione su main autorizzata per questa occasione dall'utente. Verifica completa in corso; non dichiarare stabile fino ai test automatici e alla prova sul campo.

### Pubblicazione condizionata 1.0.0rc3 con ETA informativa
Tag previsto: `v1.0.0rc3`, prerelease. La GitHub Action `publish-rc` pubblica **solo se** hanno successo test Python (3.12 e 3.13), Home Assistant 2026.11.1, Hassfest e HACS. La pubblicazione non è una prova di funzionamento reale del DPM né di una sessione archiviata dalla wallbox; resta obbligatorio il collaudo fisico prima di chiamare la versione stabile.

**RC3 trigger:** commit con messaggio di release finale e gate automatico; eventuale tag pubblicato soltanto dopo tutti i quality checks. Nessun aggiornamento al firmware ESPHome. La nuova ETA a due regimi è stata ora implementata su main, ma non è ancora collaudata sul campo.
