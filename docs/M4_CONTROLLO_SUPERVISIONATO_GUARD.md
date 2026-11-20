# M4 — Guard del controllo supervisionato (20/11/2026)

**Stato: primo modulo di sicurezza puro, non collegato a Home Assistant.**
La beta 0.2.0b5 resta in sola simulazione. Nessun comando reale, nessuna nuova release.

## Architettura

1. Johnny V2 (shadow_v2.py) propone cap teorici con auto sintetica sempre in carica. Non conosce budget di sessione, identità auto o consenso.
2. Il planner reale dovrà calcolare SOC, target, scadenza, margine e budget; il preflight non li inventa.
3. control_guard.py verifica la coerenza delle osservazioni e della proprietà del limite: produce solo **blocked**, **no_change** oppure **offer** (proposta che necessita di approvazione).
4. Un futuro adapter HA, ancora assente, sarà l'unico responsabile di autorizzazione, invio, ACK via ESPHome, conferme elettriche, rate limit, timeout e persistenza minima.
5. Il DPM fisico resta attivo e autonomo per i transitori rapidi. Nessuna modifica al firmware o alla pausa DPM = 0 A.

## Regole fail-closed del preflight

- Richiede sessione univoca in ricarica effettiva, modo AUTO e permesso derivante dal planner; Manuale, Pausa, Carica subito, RECONCILE sono bloccati.
- Richiede BLE online, telemetria valida, assenza di fault, DPM attivo e Shelly EV affidabile.
- DPM reale confermato deve coincidere con la configurazione verificata, non con un semplice modello virtuale.
- Lo slider Charge power richiesto e Power set confermato devono coincidere dopo la quantizzazione firmware in decimi di ampere.
- Un primo cap deve essere inferiore al limite già confermato. Le correzioni successive e il ripristino necessitano di un record di proprietà confermata e immutata.
- Ripristino solo al valore originario memorizzato, non a un massimo hardcoded.
- Proposte a step nominali EV di 0,2 kW dal minimo 1,4 kW, da riconfermare live prima di ogni controllo.
- Dopo restart il record recuperato richiede sempre riconciliazione e approvazione esplicita; non viene mai imposto un restore automatico.

## Limitazioni ancora bloccanti

- Il modulo non importa Home Assistant, non invia BLE, non chiama servizi, non scrive file e non è importato dal coordinatore attuale.
- LimitLease è un contratto di dati, **non uno storage persistente** o prova di comando. Nessuna persistenza è stata implementata.
- Il solo session_id della simulazione corrente non garantisce unicità attraverso i reboot; serve una sessione identificata e persistita senza collisioni.
- Il futuro adapter deve validare **per ogni sorgente** timestamps, unità, freschezza e coerenza; la data unica dello snapshot non è sufficiente.
- Nessuna verifica effettiva di effetto elettrico, timeout, conferma Shelly, consumo reale o semantica del comando ESPHome. Nessuna funzione Start/Stop è stata aggiunta.
- I log definitivi shadow_v2_amps_2026-11-20.jsonl non risultano allegati: impossibile validare le soglie o le correzioni della beta.

## Prossimi traguardi

1. Analisi dei JSONL finali e confronto fra pressione teorica, carichi Shelly, quantizzazione e numero di eventi.
2. Revisione della policy V2 e veto del planner, soprattutto per urgenza della partenza e budget.
3. Contratto di persistenza di sessione/ownership con prova di recupero dopo riavvio, manual override, disconnessione BLE e carica conclusa.
4. Adapter HA in modalità fake/test, e solo successivamente approvazione esplicita per un collaudo supervisionato con comandi reali. Verificare prima i pattern API correnti di Home Assistant e i servizi ESPHome esposti.
5. Evitare conflitti con le automazioni Fiat SOC e riduzione mattutina prima di qualsiasi attivazione.

**Test:** 15 casi unittest locali del nuovo guard superati. Su commit c2910b1 risultano riusciti anche tutti e quattro i workflow GitHub Actions (offline checks, Home Assistant integration validation, Marketplace/HACS validation, shadow test package). Nessuna validazione del controllo reale su HA o hardware. Rollback elettrico non necessario: il nuovo modulo è inattivo e non cambia le impostazioni della wallbox.
