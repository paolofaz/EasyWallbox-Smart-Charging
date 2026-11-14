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
- Una volta in carica, preservare la continuità, ma **simulare anche un limite massimo adattivo a scala di minuti** quando un picco attendibile suggerisce margine insufficiente. Il DPM resta il controllo rapido; il supervisore non lo sostituisce né insegue ogni accensione di una resistenza. La logica adattiva richiede collaudo per dimostrarne il beneficio rispetto a DPM-only.
- Gli schemi domestici ricorrenti sono **scenari di replay**, non schedulazioni obbligatorie o informazioni personali da pubblicare. Uno storico statistico dei consumi è un'eventuale fase successiva, **non parte della v0.1 approvata**.


## M0 — Regolatore adattivo supervisionato dal planner (14/11, proposta di taratura)

**Requisito confermato dall'utente:** non basta scegliere l'avvio: durante la ricarica occorre limitare, quando utile, picchi domestici ripetuti e **ripristinare automaticamente** la potenza, sfruttando i periodi di basso consumo. Non creare una regola per singolo elettrodomestico. Questa funzione è da simulare in v0.1 e non è un'autorizzazione ai comandi reali.

- **Segnale di ingresso:** anche **un solo picco attendibile** può giustificare una riduzione facoltativa, se il margine alla partenza la consente. Non usare un picco aggregato senza verifiche di unità, freschezza e allineamento temporale dei tre Shelly: differenze di timestamp possono creare apparenti superamenti. Il grafico recorder filtrato non prova durata/cause di ciascun picco.
- **Ragionamento quantitativo:** considerare separatamente potenza totale, potenza della casa senza EV, ramo wallbox misurato, `Charge power` richiesto, `Power set` confermato, qualità BLE, DPM e distanza dal prossimo obiettivo. Il comando ipotetico limita **il massimo** richiedibile, non determina l'assorbimento reale e non sostituisce la regolazione del DPM.
- **Prima riduzione proposta per simulazione:** `p_cap = min(p_cap_precedente, p_ev_misurata_al_picco - max(0, p_totale_al_picco - soglia_guardia) - margine_potenza)`, arrotondata verso il basso ai passi ESPHome consentiti; applicare solo se i campioni sono coerenti, il cap riduce realmente il limite e non cade sotto il minimo configurabile. Questa formula è una **ipotesi di replay**: un transitorio non può essere ricostruito perfettamente da campioni non sincronizzati. Nessun DPM OFF. Un profilo che non consente riduzione utile produce `nessuna azione / verifica`, non una pausa automatica non autorizzata.
- **Ridiscesa:** un nuovo picco attendibile durante il cap può rendere opportuna una nuova riduzione, senza aspettare obbligatoriamente 10 minuti; un intervallo minimo tra comandi e la verifica delle conferme impediscono raffiche BLE e retry ciechi. I tempi numerici restano da calibrare.
- **Risalita:** dopo una finestra iniziale *proposta* di circa 10 minuti, risalire soltanto se anche i consumi domestici **senza EV** sono stabilmente bassi e i dati sono affidabili: l'assenza di allarmi con cap basso non dimostra che la lavastoviglie sia finita. Risalire in passi, rivalutando dopo ciascuno; un nuovo picco causa arretramento e raffreddamento. Finestra più prudente con ampio margine, tentativi di risalita più precoci se la deadline si avvicina ma i vincoli lo consentono.
- **Veto planner:** ogni proposta di cap deve ricalcolare la durata residua alla potenza realisticamente ottenibile e lo `slack` dopo una riserva. Se il cap comprometterebbe la scadenza, **non applicarlo** come ottimizzazione facoltativa, segnalando il rischio e lasciando DPM/protezioni a gestire il carico. Un pericolo elettrico reale non viene ignorato a causa del piano: protezioni prioritarie sempre.
- **Proprietà del comando futuro:** solo il controllore autorizzato può ripristinare un limite che esso stesso ha temporaneamente ridotto; mai sovrascrivere una limitazione manuale, l'intervento di un'altra automazione, pausa utente o stop auto. In v0.1 output soltanto `cap_proposto_kw`, `motivo`, `slack_dopo_cap`, `prossima_valutazione` e qualità dei segnali.
- **Validazione:** replay comparativo con (a) DPM-only, (b) cap fisso di 2 kW, (c) cap adattivo simulato. Metriche: superamenti previsti/registrati, durata, kWh veicolo, cambi di limite, deadline raggiunta o no. Un replay con campioni filtrati non permette di dichiarare che i picchi sotto-secondo sono stati eliminati.
- **Fondamento evcc:** riutilizzare concetti del planner e separazione del load-management, **non** il controllo rapido evcc: documentazione ufficiale `https://docs.evcc.io/en/features/loadmanagement/` sconsiglia sovrapporre il suo controller a uno interno; quello di EasyWallbox rimane DPM. Il planner evcc conserva gli obiettivi di partenza; il veto di slack sulla **riduzione facoltativa** è un adattamento specifico EasyWallbox, non una funzione evcc attestata come identica.

