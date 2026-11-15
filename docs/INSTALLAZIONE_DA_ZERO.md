# Installazione da zero — EasyWallbox Smart Charging (v0.1 simulazione)

**Aggiornato: 15 novembre 2026. Stato: prima installazione di prova su Home Assistant, NON release collaudata.** L'utente ha confermato che la vecchia integrazione 0.0.13 è stata rimossa. Non occorre alcuna migrazione: si crea una nuova configurazione dalla UI. La versione su `stabilizzatore-m1` è **rigorosamente read-only**; `Pausa`, `Carica subito`, `reduce`, `restore` e gli altri stati sono **proposte virtuali**, non attuazioni.

## 1. Prerequisiti

- Home Assistant con le entità ESPHome EasyWallbox, i due Shelly di consumo casa, lo Shelly dedicato wallbox e almeno un veicolo già visibili in **Strumenti per sviluppatori → Stati**.
- Assicurati che la vecchia integrazione *EasyWallbox Smart Charging* non compaia più fra le integrazioni configurate e che la vecchia directory `custom_components/easywallbox_smart`, se presente, non contenga file 0.0.13. Non cancellare automazioni Fiat o firmware.
- Per sicurezza crea prima un backup HA (Impostazioni → Sistema → Backup). Non condividere backup, credenziali o `.storage`.
- Il ramo `main` di questo repository è ancora storico e **non contiene la nuova integrazione**: in questa fase non installare da HACS usando il repository e il default branch. Usare il download manuale del branch di test.

## 2. Copia dell'integrazione

1. Apri [branch `stabilizzatore-m1`](https://github.com/paolofaz/EasyWallbox-Smart-Charging/tree/stabilizzatore-m1).
2. Su GitHub scegli **Code → Download ZIP**, poi estrai l'archivio.
3. Individua **soltanto** la cartella `custom_components/easywallbox_smart` dell'archivio.
4. Copia la cartella nella directory di configurazione della tua Home Assistant, ottenendo:

```text
/config/
  custom_components/
    easywallbox_smart/
      __init__.py
      manifest.json
      config_flow.py
      coordinator.py
      core.py
      session_policy.py
      departure_policy.py
      validation.py
      select.py
      sensor.py
      const.py
      sources.py
      strings.json
      translations/
      brand/
```

**Non** copiare l'intero repository direttamente in `custom_components`, non copiare i test, non modificare il firmware e non configurare script o container esterni. Riavvia Home Assistant.

## 3. Config Flow: associazione fonti dati

Apri **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → EasyWallbox Smart Charging**. La prima schermata richiede:

| Campo UI | Origine | Significato |
|---|---|---|
| Casa piano terra | Shelly EM casa, es. `sensor.assorbimento_sotto` da confermare | Potenza W/kW senza auto |
| Casa piano primo | Secondo Shelly EM casa, es. `sensor.assorbimento_sopra` da confermare | Potenza W/kW senza auto |
| Potenza EV | Terzo Shelly EM dedicato wallbox | Potenza effettiva W/kW, **non** totale casa |
| Wallbox cavo collegato | ESPHome **Car Connected** | Presenza reale del cavo, **non** semplice BLE Connection |
| Wallbox in carica | ESPHome **Charging** | Ricarica osservata, non comando Start |
| Telemetria aggiornata | ESPHome **Telemetry Fresh** | Validità della lettura BLE |
| Limite richiesto | ESPHome `number` **Charge power** | Massimo impostato/richiesto kW |
| Limite confermato | ESPHome `sensor` **Power set** | Massimo confermato dalla wallbox kW |
| DPM modello | Numero da confermare (4,3 kW è **solo candidato** per l'impianto di test) | Non modifica il DPM fisico |

I **tre Shelly devono essere differenti**. L'integrazione non usa il consumo totale comprensivo di auto per riconoscere carichi domestici. Le entità sono selezionate graficamente, senza hardcode.

La seconda schermata configura un'automobile per volta: nome, sensore **cavo collegato all'auto**, SOC, eventuale target SOC letto da HA, target predefinito, capacità utile in kWh, potenza sostenibile stimata, efficienza e partenza feriale/weekend. I valori precompilati **non** sono misure approvate: verifica capacità e limiti reali. Per Kia EV3 puoi selezionare il target impostato sull'auto, se esposto con unità percentuale; per Fiat 500e mantieni l'automazione SOC legacy già esistente e puoi configurare il target software disponibile in HA. Se scegli *Aggiungi un'altra auto*, ripeti per il secondo veicolo. Non inventare sensori che non esistono.

## 4. Cosa vedrai, e cosa controllare

L'integrazione crea **tre sensori** (sessione, pianificatore, stabilizzatore) e **un selettore modalità simulata**. Cerca le entità con `easywallbox_smart` nel registro entità; i loro ID finali dipendono dalla tua Home Assistant. Il messaggio **SIMULAZIONE — NESSUN COMANDO** deve essere visibile negli attributi.

- Senza cavo nessuna carica simulata è autorizzata e non si attiva lo stream dei due Shelly casa.
- Con auto collegata dopo un **riavvio HA**, il selettore può richiedere esplicita riconciliazione: scegli *Automatica* per avviare soltanto il ragionamento virtuale.
- In **Manuale** il planner non propone cambi automatici; in **Pausa** non propone di riavviare, ma una carica elettrica già attiva **non viene fermata**.
- **Carica subito** propone virtualmente una partenza immediata, senza inviare un comando Start.
- Il regolatore `NORMAL/LIMITED` propone eventualmente un unico cap e poi il ripristino. DPM e firmware operano autonomamente.
- Con SOC obsoleto, sensori `unknown` o ambiguo collegamento, il consiglio deve essere sospeso o dichiarare dati insufficienti; mai tradurre dati mancanti in zero.
- Controlla log Home Assistant e Recorder: il plugin **non** deve introdurre chiamate verso la wallbox o salvare una sequenza di potenze Shelly per ogni campione.

## 5. Se qualcosa non funziona: rollback

Per questa **nuova installazione**, non serve recuperare alcuna entry 0.0.13:
1. In **Impostazioni → Dispositivi e servizi** rimuovi l'entry *EasyWallbox Smart Charging* di test.
2. Rimuovi solo la cartella `/config/custom_components/easywallbox_smart` installata per questa prova.
3. Riavvia Home Assistant. Le integrazioni originali ESPHome/Shelly/Fiat/Kia e le automazioni preesistenti **non devono essere cambiate**.
4. Se sorgono problemi di configurazione HA indipendenti da questa integrazione, usa il backup del punto 1; non modificare manualmente `.storage`.

La prova non è ancora avvenuta sul tuo Home Assistant: **hassfest e i test fake-HA non equivalgono al collaudo runtime**. Riporta eventuali errori di log ripuliti da token, PIN, IP privati non necessari e dati personali.

## 6. Prima della pubblicazione

Nessuna release pubblicata e nessun merge su main. Soglie di 1,5/1,0 kW, quiete 10 min, budget 25% dello slack e modello DPM 4,3 kW restano **parametri interni candidati**. Le eccezioni temporanee di partenza non sono ancora nella UI. L'obiettivo della prova è verificare affidabilità della simulazione con le fonti reali, non certificare una risposta elettrica.
