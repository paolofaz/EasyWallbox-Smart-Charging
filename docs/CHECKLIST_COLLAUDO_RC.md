# Checklist di prima installazione e collaudo supervisionato

Questa checklist si riferisce alla **Release Candidate reale**. Nessuna
funzione di laboratorio è installata.

## Prima dell'installazione

1. Eseguire un backup di Home Assistant.
2. Disabilitare le automazioni legacy che comandano gli stessi
   `Charge power` e `Start-Stop`. Non bastano due interruttori
   visivamente ON/OFF per dimostrare l'assenza di altri scrittori.
3. Verificare sul dispositivo ESPHome che il DPM sia **attivo** e che
   Start-Stop OFF→DPM 0 A e ON→ripristino DPM positivo funzionino.
4. Conservare una copia della vecchia integrazione, senza modificare
   manualmente `.storage`.
5. Verificare la **versione effettivamente caricata**, non il solo tag
   GitHub: la vecchia configurazione aveva `house_downstairs`,
   `house_upstairs`, `target_default`, `sustainable_kw`. La RC
   deve invece mostrare **Sensori potenza domestica (1..N)**,
   **Target fisso/da entità** e **Potenza prudenziale per il planner**.

## Configurazione

- Selezionare liberamente uno o più sensori domestici con unità W/kW,
  senza includere la wallbox. Selezionare separatamente lo Shelly EV.
- Selezionare tutte le conferme ESPHome (cavo, Charging, Telemetry Fresh,
  DPM Active, Fault, Charge Enabled, DPM set, Power set, Command status)
  e le due entità di comando (Charge power number, Start-Stop switch).
- Configurare DPM positivo di riferimento (tipicamente 4,4 kW),
  limite EV ordinario (tipicamente 4,0 kW) e boost (tipicamente 4,2 kW).
- Per ogni auto scegliere SOC, cavo, capacità utile, rendimento,
  orari e **un solo target**: percentuale fissa oppure entità HA.
  La potenza prudenziale per stimare i tempi non è un comando EV.
- Il refresh dati auto viene richiesto al massimo una volta a cavo ON
  (dopo 20 s). Il pulsante non vale come dato aggiornato.
- Dopo il riavvio verificare che **Controllo reale sia OFF**.

## Collaudo a step

1. Con cavo scollegato all'avvio HA, non deve partire alcun comando.
2. Monitorare la disconnessione da una sessione nota e verificare
   sensore wallbox OFF + Shelly EV <30 W per 30 secondi.
   Solo in controllo reale abilitato può partire un singolo
   `switch.turn_off`; confermare DPM 0 A e Charge Enabled OFF.
3. Collegare la vettura, aspettare 20 s e controllare che l'aggiornamento
   richiesto riguardi la vettura riconosciuta, oppure entrambe quando
   ancora ignota. Nessun loop di refresh.
4. Con refresh riuscito, verificare SOC, target, energia residua,
   partenza e ultimo inizio utile. Senza dati attendibili
   **nessun avvio**.
5. Con avvio posticipato attivo, la wallbox deve restare a DPM 0 A
   fino all'ora consentita. Alla partenza, il valore Charge power deve
   essere confermato al limite ordinario prima di Start-Stop ON.
6. Durante Charging confermato, nessun `switch.turn_on/off`
   automatico: soltanto eventuali `number.set_value`.
7. Provare le riduzioni lente con carichi domestici reali e
   verificare che sia il DPM fisico a occuparsi dei picchi.
8. Provare modalità Manuale, ritorno ad Automatico allo scollegamento,
   target raggiunto, SOC obsoleto, errore BLE, DPM differente,
   cavo in stato `unknown` e riavvio con DPM 0 A.
   Vietati retry ciechi.

## Rollback

Portare **Controllo reale su OFF**, selezionare Manuale,
controllare l'ultima conferma del DPM e fermare gli eventuali
controllori concorrenti. Ripristinare la release precedente e riavviare
Home Assistant. Una lettura DPM 0 A richiede verifica sul firmware;
non richiedere Start-Stop ON senza conoscere lo stato elettrico.

Questa procedura **non prova la sicurezza elettrica**. Nessuna
modifica al firmware, alle credenziali BLE o ai file `.storage`.
