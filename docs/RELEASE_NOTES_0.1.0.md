# EasyWallbox Smart Charging 0.1.0 — SOLO SIMULAZIONE

**Prima release Marketplace per installazione da zero.** Home Assistant 2026.11 o successivo.

> **ATTENZIONE: questa integrazione non comanda la wallbox.** Nessuna azione `Start`, `Stop`, `Carica subito`, `Pausa`, `reduce` o `restore` viene inviata fisicamente alla wallbox, a ESPHome o all'automobile. Tutte le decisioni sono simulate. Il DPM originale rimane attivo e indipendente.

## Novità

- Nuovo **Config Flow grafico** con selezione configurabile di due misuratori domestici Shelly, uno per la wallbox, telemetria ESPHome e profili per più auto.
- Pianificatore di partenza che valuta SOC, target, capacità, partenza, margine e raccomandazioni virtuali **attendere/avviare ora**.
- Stabilizzatore lento virtuale: `NORMAL/LIMITED`, carichi domestici intermittenti e ripristino del limite virtuale nel rispetto della partenza.
- Modalità utente **Automatica, Manuale, Pausa, Carica subito** tramite selettore HA, senza comandi reali.
- Tre sensori diagnostici di sessione, pianificazione e stabilizzatore; Options Flow per modificare target e orari di ogni auto.
- Icona BRAND, traduzioni IT/EN, controlli sui dati inattendibili, riavvio e ambiguità veicolo.

## Installazione Marketplace

1. In Home Assistant 2026.11+ apri **Impostazioni → Marketplace → Add from link**.
2. Aggiungi `https://github.com/paolofaz/EasyWallbox-Smart-Charging` come integrazione (se richiesto scegli tipo *Integration*).
3. Installa la **0.1.0** dal Marketplace, quindi **riavvia Home Assistant**.
4. Vai su **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → EasyWallbox Smart Charging** e seleziona le entità esistenti.

**Niente importazione della vecchia versione 0.0.13:** l'installazione è ex novo. Non copiare il codice a mano se usi il Marketplace.

## Avvertenze e limiti

- Questa è la prima release installabile; i test offline, con mock HA, hassfest e HACS validation sono superati, **ma il runtime sulla Home Assistant dell'utente non è ancora stato collaudato**.
- Parametri numerici del simulatore ancora da tarare sull'impianto reale: soglie casa, durata quiete, budget, modello DPM. La simulazione non garantisce il raggiungimento della partenza e non attua alcuna protezione elettrica aggiuntiva.
- La modalità **Pausa** nel selettore è soltanto una pausa del planner virtuale. L'auto può continuare fisicamente a caricare.
- Nessun firmware ESPHome, DPM, automazione Fiat o altra integrazione modificati. Non caricare backup, PIN BLE, credenziali o `.storage` in GitHub.
- Se qualcosa non funziona: rimuovi l'entry di test da Dispositivi e servizi, disinstalla la repository dal Marketplace e riavvia. La wallbox e i dispositivi originali non sono stati modificati.

Documentazione: [README](https://github.com/paolofaz/EasyWallbox-Smart-Charging#readme).
