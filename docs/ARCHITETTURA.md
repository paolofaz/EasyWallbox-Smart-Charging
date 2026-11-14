# Architettura EasyWallbox Smart Charging — rifondazione ispirata a evcc

**Data:** 2026-11-14  
**Stato:** M0, impostazione architetturale approvata; parametri e semantiche ancora da chiudere. **Nessuna implementazione nuova o test eseguito da questo documento.**

## Origine e perimetro

Questa integrazione Home Assistant nativa Python si ispira ai concetti di evcc (sessione, veicolo, piano di partenza, stima SOC), **senza porting integrale o attuatore evcc**. Studio di riferimento: evcc commit `6b1f9584286fd4ab9a702b1e77e5aede8e967300` e documento `EASYWALLBOX_EVCC_STUDIO_ARCHITETTURA_2026-11-14.md` della fonte di Progetto.

- Una sola EasyWallbox per installazione, veicoli configurabili 1..N; non vincolare il codice a Fiat o Kia.
- ESPHome rimane l'unico proprietario BLE; la wallbox mantiene il DPM attivo, che controlla i picchi elettrici. Il nuovo planner opera a scala di minuti.
- **v0.1 = sola simulazione**: nessun servizio o comando a wallbox, auto o DPM; niente nuovo controller attuativo. Lovelace dedicata e replay offline obbligatori.
- La 0.0.x sperimentale rimane recuperabile da Git; il codice esistente nel branch appena creato non è considerato un core da riutilizzare per inerzia.
- Non modificare `main`, `sviluppo-test`, firmware ESPHome, automazioni HA legacy, configurazioni HA o credenziali. Nessuna release per M0 o M1.

## Contratto logico: pipeline proposta

```text
ESPHome + Shelly + veicoli + preferenze
          |
SourceSnapshot (valore, unità, provenienza, timestamp, validità)
          |
SessionState (modo utente, fase, cause, titolarità della decisione)
          |
EnergyModel + DeadlinePlanner (funzioni pure)
          |
ProposedDecision (intenzione simulata, motivo, confidenza, prossima valutazione)
          |
Replay offline + dashboard Lovelace nativa (v0.1)
```

Il controller che invia e verifica comandi è un **componente futuro distinto**, non incluso nella v0.1.

### Sorgenti e qualità dati

- **Wallbox ESPHome:** auto/cavo, stato charging, connessione e freschezza BLE, guasti, richiesta `Charge power`, conferma `Power set`, stato DPM. Nessun sensore derivato confonde comando richiesto, conferma BLE o effetto reale.
- **Shelly:** ramo casa 1, ramo casa 2 e wallbox; misura AC del ramo wallbox distinta dalla telemetria ESPHome. Le topologie generiche ammesse dalla configurazione richiedono validazione della somma e delle unità prima dell'uso.
- **Auto:** profili 1..N con identificazione non ambigua, SOC ufficiale, collegamento, charging, target numerico della sessione, capacità utilizzabile configurata; limite interno auto, se disponibile, resta un dato distinto e **non è comandato**.
- **Preferenze:** modo, prossima partenza calcolata sul giorno della partenza e fuso, profilo feriale/weekend, eventuale deroga temporanea.
- Ogni dato porta sorgente, ora lettura, unità e qualità (valido, vecchio, mancante, incoerente). `unknown` e `unavailable` non equivalgono a zero o a OFF; due auto contemporaneamente candidate non diventano un'identità arbitraria.

Gli entity_id effettivi, l'affidabilità dei timestamp e le capacità utilizzabili richiedono verifiche live; non sono hardcoded.

## Macchine a stati: separare intenzioni e osservazioni

- Modo utente: `AUTO`, `MANUALE`, `PAUSA_UTENTE`. Il cambio di fase elettrica non cancella un comando esplicito dell'utente. Modalità e override sono proprietà di sessione.
- Fase sessione: `SCOLLEGATA`, `COLLEGATA`, `ATTESA`, `IN_CARICA`, `TERMINATA`, `INTERROTTA`, `DATI_INSUFFICIENTI`, sempre con un motivo esplicito.
- `ATTESA` è una proposta del planner, **non** una pausa manuale. `TERMINATA` per target non deve provocare riprese con cavo ancora inserito. `INTERROTTA` per stop auto/manuale non ammette retry ciechi.
- All'avvio/riavvio HA riconciliare stato e persistenza con gli ingressi disponibili, senza fingere un nuovo evento di collegamento, senza uscire da una pausa esplicita e senza assumere effetti elettrici non confermati.
- Le priorità precise di `Carica subito`, pausa utente, stop auto, deroga e intervento manuale su ESPHome sono ancora da specificare in M0 prima di implementare azioni future.

## Due calcoli differenti

