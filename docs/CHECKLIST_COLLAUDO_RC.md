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

## Test della nuova gestione SOC (prima senza comandi reali)

1. Aprire **Dispositivi e servizi → EasyWallbox Smart Charging →
   Dispositivi**. Deve comparire il dispositivo logico
   EasyWallbox Smart Charging con le entità associate, i due sensori
   collocati in diagnostica e **nessun duplicato** degli ID esistenti.
2. In **Configura → Modifica auto**, verificare che l'opzione
   **Stop a target SOC** sia inizialmente disattivata per entrambe
   le auto già configurate.
3. Per Fiat: target da entità HA esistente **oppure** target fisso
   80–100% con slider nativo a passi di 5. Non creare un secondo
   slider quando già esiste un `input_number` di target.
4. Per Kia: mantenere Stop a target OFF e lasciare che sia l'auto
   ad interrompere al limite impostato internamente; la RC deve
   osservare la fine e **non** emettere uno Stop né uno Start.
5. Prima di un test elettrico dello Stop Fiat, **disabilitare
   l'automazione legacy che scrive Start-Stop**. Non toccare
   le notifiche e gli eventi MQTT finché non si concorda
   la loro migrazione.
6. Con Fiat in carica, SOC sotto target e Stop attivato,
   nessuno Stop sulla wallbox. Vicino al target il refresh auto
   è al massimo ogni 20 minuti, non una sequenza veloce.
7. Dopo un refresh Fiat, verificare che il timestamp originario
   `last_info_update_at` sia realmente cambiato; se non cambia,
   **nessuno Stop**. Premere il pulsante non equivale a conferma.
8. Soltanto con SOC >= limite, cavo ON, Charging ON e Shelly
   positivo, il controller può richiedere **un solo** Start-Stop OFF.
   DPM confermato a 0 A, Charge Enabled OFF, Charging OFF
   e Shelly EV <30 W sono necessari per dichiarare fine carica.
9. Se manca un ACK BLE o il consumo EV resta sopra 30 W,
   blocco diagnosticato e **nessun retry**.
10. Finché la Fiat resta collegata, cambiare il target NON deve
    far ripartire la ricarica una volta fermata per SOC.

**Attenzione:** i primi test di carica reale devono essere
supervisionati. Disabilitare l'automazione legacy solo quando
la sostituzione è verificata; se la RC non è ancora collaudata
mantenere Controllo reale OFF.

## Rollback

Portare **Controllo reale su OFF**, selezionare Manuale,
controllare l'ultima conferma del DPM e fermare gli eventuali
controllori concorrenti. Ripristinare la release precedente e riavviare
Home Assistant. Una lettura DPM 0 A richiede verifica sul firmware;
non richiedere Start-Stop ON senza conoscere lo stato elettrico.

Questa procedura **non prova la sicurezza elettrica**. Nessuna
modifica al firmware, alle credenziali BLE o ai file `.storage`.