**Da approvare/calibrare in M0:** soglia picco, margine kW, TTL e sincronizzazione Shelly, cap minimo utile, entità dei passi (il firmware usa 0,2 kW secondo fonte storica), intervalli tra riduzioni e aumenti, finestra di carico domestico basso, riserva di tempo, precedenze utente/legacy. Le soglie 4,4 kW e superamenti oltre 5 kW sono valori del contesto utente, non limiti di sicurezza universali. Test hardware successivi necessari per verificare l'effetto fisico.


### Parametri iniziali **proposti per il replay** (non approvati come default)

- Config Flow futuro: `P_available_kw` (potenza impianto che l'utente ritiene continuativamente disponibile; esempio 4,4), `P_trigger_kw` (soglia di intervento preventivo; esempio 5,0), distinti dal DPM hardware che resta sempre attivo. Selezione esplicita dei sensori `P_house_excluding_ev = sum(P_house_sensors)` e di `P_wallbox_meter` senza doppio conteggio. La soglia trigger **non** è un limite di sicurezza. Entrambi i parametri devono essere validati.
- Un solo evento di `P_total >= P_trigger_kw` può avviare la valutazione **se** le misure sono recenti, coerenti nel tempo e provengono da sensori corretti. Non dedurre il picco da somma di campioni asincroni senza controlli. Se manca la conferma dei dati, sola diagnosi. Il recorder filtrato non equivale a flusso completo di misure.
- Cap candidato: `floor_to_step(P_available_kw - P_house_at_peak_kw - 0.2 kW, 0.2 kW)`, mai superiore al precedente massimo di sessione autorizzato, mai applicato come richiesta sotto il minimo configurabile (attualmente 1,4 kW, step 0,2 nel firmware main verificato 14/11). Esempio: 4,4 − 2,1 − 0,2 = 2,1 -> 2,0 kW; nessuna pretesa di azzerare tutti i transitori. Se il cap risultasse troppo basso, lasciare al DPM la protezione rapida e segnalare che il cap normale non basta; non fare Stop senza una decisione futura autonoma.
- Monitorare il totale per rilevare singoli picchi; per la **risalita** usare consumi della casa esclusa EV. Dopo una prima permanenza proposta di **10 minuti** con ampio slack, valutare ogni **1 minuto** l'andamento domestico. Se è sceso stabilmente, aumentare al massimo di **0,4 kW ogni 3-5 minuti**; se resta alto, valutare comunque un cap intermedio proporzionato anziché imporre una soglia binaria di 1 kW (es. da 2,1 a 1,2 kW di casa implica 3,0 kW staticamente teorici). Tornare fino al limite originale di sessione, non superarlo.
- Nuovo picco attendibile durante la risalita: ricalcolare riduzione e, se lo slack lo consente, riportare il cap più in basso; introdurre cooldown anti-oscillazione. Un ulteriore comando non parte senza valutazione di un precedente comando pendente, conferma e stato reale. Non spostare il DPM né l'interruttore di pausa.
- Il planner valuta il **costo energetico di una riduzione temporanea**: `E_penalty_kWh = max(0, P_expected_without_extra_cap - P_expected_with_cap)*hold_hours`, ed esamina l'effetto sulla deadline e sulla riserva, **non** presume che il cap resti fino al mattino. Il controllo rivaluta il rischio se la riduzione deve persistere. Se lo slack di sicurezza è insufficiente (da definire quantitativamente), non applicare riduzioni discrezionali e osserva il DPM; nessuna deroga ai vincoli elettrici.
- `P_house <1 kW` può essere utile come indizio di rientro, ma non come unica soglia fissa. Prova con stima del massimo domestico su una breve finestra e conferma con misure reali: resistenze intermittenti possono spegnersi temporaneamente e riaccendersi. Un controllore lento non promette di anticipare i picchi sotto-secondo.
- In caso di modifica manuale del limite ESPHome, priorità all'utente: il futuro controller rinuncia al proprio ripristino automatico; in v0.1 ogni output è solo previsione. Non cambiare `Charge power` con step 0,1 in firmware senza un beneficio dimostrato; lo step attuale 0,2 è sufficiente per i test preliminari.
- **Da misurare**: distribuzione temporale dei picchi reali, allineamento timestamp Shelly, reazione DPM e potenza EV, numero di comandi simulati, kWh persi/recuperati e target raggiungibile. Questi valori sono candidati per fixture, non configurazione operativa approvata.

## M1 — Zero scritture da campioni e comportamento inattivo (vincolo 14/11)

**Requisito approvato:** quando non è in corso una ricarica elettrica, EasyWallbox Smart Charging non deve raccogliere i campioni puntuali Shelly, aggiornare continuamente sensori diagnostici, scrivere file, né generare nuovi eventi di storico ad alta frequenza. Le entità Shelly/ESPHome esistenti continuano a operare normalmente e il Recorder di HA rimane governato dalla configurazione dell'utente; la nostra integrazione non può disattivare le registrazioni generate da altri componenti.

- `SCOLLEGATA` / fuori sessione: il regolatore è inattivo, niente ascoltatori Shelly ad alta frequenza, buffer svuotato e nessun timer periodico del regolatore. Rimane **soltanto** un ascoltatore minimale dei cambi di stato wallbox/collegamento per riconoscere l'inizio della sessione, senza polling BLE aggiuntivo.
- `COLLEGATA/ATTESA` ma carica non partita: il **planner** può valutare occasionalmente SOC, orario di partenza e fotografia dei carichi correnti per proporre l'avvio (non deve perdere questa capacità), ma il **regolatore di potenza** è fermo e non campiona/storicizza continuamente. La distinzione tra collegamento e carica elettrica sarà verificata in M2 prima del wiring.
- `IN_CARICA` confermata: abilitare ricezione delle sole entità Shelly configurate (puntuali, escluse dal Recorder dall'utente), costruire combinazioni coerenti con timestamp e conservarle **solo in un deque limitato in RAM**, massimo 20 minuti e 1200 punti. Finestra prudente di 5 minuti, attesa massima tra campioni 60 s, freschezza 60 s: numeri interni candidati, da tarare con eventi Shelly veri; nessun salvataggio su file o su DB. Un sensore che non cambia ma ripubblica uno stato deve essere osservato correttamente; la futura sottoscrizione a `state_reported` sarà filtrata per entità e usata solo se necessario.
- Ricarica terminata/stop/sessione chiusa, o disconnessione: togliere listener ad alta frequenza, cancellare buffer e non pubblicare in loop stati di riepilogo. Un eventuale aggiornamento **una tantum** per rappresentare la chiusura della sessione è distinto da un monitor periodico; discuterne il Recorder nella v0.1.
- **Debito tecnico individuato:** nella 0.0.13 storica `sensor.py`, `Monitor.refresh` chiama `async_write_ha_state` su sette entità ogni 2 minuti, anche da inattivo. Questa logica è **da sostituire in M2**: il solo nuovo modulo puro M1 non modifica né risolve da sé tale comportamento. Non distribuire il nuovo branch come versione certificata prima del test di inattività.
- Nessun `async_write_ha_state`, `hass.bus.async_fire`, logging per singolo campione, `open()`, database, sessioni statistiche o chiamate ai dispositivi nel core M1. I test devono coprire inattività, assenza di raccolta, svuotamento, finestre incompletamente coperte, dato obsoleto, picchi nella finestra, sorgenti incoerenti e memoria limitata.

### Profilo storico facoltativo futuro, senza AI nella v0.1

- Leggere in futuro, *solo se utile ai test e senza nuova raccolta*, la storia o le statistiche dei **sensori filtrati già presenti nel Recorder**: stimare per fascia e giorno feriale/weekend potenze tipiche e frequenza di carichi elevati. Valutare affidabilità ed entità già registrate prima di attivarlo; dati filtrati non restituiscono i picchi mancanti.
- Un modello AI non è necessario per statistiche di base; l'obiettivo di partenza e i dati reali conservano priorità. Nessun logger quotidiano autonomo, nessuna raccolta quando non si carica, nessun profilo domestico persistito dalla nostra integrazione nella v0.1.
- In assenza di storico esistente: niente previsioni inventate; il planner rimane prudente e reattivo.


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
