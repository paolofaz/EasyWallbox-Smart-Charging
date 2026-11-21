# Checklist RC — primo collaudo supervisionato

**Questa è una custom integration che può inviare comandi elettrici reali**.
Il DPM hardware ESPHome/wallbox rimane attivo. L'integrazione non sostituisce
le protezioni elettriche e non è ancora collaudata su un'auto reale.

## Prima dell'aggiornamento

1. Backup Home Assistant. Non modificare manualmente `.storage`.
2. Installare la **versione RC corrispondente al tag** da Marketplace con
   prerelease attive; riavviare HA. La Config Entry precedente è conservata.
3. Verificare in **Configura → Wallbox**:
   - sensori domestici 1..N, Shelly EV separato;
   - sensori ESPHome cavo, Charging, Telemetry Fresh, DPM Active, Fault,
     Charge Enabled, Command status, DPM positivo/zero confermato,
     Charge power richiesto/riscontrato, Start-Stop e Refresh data;
   - collegare il binary sensor **Connection BLE**, consigliato;
   - DPM positivo riferimento (es. 4,4 kW), limite EV ordinario 4,0 kW,
     boost 4,2 kW.
4. **Controllo automatico reale** nelle Opzioni resta inizialmente **OFF**
   per chi aggiorna da RC precedenti; abilitarlo soltanto dopo avere
   disabilitato tutte le automazioni concorrenti.
5. Se utilizzi Stop SOC Fiat nella nuova integrazione, rimuovere
   preventivamente il comando Start-Stop dall'automazione Fiat legacy.
   Conservare le notifiche/MQTT soltanto senza doppio controllo.
6. Nel dispositivo logico EasyWallbox Smart Charging controllare che
   siano spariti i vecchi pulsanti e lo switch «Controllo reale»;
   **restano** Modalità Automatico/Manuale, Avvio posticipato,
   Inizia non prima delle, Auto pronta entro, e i sensori di stato.
   Nessuna duplicazione di entity_id Shelly, ESPHome o target SOC.

## Test senza comandi elettrici

- Con wallbox **spenta e Connection BLE OFF**, lo stato deve essere
  «Wallbox non disponibile», senza tentativi di comando né polling BLE.
  Quando riaccendi la wallbox e Connection torna ON, verificare letture
  coerenti; l'integrazione non va ricaricata manualmente.
- Cavo scollegato per ore: OFF resta legittimo e non diventa
  `cable_or_vehicle_ambiguous` solo perché il sensore è invariato.
- Con auto riconosciuta deve compilarsi «Auto pronta entro» dall'orario
  feriale/weekend del **giorno di partenza**; modificarlo nella sessione,
  verificare il ricalcolo e scollegare: deve tornare vuoto. Il default
  salvato per l'auto non deve cambiare.
- Nessun nuovo sensore per Shelly watt, DPM o cavo. Avviso ricarica
  cambia solo quando cambia il messaggio significativo. Fine prevista
  ha granularità di 10 minuti, non countdown al secondo.

## Test avvio posticipato (senza riavvi ciechi)

1. Alle **20:00**, selezionando **19:00** la prossima occorrenza
   sarebbe domani alle 19:00 (23h): lo switch ON deve essere
   **rifiutato**, senza inviare Start-Stop OFF. Avviso ricarica
   segnala che l'ora è fuori dalla finestra di **12 ore**.
2. Alle 20:00, selezionare 01:00 significa **domani 01:00**:
   richiesta valida. Orario e data assoluta vengono persistiti.
3. Se l'auto **sta già caricando**: una sola richiesta Start-Stop
   OFF (DPM 0 A), con ACK BLE, Charge Enabled OFF, Charging OFF
   e Shelly EV <30 W. Se la conferma manca, blocco e **nessun retry**.
4. Se il planner reputa necessario iniziare alle 00:15 per essere
   pronti alle 08:00, ma il posticipo è fissato alle 01:00,
   **non anticipare**. Mostrare l'avviso di rischio.
5. All'ora selezionata, con auto e dati verificati, preparare
   e confermare **4,0 kW** (o base configurata), poi un solo
   Start-Stop ON. Confermare DPM positivo e Charging/Shelly.
6. Lo switch Avvio posticipato rimane ON finché **Charging non
   è realmente confermato**. Non spegnerlo solo perché è passata
   l'ora. Dopo la ripresa confermata va OFF automaticamente.
7. In caso di scollegamento reale durante attesa, lo switch torna
   OFF e non resta programmato per l'auto successiva.
8. Annullare posticipo mentre DPM 0 A è già confermato e posseduto
   dalla RC: può riprendere dopo le stesse verifiche, senza adottare
   pause poste da altre automazioni.
9. Riavviare HA in ambiente isolato mentre è **pausata una sessione**
   confermata e salvata: proprietà recuperabile solo con stessa auto,
   stesso appuntamento, BLE/DPM0/Charging OFF/Shelly <30 W. Con
   dati discordanti, nessun comando di ripresa.

## Test in carica e fine

- Johnny/algoritmo stabilizzatore: varia solo **number.Charge power**,
  carichi forti/moderati, LIMITED, ritorno dopo 15 min di quiete,
  boost soltanto con urgenza e regole 60/75.
- Kia con stop gestito dall'auto: **Stop SOC integrato OFF**, nessuno
  Stop/Start automatico se la Kia ha già raggiunto il proprio target.
- Fiat con Stop SOC integrato esplicitamente abilitato, automazione
  legacy esclusa: refresh dati recente, un solo Start-Stop OFF a target,
  verifica fisica e nessuna ripresa nella stessa connessione.
- Dopo ON→OFF di cavo e Shelly <30 W per 30 secondi, una sola
  richiesta Start-Stop OFF di parcheggio, se i dati sono affidabili.
- Manuale non ferma elettricamente la carica. Lo switch ESPHome
  rimane utilizzabile per gli interventi dell'utente.

## Rollback

Disabilitare il controllo automatico nelle Opzioni (con reload),
verificare sul firmware ESPHome lo stato DPM e Start-Stop, quindi
ripristinare il precedente tag dal Marketplace e riavviare.
**Non premere Start-Stop ON alla cieca** per recuperare una ricarica
interrotta. Annotare le letture BLE e Shelly nella diagnosi.
