# EasyWallbox Smart Charging 0.3.0rc1 — PRE-RELEASE

**Home Assistant 2026.11+ · RC privata di collaudo supervisionato.**

Questa prerelease deriva esclusivamente dal branch `RC`.
Il branch `main`, la release 0.1.0 e il firmware ESPHome non vengono modificati.

## Cosa include

- Nuova custom integration nativa HA con configurazione grafica dei
  tre Shelly (rami casa e wallbox separati), dei controlli BLE ESPHome,
  delle Fiat/Kia, del SOC, dei target e degli orari di partenza.
- Johnny RC: forte/moderato, correzione 5/7, quiete 15 minuti,
  boost 4,0→4,2 **soltanto con margine ≤60 min** e isteresi 75 min.
- Riferimento DPM configurato (es. 4,4 kW) per la matematica;
  sensore DPM letto usato per la conferma dell'effetto elettrico.
- Parcheggio post-scollegamento **una sola volta** dopo 30 s con
  Shelly wallbox <30 W e cavo wallbox confermato OFF:
  `Start-Stop OFF` porta DPM a 0 A e verifica esito.
- Collegamento: attesa 20 secondi, refresh dati Fiat o Kia una volta
  (entrambe se auto non identificata), attesa dei nuovi dati reali,
  pianificazione partenza/override, 4,0 kW verificati e soltanto dopo
  `Start-Stop ON` quando occorre iniziare.
- Avvio posticipato, Manuale fino a fine sessione, Carica subito,
  Pausa gestione, override della partenza, dashboard Lovelace nativa.
- Laboratorio H24 indipendente: JSONL privati, zero comandi.
- Solo due sensori diagnostici a eventi, non aggiornati a ogni watt.
- Ripartenza e recupero conservativi, blocchi leggibili, nessun retry
  cieco di BLE/Start-Stop.

## Limitazioni e verifiche

**Non è ancora collaudata in una sessione elettrica reale.**
52 test offline, hassfest e validazione HACS/Marketplace hanno verificato
la logica isolata; la conferma delle sequenze BLE e dell'azione fisica
resta un test sul campo. Nessuna garanzia di raggiungimento del target
se il DPM riduce la potenza più del previsto.

Il controllo reale è **OFF al primo avvio, riavvio e reload**.
Non abilitarlo prima di aver verificato e disabilitato le automazioni
concorrenti. Il firmware deve avere già lo switch `Start-Stop`,
`Charge power` e il pulsante `Refresh data` funzionanti.
La vecchia config entry beta non è migrata automaticamente: creare
una nuova configurazione attraverso l'interfaccia grafica.

Durante il primo collaudo tenere i sensori DPM Active, Charge Enabled,
Limit house power set -DPM-, Power set, Charging e Shelly EV visibili.
Se qualcosa non torna, mettere il Controllo reale OFF e passare in
Manuale; riconciliare dal firmware ESPHome senza Start/Stop ciechi.

**Documentazione**
- README del branch RC: regole complete e significato dei comandi
- `docs/CHECKLIST_COLLAUDO_RC.md`: prove positive, negative e rollback
- `docs/LOVELACE_RC.yaml`: dashboard con segnaposto per i tuoi entity_id

## Installazione Marketplace

Da Home Assistant **Impostazioni → Marketplace**, aprire il repository
`paolofaz/EasyWallbox-Smart-Charging`, abilitare la preferenza
**Pre-release**, scegliere `0.3.0rc1`, installare e riavviare HA.
In **Dispositivi e servizi** rimuovere la vecchia entry di test prima
di configurare nuovamente EasyWallbox Smart Charging. Salvare
una copia dell'integrazione precedente per eventuale rollback.
