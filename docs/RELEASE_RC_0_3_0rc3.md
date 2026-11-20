# EasyWallbox Smart Charging v0.3.0rc3 — correzione RC

**Prerelease per Home Assistant 2026.11+, ancora senza collaudo elettrico.**
Il controllo reale resta **OFF dopo ogni avvio/ricaricamento**.
Non modificare il firmware ESPHome e non attivare automazioni concorrenti.

## Correzioni principali

1. **Eliminata la "potenza AC media prudenziale" da configurare a mano.**
   La precedente versione la richiedeva erroneamente con default 2,4 kW.
   Il planner ricava ora la stima da una finestra temporale limitata di
   consumi domestici Shelly (esclusa la wallbox), limite DPM positivo
   configurato e, quando disponibile, storico della potenza EV misurata.
   Quando non ci sono dati sufficienti non inventa una previsione.
   Una partenza posticipata rimane posticipata: senza media affidabile,
   il cap EV configurato è usato solo come *limite superiore teorico*
   per verificare che non si oltrepassi l'ultimo avvio fisicamente possibile.
2. **Tutte le auto sono gestibili dopo la prima installazione.**
   Aprire Impostazioni → Dispositivi e servizi → EasyWallbox Smart
   Charging → **Configura/Opzioni** e scegliere **Modifica auto**,
   **Aggiungi auto** oppure **Rimuovi auto**. La modifica comprende
   nome, cavo, SOC, target fisso o da entità, capacità, rendimento,
   pulsante aggiornamento, timestamp e partenza feriali/weekend.
   L'ultima auto non può essere cancellata.
3. **Compatibilità con le configurazioni già salvate.**
   I profili della rc2 vengono riletti; il campo `planning_rate_kw`
   eventualmente presente nella vecchia configurazione è ignorato,
   non richiesto, e viene eliminato quando il profilo è salvato dalle
   Opzioni. Non modificare manualmente `.storage`.
4. **Nessun nuovo sensore Recorder.** Gli storici per il planner
   vivono solo nella memoria della custom integration e restano limitati.

## Aggiornamento dalla 0.3.0rc2

- Eseguire un backup di Home Assistant.
- Installare **v0.3.0rc3** dal Marketplace, con prerelease abilitate,
  e riavviare Home Assistant.
- Non eliminare la Config Entry e non rifare i profili: i valori attuali
  vengono mantenuti.
- Il controllo reale dopo il riavvio è OFF: verificare i sensori e
  le nuove voci delle Opzioni, poi procedere soltanto con prove supervisionate.
- Se si desidera cambiare i profili, farlo dalle Opzioni; il loro
  salvataggio ricarica l'integrazione e riporta Controllo reale OFF.
- La dashboard automatica non è ancora presente in questa prerelease;
  i controlli sono entità native di Home Assistant.

## Collaudo e rollback

La qualità CI include test Python 3.12/3.13, configurazione guidata
testata con voluptuous, Add/Edit/Delete dei veicoli, unit test
della stima automatica, Home Assistant hassfest e HACS validation.
Sono test software: **non certificano il comportamento elettrico**.

Per il rollback disattivare Controllo reale, verificare il DPM
dall'interfaccia ESPHome e ripristinare la rc2 se indispensabile.
Il firmware resta invariato. Leggere README e
`docs/CHECKLIST_COLLAUDO_RC.md` prima di abilitare i comandi reali.