1. **Piano di partenza**: `E_batt_kWh = max(0, target_soc - soc_auto) / 100 * capacita_utilizzabile_kWh`; `E_rete_kWh = E_batt_kWh / efficienza_ac_ipotizzata`; `durata_piano = E_rete_kWh / potenza_attesa_prudente_kW`; `ultimo_avvio = partenza - durata_piano - riserva`. I valori non sono garantiti: efficienza e potenza devono avere provenienza/assunzioni documentate.
2. **ETA alla potenza attualmente misurata**: `fine_eta = ora + E_batt_kWh / (potenza_ac_effettiva_kW * efficienza_ac_ipotizzata)` **solo** durante ricarica reale con lettura positiva, valida e fresca. Non usarla come previsione della notte quando DPM e carichi varieranno.

La potenza del piano non deriva da `4,4 kW - carico casa adesso`: deve rispettare il limite effettivamente confermato della wallbox e le capacità note/limiti del veicolo, prevedendo riduzioni DPM ragionevoli e segnalando incertezza. Non dedurre una capacità certa da un'unica sessione. Se la deadline è fisicamente irraggiungibile, segnalarlo esplicitamente.

Per target 100%: calcolare solo l'arrivo indicativo al 100% senza comandare stop SOC futuro; bilanciamento e completamento reale rimangono all'auto. SOC ufficiale e un'eventuale interpolazione da energia di sessione hanno provenienze distinte.

## Politica di pianificazione approvata a livello di principio

- **Non** hardcodare orari di cucina, lavastoviglie, né identificare singoli elettrodomestici. Il planner deve funzionare anche con collegamenti pomeridiani, notturni, weekend e partenze eccezionali.
- Se c'è ampio margine, si può attendere un calo **persistente** del carico domestico. L'attesa ha sempre una deadline e una prossima rivalutazione.
- Se il carico scende o il margine si restringe, proporre un inizio utile; quando si avvicina l'ultimo avvio ragionevole, privilegiare l'obiettivo di partenza e lasciare al DPM la gestione dei picchi.
- Una volta in carica, preferire la continuità e nessuna azione rispetto a inseguire carichi intermittenti; una limitazione DPM si osserva tramite la potenza reale e aggiorna il rischio di ritardo senza comandi HA frequenti.
- Gli schemi domestici ricorrenti sono **scenari di replay**, non schedulazioni obbligatorie o informazioni personali da pubblicare. Uno storico statistico dei consumi è un'eventuale fase successiva, **non parte della v0.1 approvata**.

## Output minimo e UI

Una `ProposedDecision` include almeno: sessione, modalità/fase, azione **solo simulata** (attendi / avvia consigliato / continua / nessun intervento / dati insufficienti), motivo principale, potenza e durata usate con provenienza, timestamp delle sorgenti, confidenza e prossima rivalutazione.

Lovelace v0.1 mostra in modo evidente **SIMULAZIONE — NESSUN COMANDO INVIATO**, veicolo, SOC ufficiale/target, partenza, energia residua, piano, ETA istantanea **solo quando disponibile**, motivo e qualità dati. Preferire card native e poche entità di riepilogo; nessun controllo attuativo o sensori duplicati.

## Verifiche M1 e chiusura M0

- M1: core Python puro, senza import Home Assistant e senza adapter attuativo; replay timestamp -> ingressi -> decisione -> motivo, anche con auto scollegata. Scenari T01-T30 dello studio, soprattutto doppia auto, SOC stale, restart, target 100%, pausa esplicita, DPM limitante, disconnessione, giorno feriale/weekend e DST.
- Scenario generico di prova: utilizzo intermittente di carichi elevati nella fascia serale/mattutina, carico prolungato notturno, auto connessa in orario non abituale. **Fixture sintetiche, non dati privati.**
- **Ancora aperto in M0:** riserva temporale; selezione/calibrazione della potenza prudente e del rendimento; soglie freshness e carico persistente; frequenza di valutazione; precedenze `Carica subito`/Pausa/Manuale; persistenza sessione e compatibilità di migrazione/rollback da 0.0.13. Gli orari 07:00/08:00 e 45 minuti sono esempi storici, non default approvati.
- Prima di qualunque modifica al codice esistente leggere file e test live del branch. Prima di M2 verificare API correnti HA, migrazione delle config entry e non concorrenza con automazioni legacy.

## Stato lavori

**14/11/2026:** branch `rifondazione-evcc` derivato dal commit `ab6b2b279e724ee0629aa80eaf7dfed64d3953d0` di `sviluppo-test`; documento di specifica M0 aggiunto. Nessuna nuova simulazione, test o installazione HA eseguita; 0.0.13 presente come codice storico, non validata come nuova architettura.
