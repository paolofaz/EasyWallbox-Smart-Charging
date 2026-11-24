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

### Non introdotto in questa revisione
- Modifica manuale della potenza mentre è in LIMITED: criticità riconosciuta, non cambiata.
- ETA: confronto con proposta Claude del 24/11 (due potenze, apprendimento kWh/% SOC, intervallo di incertezza). Interessante, ma necessita replay su più sessioni e non deve influire sul margine prudente usato dalle decisioni.
- Margine falsamente urgente dopo carichi domestici e margine ignoto dopo riavvio: da testare offline prima di modificare la policy.
- Nessun cambiamento al firmware ESPHome né a soglie STRONG/MODERATE/quiet di 15 minuti.

### Stato
Implementazione su main autorizzata per questa occasione dall'utente. Verifica completa in corso; non dichiarare stabile fino ai test automatici e alla prova sul campo.

### Tentativo di pubblicazione 1.0.0rc1
Tag previsto: `v1.0.0rc1`, prerelease. La GitHub Action `publish-rc` pubblica **solo se** hanno successo test Python (3.12 e 3.13), Home Assistant 2026.11.1, Hassfest e HACS. La pubblicazione non è una prova di funzionamento reale del DPM né di una sessione archiviata dalla wallbox; resta obbligatorio il collaudo fisico prima di chiamare la versione stabile.
