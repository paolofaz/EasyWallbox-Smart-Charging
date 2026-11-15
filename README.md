# EasyWallbox Smart Charging

**Versione 0.1.0 — PRIMA RELEASE MARKETPLACE — SOLO SIMULAZIONE**

Custom integration Python per Home Assistant che simula la pianificazione di ricarica e uno stabilizzatore lento della potenza EV. Il DPM fisico della EasyWallbox resta attivo, autonomo e responsabile di picchi e sicurezza elettrica. **La 0.1.0 non invia alcun comando reale alla wallbox o alle automobili.** I pulsanti/selettori sono consigli virtuali, non interruttori elettrici.

<!-- ha-marketplace:exclude-start -->
## Installazione

**Home Assistant 2026.11 o superiore:** apri **Impostazioni → Marketplace → Add from link**, aggiungi il repository:

```text
https://github.com/paolofaz/EasyWallbox-Smart-Charging
```

Installa la versione **0.1.0**, riavvia Home Assistant e apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → EasyWallbox Smart Charging**. Non servono ZIP, HACS separato, Docker, codice ESPHome nuovo o modifiche a `configuration.yaml`.

Il repository non è ancora incluso nel catalogo pubblico, quindi si aggiunge una volta dal link. Su Home Assistant 2026.11 e successivi, il Marketplace sostituisce HACS.
<!-- ha-marketplace:exclude-end -->

## Funzionamento

- **Pianificatore**: legge SOC auto, target, partenza e capacità; propone quando attendere o partire. Gli orari feriali/weekend sono impostabili per auto.
- **Stabilizzatore**: legge soltanto i due Shelly di casa **esclusa la wallbox**; propone un limite EV virtuale stabile durante carichi intermittenti e un ripristino dopo quiete o quando il planner perde margine.
- **DPM**: resta sempre attivo e gestisce autonomamente i picchi rapidi. La simulazione non sostituisce alcuna protezione elettrica.
- **Modalità**: Automatica, Manuale, Pausa e Carica subito sono modalità di simulazione. Una Pausa nel selettore NON interrompe la ricarica reale; Carica subito NON la avvia.

## Configurazione

Il Config Flow permette di selezionare i sensori già presenti in Home Assistant: due Shelly EM dei consumi casa, il terzo Shelly dedicato alla wallbox, ESPHome **Car Connected**, **Charging**, **Telemetry Fresh**, **Charge power** (number in kW) e **Power set** (sensore kW). Configura uno o più veicoli con cavo collegato, SOC, target SOC facoltativo, capacità utile, rendimento, potenza sostenibile e orari di partenza. Nessun `entity_id` è fisso, quindi non è limitata a Fiat 500e o Kia EV3.

Il Config Flow crea un profilo nuovo: non è prevista la migrazione della vecchia 0.0.13. L'utente ha confermato che la precedente installazione è stata rimossa.

## Entità

Tre sensori: **sessione**, **pianificatore** e **stabilizzatore**, e un selettore **modalità simulata**. Le proposte `reduce`/`restore` non impostano la potenza reale. L'icona è inclusa in `custom_components/easywallbox_smart/brand/icon.png`; traduzioni IT/EN e Options Flow sono presenti.

## Qualità e limiti

**Verifiche completate:** 99 test offline e con mock HA su Python 3.12/3.13, validazione ufficiale hassfest e HACS/Marketplace. **Non ancora collaudato** su una Home Assistant reale: Config Flow, Recorder, selettore, runtime con Shelly/ESPHome/auto e riavvio. Quindi questa è una **prima release di prova in sola simulazione**.

Le soglie 1,5/1,0 kW, quiete 10 min, budget 25% dello slack e modello DPM 4,3 kW sono ipotesi interne al simulatore, **non tarature approvate** per altri impianti.

Nessuna modifica a firmware ESPHome, DPM e automazioni Fiat esistenti. Non inserire PIN BLE, credenziali, token, cronologie private o cartelle `.storage` nel repository.

**Approfondimenti:** [Note tecniche](NOTE_SVILUPPO.md), [Architettura M1](docs/ARCHITETTURA_M1.md), [Dashboard Lovelace](docs/LOVELACE.md), [Note release 0.1.0](docs/RELEASE_NOTES_0.1.0.md).

In caso di problemi puoi rimuovere l'entry di test da Dispositivi e servizi, disinstallare la custom integration da Marketplace e riavviare HA. Questo non cambia il DPM né le automazioni originali.
