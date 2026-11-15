# EasyWallbox Smart Charging — nuova base M1

**Stato: CORE OFFLINE IN SOLA SIMULAZIONE. Non è una custom integration Home Assistant installabile.**
Nessun servizio, comando BLE, avvio/stop, scrittura wallbox/auto o modifica del DPM.

## Obiettivo

La wallbox conserva il suo DPM autonomo e sempre attivo, responsabile di picchi e sicurezza elettrica. La futura integrazione HA gestirà la sessione e la partenza. Un supervisore **lento** vede la sola potenza domestica senza EV (piano terra + primo piano): se carichi intermittenti persistono e il planner ha flessibilità, propone un limite EV stabile; dopo quiete propone di ripristinare **direttamente il limite precedente**. Se l'obiettivo di partenza rischia di non essere raggiunto, il planner fa rientrare la propria limitazione e lascia operare il DPM.

Il regolatore NON riconosce elettrodomestici, NON usa il totale da 5 kW, NON insegue i picchi con step continui, NON disattiva il DPM.

## M1 disponibile ora

- `custom_components/easywallbox_smart/core.py`: contratto input/output, `plan()` ed `evaluate()` puri, `NORMAL/LIMITED`, ownership virtuale, budget conservativo cumulativo, azioni e motivazioni spiegabili.
- `tests/test_core.py`: test di sessione, SOC, partenza, carichi intermittenti, quiete, budget, proprietà manuale, stop e dati mancanti.
- Parametri in `Config` **solo candidati da laboratorio**, non di produzione. Non trasferire il modello DPM a 4,3 kW ad altri impianti senza configurazione.
- Nessun `manifest.json`, `config_flow.py`, sensore HA, dashboard o release: volutamente non installabile.

### Test locali

```bash
python -m unittest discover -s tests -v
```

## Cosa resta da fare

1. Test ripetibili con eventi coerenti di veri Shelly/auto; nel replay storico un valore invariato può essere mantenuto come stabile su conferma dell'utente, ma una sorgente offline/non disponibile NON è lettura stabile. Il futuro adapter dovrà certificarne lo stato.
2. Raffinare la stima del budget con energia EV misurata e SOC che aggiorna lentamente (~15 min), senza sostituire mai il SOC ufficiale.
3. Costruire config flow con mappatura **configurabile** per 1..N auto, i tre Shelly, gli stati BLE/ESPHome, capacità, limiti e target; non hardcodare entity_id domestici. Per la prima installazione verificheremo con le due auto e gli Shelly già presenti.
4. Adapter HA read-only a eventi, timer solo in sessione, dashboard Lovelace **«SIMULAZIONE — NESSUN COMANDO»**, nessun Recorder per campione, test su HA reale e rollback dalla 0.0.13.
5. Solo in un successivo rilascio approvato, progettare attuazione/ack/riconciliazione, senza due proprietari dei comandi e senza modificare firmware o automazioni legacy prima di migrazione collaudata.

## Repositoy e sicurezza

Il nuovo branch `stabilizzatore-m1` nasce dal **commit iniziale di main contenente solo LICENSE**, non dai prototipi precedenti. I vecchi branch rimangono per ora come riferimenti storici separati; nessun merge su main. Vedere `NOTE_SVILUPPO.md`.

Non caricare storico puntuale privato dei consumi, dati `.storage`, credenziali, BLE PIN, MAC personali. La simulazione non dimostra una riduzione reale degli interventi DPM o del rischio di distacco.
