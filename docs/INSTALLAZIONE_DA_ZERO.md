# Configurazione EasyWallbox Smart Charging — versione M4 in sviluppo

**15 novembre 2026.** La versione installabile tramite Marketplace è attualmente **0.1.0** (su `main`, già pubblicata). Questa pagina descrive il Config Flow **0.2.0b1 in sviluppo**, *non ancora pubblicato*: le nuove schermate compariranno soltanto in una release successiva autorizzata. Non installare copie manuali del branch per anticipare un aggiornamento Marketplace.

## Primo avvio tramite Marketplace — dopo una futura release

1. In HA 2026.11+ aggiungere il repository `https://github.com/paolofaz/EasyWallbox-Smart-Charging` da **Impostazioni → Marketplace → Add from link**.
2. Installare la release futura quando effettivamente pubblicata, riavviare Home Assistant.
3. Aprire **Impostazioni → Dispositivi e servizi → Aggiungi integrazione → EasyWallbox Smart Charging**. Se esiste già una entry creata dalla 0.1.0, non eliminarla: il nuovo codice riconosce il mapping precedente e permette di aggiornare le fonti da **Opzioni**.
4. Eseguire una verifica in sola lettura prima di valutare eventuali ulteriori funzioni.

## Config Flow aggiornato: consumi domestici ed EV

| Campo | Che cosa scegliere |
|---|---|
| **Consumi domestici — uno o più sensori** | Selezionare uno o più sensori `sensor` che coprano i consumi domestici **senza auto**, in W o kW. Vengono sommati; evitare duplicazioni e sensori che già riportano il totale |
| **Potenza wallbox** | Shelly EM che misura **solo** la ricarica auto, separato da tutti i sensori domestici |
| **Session Energy (facoltativo)** | Sensore ESPHome `Session Energy`, in **kWh**, del firmware EasyWallbox |
| **Session Duration (facoltativo)** | Sensore ESPHome `Session Duration`, in **minuti**: selezionare insieme a Session Energy o non selezionarli entrambi |
| **Wallbox cable connected** | ESPHome `Car Connected` (non `Connection` BLE) |
| **Wallbox Charging** | ESPHome `Charging` |
| **Telemetry Fresh** | ESPHome `Telemetry Fresh` |
| **Charge power requested** | Numero ESPHome `Charge power` (kW) |
| **Power set confirmed** | Sensore ESPHome `Power set` (kW): limite confermato, **non** potenza effettiva |
| **DPM model** | Parametro numerico **solo per simulazione**, da non confondere con una modifica del DPM fisico |

Per la prima installazione della casa con 3 Shelly, selezionare i due Shelly domestici nella prima voce e il terzo Shelly dedicato alla wallbox nella seconda. Per una casa con un solo sensore domestico totale *senza EV* ne basta uno; con tre rami domestici ne puoi selezionare tre.

## Scheda auto

Richiede nome, sensore cavo, SOC corrente, **target SOC predefinito**, capacità utile, rendimento ed orari di partenza feriale/weekend. **Non chiede più potenza sostenibile manuale**.

- **Entità obiettivo SOC (facoltativa):** un sensore o numero percentuale che contiene *il target impostato nell'auto o in Home Assistant*, per esempio 80%. Non è la misura del SOC attuale e non viene comandata.
- Se non configuri l'entità obiettivo, il planner usa il target fisso inserito nella scheda. Se l'entità obiettivo esiste ma diventa `unknown`, il planner non inventa un valore sostitutivo.
- I due veicoli hanno schede e partenza indipendenti; il coordinatore riconosce una sola auto per volta sulla wallbox fisica.

## Da dove viene la potenza di pianificazione?

- Al primo avvio della ricarica: **Shelly wallbox** (potenza effettiva osservata). Una misura isolata non garantisce che quella potenza resti costante per ore.
- Dopo almeno 30 minuti, con contatori di sessione disponibili e verificati in almeno due progressioni: stima combinata 65% potenza corrente / 35% energia sessione divisa durata. Percentuali ancora da testare.
- Senza potenza osservata, non assumere 4 kW come potenza futura; il planner può suggerire virtualmente di iniziare, anziché un'attesa basata su numeri inventati.
- Un target SOC già raggiunto viene riconosciuto anche senza stima di potenza. Se lo Shelly EV è assente/stale o ESPHome e Shelly discordano, il sistema mostra dati insufficienti.

Tutte le modalità **Automatica, Manuale, Pausa, Carica subito** sono *solo simulate*; il sistema non avvia o interrompe fisicamente l'auto e non scrive valori su ESPHome. Il DPM originale mantiene le protezioni.

## Modificare le fonti in una installazione già esistente

Da **Dispositivi e servizi → EasyWallbox Smart Charging → Opzioni**: scegliere **Sensori consumi e contatori sessione** per modificare l'elenco dei misuratori o i due contatori, oppure **Parametri veicolo e orari**. Le nuove impostazioni ricaricano il coordinatore in sola lettura. Le entry 0.1.0 con due sensori casa `house_downstairs`/`house_upstairs` rimangono leggibili; **non** modificare `.storage` a mano.

## Limiti e rollback

Prima di usare la nuova versione creare un backup HA. In caso di errore, tornare alla release Marketplace stabile precedente. Nessun test runtime sulla HA reale è ancora stato svolto per la versione M4: controllare GUI, Recorder, reset dei contatori tra sessioni, stale SOC, sessione sospesa e tempi di riavvio. Non inviare dati privati, PIN BLE o backup in GitHub.

Dettagli tecnici in [Stima automatica e consumi universali](STIMA_AUTOMATICA_E_CONSUMI_UNIVERSALI.md). Una futura release richiede test e autorizzazione esplicita.
