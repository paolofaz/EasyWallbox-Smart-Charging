# Stima automatica potenza e consumi domestici universali — sviluppo v0.2.0b1

**Decisione utente del 15 novembre 2026**: non chiedere una potenza sostenibile in kW, perché il DPM può portare la carica a 2 kW di giorno e 4 kW di sera. La stima deve basarsi sulle misure reali e essere accompagnata dalla relativa provenienza. Non introdurre uno storico persistente da cinque sessioni in questa prima iterazione.

## Input, già presenti in ESPHome main (verificati)

- Shelly EM dedicato alla wallbox: potenza EV effettiva, W o kW, selezionato in `ev_power`.
- ESPHome `Session Energy`: contatore energia sessione kWh (protocollo AD `p[22]/10`), facoltativo.
- ESPHome `Session Duration`: durata sessione min (protocollo AD `p[23]`), facoltativo, da selezionare insieme a Session Energy.
- `Charge power` number e `Power set` sensor: limite richiesto/confermato **non sostituiscono** la potenza misurata.
- `Charging`, `Car Connected`, `Telemetry Fresh`: validità fisica e telemetrica distinta. I contatori vengono usati soltanto con telemetria valida e dati freschi.

## Strategia M4 simulata

1. Senza ricarica effettiva verificata: **nessuna potenza sostenibile osservata**. Il planner non presume che il limite nominale sia raggiungibile e non raccomanda di attendere sulla base di una media inventata. Se SOC, target e partenza sono attendibili, può consigliare virtualmente di avviare ora per ottenere una misurazione.
2. Con ricarica iniziata: misura Shelly EV attuale. Stima `shelly_instant`; NON è una previsione garantita della potenza futura.
3. Dopo almeno **30 minuti** e almeno due coppie crescenti e coerenti energia/durata nella **stessa** sessione: può ottenere la media `60 × session_kWh / session_duration_min`, poi la combina con la misura Shelly attuale: **65% corrente + 35% media**. I coefficienti sono *candidati* da validare con dati reali, non tarature garantite.
4. Se la misura è stale, mancante o nulla, **nessuna stima affidabile**; se i contatori sono incoerenti/azzerati, riparte il controllo di coerenza senza sommare sessioni diverse. Il solo valore di energia/durata non sostituisce lo Shelly corrente.
5. La stima viene aggiornata a eventi, senza polling BLE aggiuntivo e senza storici puntuali da salvare. Nel sensore pianificatore compaiono `estimated_charge_rate_kw`, `estimated_rate_source`, `wallbox_session_average_kw` e `rate_observation_minutes`. Non sono comandi e non sono garantite misure previsionali.

La wallbox e il DPM gestiscono come sempre il carico istantaneo; il supervisore lento usa il margine del planner e produce soltanto suggerimenti virtuali.

## Input domestici universali

- La prima schermata seleziona da **uno a più sensori domestici** `sensor`, ciascuno esposto in W/kW: `house_power_sources`. Il core somma le letture, rifiutando sensori duplicati, obsoleti o non numerici; non esiste più una distinzione obbligatoria per piano o marca.
- Il misuratore dedicato EV `ev_power` è separato e non entra mai nella somma casa.
- Le opzioni permettono di modificare le sorgenti e aggiungere/togliere i due contatori di sessione senza ricreare la voce.
- Una configurazione creata con Marketplace **0.1.0**, che contiene `house_downstairs` e `house_upstairs`, continua ad avviarsi: il coordinatore tratta quei due sensori come elenco iniziale e l'Options Flow può sostituirli. Nessuna migrazione della vecchia `0.0.13` e nessuna modifica manuale di `.storage`.

## Target SOC in GUI

- **SOC attuale**: lettura dell'auto.
- **Entità obiettivo SOC facoltativa**: *un numero percentuale di destinazione già esposto da HA*, per esempio il limite configurato nell'auto. Viene letto soltanto; non provoca scritture nell'auto.
- **Target SOC predefinito**: usato solo quando non è stata configurata alcuna entità obiettivo. Se un'entità configurata diventa `unknown/unavailable`, non si inventa un target sostitutivo.

## Stato / rischi ancora aperti

- v0.2.0b1 è **solo nel branch di sviluppo `stabilizzatore-m1`**, non una release pubblicata. Marketplace e `main` continuano a offrire la **0.1.0** invariata; nuova release solo con approvazione.
- ESPHome descrive i contatori come energia e durata di sessione, ma il loro comportamento preciso in stop/restart, reset all'inizio e eventuale riavvio BLE deve ancora essere osservato su HA reale. Verifica dei cambi di contatore e percentuale SOC durante due vere sessioni necessaria prima di tarare il modello.
- La media di sessione integra cambi DPM nel tempo e può reagire lentamente a transitori. L'algoritmo è una prima ipotesi, non una previsione garantita; il rapporto 65/35 potrà cambiare dopo dati reali.
- Nessun comando Start/Stop/limite/auto, niente telemetria aggiuntiva e niente persistenti storici di sessione in questa release.
