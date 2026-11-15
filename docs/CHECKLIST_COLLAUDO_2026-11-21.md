# Primo collaudo M4 in sola simulazione — sabato 21 novembre 2026

**Contesto:** il 15/11 l'utente ha indicato che probabilmente non ricaricherà l'auto fino a sabato 21/11. Questa checklist è una **preparazione**, non un test già eseguito. Il software non modifica lo stato elettrico né invia comandi. Nessun test va effettuato aprendo una sessione di ricarica appositamente prima del previsto.

## Già verificabile senza auto in ricarica

- Installazione e configurazione grafica su una Home Assistant di prova, dopo la pubblicazione autorizzata della versione M4; **non** installare manualmente il branch di sviluppo sopra la release Marketplace 0.1.0.
- Selezione dei sensori casa con 1, 2 o più entità W/kW che non includono la wallbox e sensore Shelly EV separato. Valori mancanti non devono essere sommati come zero.
- Fiat 500e e Kia EV3: target SOC da **entità HA**, non da valore fisso (salvo scelta esplicita dell'utente). Cambiare un valore di target *solo se si tratta di un'entità software di test*, mai il limite reale dell'auto per fare prove.
- Verificare in Stati di HA che le entità siano `sensor`, `number` o `input_number` e riportino una percentuale fra 1 e 100. Annotare soltanto i nomi delle entità necessari alla configurazione, non backup o credenziali.
- Con auto scollegata, nessuna nuova raccolta continua Shelly da parte dell'integrazione e nessun comando BLE aggiuntivo.

## Quando partirà una ricarica già prevista

1. Rilevare soltanto `Car Connected`, `Charging`, `Telemetry Fresh`, SOC, target, potenza Shelly wallbox e i due contatori ESPHome `Session Energy` (kWh) / `Session Duration` (min).
2. **Primi minuti:** la stima deve avere fonte `shelly_instant`; non deve utilizzare un limite impostato come potenza realmente sostenuta e non deve fingere un campione storico.
3. **Dopo 30–60 minuti:** con contatori di sessione validi, crescenti e abbastanza recenti, la fonte può diventare `mixed_session_mean`; confrontare la potenza stimata con la potenza Shelly e con `60 × kWh / minuti`. Non dedurre la potenza futura dai soli valori medi.
4. Verificare se i contatori ripartono da zero in caso di nuova sessione, pausa, Stop/Start o riavvio ESPHome. **Non eseguire Stop/Start forzati soltanto per il test.**
5. In presenza di `unavailable`, contatori che si azzerano, SOC mancante o cavo ambiguo, il planner deve segnalare dati insufficienti; non creare nuovi comandi o nuovi cambi di cap reali.
6. Se si modifica dall'interfaccia il target reale per esigenze normali dell'auto, verificare che la simulazione riceva il nuovo valore e non utilizzi la percentuale fissa eventualmente salvata in una vecchia configurazione.
7. Controllare `estimated_charge_rate_kw`, `estimated_rate_source`, `wallbox_session_average_kw`, `required_minutes`, `slack_minutes` e la data di partenza; non confondere una proposta di avvio/pausa con azione reale.
8. Controllare Recorder e log per eventuali aggiornamenti eccessivi, eccezioni Python, timestamp stantii e flussi BLE indesiderati. Non condividere PIN, token o intera cartella `.storage`.

## Criteri di accettazione prima di autorizzare una release successiva

- Test offline, hassfest e HACS passati sul commit pubblicato.
- Config Flow e Options Flow funzionanti su HA reale, inclusi due veicoli e target entità distinti.
- Nessuna scrittura su ESPHome, wallbox, auto, Shelly e DPM.
- Consumo casa = somma corretta dei sensori selezionati, senza includere lo Shelly EV.
- Session Energy/Duration affidabili oppure fallback dichiarato a sola potenza Shelly, senza media inventata.
- Conferma che il planner non autorizza un'attesa con dati SOC/target/potenza insufficienti.
- Ripristino documentato della release `0.1.0` attraverso Marketplace se necessario. Non manipolare `.storage` manualmente.

La checklist serve a confrontare **osservazioni** e **proposte simulate**. Non è una procedura per testare la sicurezza elettrica o provocare distacchi del contatore.
