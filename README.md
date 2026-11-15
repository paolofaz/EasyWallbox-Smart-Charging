# EasyWallbox Smart Charging

> **Sviluppo M2 — 15 novembre 2026.** Il branch `stabilizzatore-m1` contiene una custom integration Home Assistant in versione preliminare `0.1.0b1`, **SOLO SIMULAZIONE**. Config Flow e sensori sono stati codificati, ma l'installazione su Home Assistant reale e il comportamento elettrico NON sono stati collaudati. **Non è stata pubblicata alcuna release.**

## Perché esiste

EasyWallbox Smart Charging aiuta a preparare una ricarica EV per il SOC obiettivo e l'ora di partenza. Il suo *stabilizzatore lento* propone un massimo di potenza EV temporaneamente più basso quando la **casa senza wallbox** ha consumi elevati e intermittenti, per ridurre inutili ritorni al massimo del DPM. Il cap è unico per episodio; dopo quiete torna direttamente al limite originario, oppure viene ritirato prima se la partenza è a rischio. **Il DPM originale resta sempre attivo e gestisce tutti i picchi elettrici.**

La prima versione non controlla nulla: tutti gli stati e i limiti sono **virtuali**. Non vengono eseguiti `switch.turn_on/off`, `number.set_value`, comandi BLE o servizi delle automobili. Nessun polling BLE nuovo.

## Stato attuale: base M2 in sviluppo

- `core.py`: planner e supervisore deterministici `NORMAL/LIMITED`, budget e ownership **solo simulati**.
- `config_flow.py`: configurazione grafica di due Shelly domestici, uno Shelly wallbox, telemetria ESPHome, limite richiesto/confermato e **1..N automobili**. Gli ID sono selezionabili e non hardcodati.
- `coordinator.py`: lettura a eventi HA e timer puntuali, non un monitor a intervallo fisso. Lo stream dei due Shelly casa è seguito soltanto durante la ricarica effettivamente osservata; nessun campione viene salvato.
- `sensor.py`: tre entità sintetiche — sessione, piano, stabilizzatore — con attributi diagnostici, pubblicate soltanto quando cambia il riepilogo. Non duplica le potenze Shelly.
- `translations/it.json` e `en.json`: interfaccia italiana e inglese.
- `brand/icon.png`: icona 256×256 conforme al percorso HA locale delle custom integration dal 2026.3, disponibile per la prossima release.
- `docs/LOVELACE.md`: dashboard di esempio con card native e dicitura **SIMULAZIONE — NESSUN COMANDO**.

**Non ancora implementato nella GUI**: modifiche dei profili tramite Options Flow, modalità Manuale/Pausa/Carica subito, eccezioni temporanee e il planner completo di avvio/attesa. L'adapter M2 attualmente propone cap soltanto quando la carica è già attiva. Non installare come versione approvata.

## Configurazione prevista

I tre Shelly sono distinti: piano terra + primo piano costituiscono `P_casa`; lo Shelly della wallbox serve a verificare potenza EV e energia effettiva, **mai per innescare il cap**. L'integrazione seleziona sensori di cavo/SOC/target per ciascuna auto e legge `Charge power` (richiesto), `Power set` (confermato), `Charging` e `Telemetry Fresh` da ESPHome. Un valore `unavailable` non diventa zero e non autorizza nuovi cap.

I parametri `1,5 / 1,0 kW`, `10 minuti`, budget `25%` dello slack, DPM modello `4,3 kW`, rendimento e potenza sostenibile sono **ipotesi di simulazione**, non taratura elettrica di produzione. Il Config Flow richiede che capacità, potenze, sensori e orari siano esplicitamente confermati prima dell'uso; le precompilazioni sono soltanto esempi.

### Attenzione alla vecchia 0.0.13

La nuova configurazione M2 **non è compatibile automaticamente** con la config entry della vecchia 0.0.13. Non aggiornare sopra una installazione esistente prima di aver definito e verificato una migrazione o una reinstallazione con backup. Il codice controlla la compatibilità e rifiuta le config entry mancanti, senza eliminarle né modificarle. Nessuna automazione Fiat SOC o mattutina viene toccata.

## Test e sicurezza

- `python -m unittest discover -s tests -v` — **23 test** (15 M1 + 8 M2), passati su GitHub Actions con Python 3.12 e 3.13 alla verifica del 15/11/2026.
- `python -m compileall -q custom_components/easywallbox_smart` per verificare la sintassi di tutti i moduli.
- I test automatici NON sostituiscono hassfest, verifiche GUI Config Flow, prove idle/Recorder, test su HA reale, replay delle sette sere e simulazioni di reboot/assenza dati.
- Non pubblicare cronologie puntuali private, account auto, PIN BLE, token, dati `.storage` di Home Assistant o credenziali.

## Sviluppo e roadmap

Questo branch deriva dal commit iniziale `main` che conteneva soltanto `LICENSE`. I branch storici restano separati e non sono stati fusi. README e diario distinguono ciò che è codificato, testato offline e ancora da collaudare.

La v0.1 **sola simulazione** richiede il completamento del planner di avvio/attesa, una GUI di modifica, verifica dell'adapter su Home Assistant e della dashboard prima della pubblicazione. Il controllo reale sarà progettato **solo dopo autorizzazione**, con DPM sempre attivo e un unico proprietario software dei comandi. Vedi `NOTE_SVILUPPO.md` e `docs/ARCHITETTURA_M1.md`.
