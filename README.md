# EasyWallbox Smart Charging

Custom integration Python per **Home Assistant** per pianificare la ricarica di **veicoli configurabili da 1 a N** (inclusi Fiat 500e e Kia EV3), utilizzando stati ESPHome, SOC e sorgenti di potenza configurabili (Shelly, ESPHome o altri sensori Home Assistant).

> **Stato: anteprima di pianificazione read-only v0.0.12, ancora precedente alla v0.1 completa.** Espone stime di partenza/termine, potenza domestica e scenari dimostrativi per le auto scollegate. **Non invia comandi alla wallbox o alle auto** e non dispone ancora della dashboard completa.

## Sicurezza e separazione delle responsabilità

- Il firmware ESPHome rimane proprietario della comunicazione BLE.
- Il **DPM della wallbox rimane sempre attivo** e gestisce autonomamente picchi e limiti elettrici; **mai disattivarlo**. Lo **switch di pausa ricarica** è lo Start-Stop ESPHome: quando usato nelle future fasi di controllo, richiede una pausa impostando il **limite DPM a 0 A**, senza spegnere il DPM. Lo stato dello switch da solo non dimostra che l'erogazione elettrica si sia arrestata.
- L'integrazione legge solo stati Home Assistant configurati, con listener e controllo periodico dell'obsolescenza; **non invia servizi, comandi BLE o controlli elettrici**.
- L'automazione Fiat per il limite SOC e quella di riduzione mattutina della potenza **restano attive** fino a una migrazione futura verificata.
- Nessuna credenziale, PIN BLE o file `.storage` va pubblicato.

## Branch e versione

- `main`: stabile, **non modificare senza autorizzazione esplicita**.
- `sviluppo-test`: unico branch per lo sviluppo iniziale.
- `0.0.11`: aggiunge la media di potenza necessaria entro la partenza, indipendente dai consumi domestici correnti; distingue esplicitamente lo scenario del carico costante da una previsione futura. Conserva il fix dei sensori ON/OFF di 0.0.10. Restano le diagnosi e la lettura indipendente dei sensori di casa introdotte nella 0.0.9. La **v0.1** aggiungerà un planner più completo e Lovelace dedicata, sempre senza comandi.
- Le versioni di prova `0.x` vengono pubblicate come **release GitHub normali**, ma sono **software sperimentale e non stabile**. I tag puntano ai commit verificati di `sviluppo-test`, senza modificare `main`. Nessuna compatibilità con HA reale è ancora certificata.

## Installazione tramite Marketplace (release di prova)

Dopo che la GitHub Action di pubblicazione ha confermato la release `0.0.12`:

1. In Home Assistant 2026.11+ aprire **Impostazioni → Marketplace → Aggiungi da link**.
2. Inserire `https://github.com/paolofaz/EasyWallbox-Smart-Charging`. La registrazione di repository personalizzati richiede l'autorizzazione GitHub in sola lettura.
3. Selezionare la **release normale** `0.0.11` quando viene proposta. Non occorre abilitare lo switch **Pre-release**.
4. Installare la release `0.0.12`, **non il commit di `main`**. Da **Dispositivi e servizi**, aggiungere EasyWallbox Smart Charging e verificare le tre schermate di configurazione.

> **Attenzione:** `main` contiene soltanto `LICENSE`. La release punta all'esatto commit di `sviluppo-test`. **Il branch predefinito `main` non contiene ancora `hacs.json` né l'integrazione: il Marketplace potrebbe quindi non riuscire a riconoscere il repository durante l'aggiunta da link.** Se il repository non viene accettato, riportare l'errore e non installare il fallback di `main`.

**Installazione manuale alternativa, solo in caso di problemi con Marketplace:** scaricare l'archivio della release `0.0.12` da GitHub e copiare `custom_components/easywallbox_smart/` nella directory di configurazione HA. Per questa prima milestone non cambia alcuna automazione.

<!-- ha-marketplace:exclude-start -->
Link alle [release GitHub](https://github.com/paolofaz/EasyWallbox-Smart-Charging/releases).
<!-- ha-marketplace:exclude-end -->

Il requisito indicativo dichiarato per il Marketplace è **Home Assistant 2026.11.0+**; la versione effettivamente installata e l'esito del test sono ancora da verificare. **Non è necessaria alcuna configurazione YAML**.

Il Config Flow prevede: (1) sensori wallbox, (2) **uno o più veicoli configurabili**, (3) scelta del metodo di misura elettrica. A ogni veicolo si assegna **nome, sensore SOC, sensore cavo collegato, eventuale sensore ricarica, capacità utilizzabile e obiettivo SOC abituale**. Non richiede un sensore del limite impostato nell'auto. Dopo ogni veicolo, la procedura chiede se aggiungerne un altro.

Le Opzioni permettono di gestire i veicoli e cambiare la **topologia energetica** senza reinstallare l'integrazione. Per salvare premere **Salva modifiche**. La schermata di configurazione **non invia comandi**.

**Migrazione 0.0.1 → 0.0.3:** se avevi già completato la configurazione vecchia, occorre inserire almeno un nuovo profilo nelle Opzioni; i valori batteria sconosciuti **non vengono inventati**. Se invece ti eri fermato prima della fine, configura da zero con il nuovo flusso.

Tutti i campi sono facoltativi **solo in questa pre-alpha**, per consentire di creare l'entry mentre si raccolgono gli entity_id. Una mappatura incompleta non sarà ritenuta valida per il planner delle prossime milestone. Gli entity_id vengono selezionati nella GUI, non scritti nel codice. Le selezioni potranno essere aggiornate dalle **Opzioni** dell'integrazione. Non sono presenti switch o pulsanti per inviare comandi.

## Verifiche di questa pre-alpha

Controlli offline (non richiedono Home Assistant):

```bash
python -m unittest discover -s tests -v
```

Sono verifiche statiche di sintassi, manifest, traduzioni e assenza di alcune chiamate di comando. **Non equivalgono a un test del config flow eseguito in Home Assistant, né a hassfest/HACS action.** Prima di pubblicare e installare su impianti reali servono test aggiuntivi.

### Rollback

In sviluppo, disabilitare/rimuovere l'integrazione da *Dispositivi e servizi* e rimuovere la directory `custom_components/easywallbox_smart/` copiata manualmente. Nessuna automazione esistente o configurazione ESPHome viene cambiata. Per ripristinare il codice usare un commit precedente del solo branch `sviluppo-test`.

## Roadmap concordata

- **v0.1 — simulazione**: validazione/qualità dati, identificazione auto, energia e tempi, scadenza, raccomandazione spiegabile, sensori, test e **dashboard Lovelace dedicata**.
- **v0.2 — supervisione (solo previa autorizzazione)**: controllore unico e comandi sicuri con conferma.
- **v1.0 — automazione (solo dopo collaudo e consenso)**: gestione completa della sessione, eccezioni, modalità manuale, pausa e Carica subito.

**Decisione SOC (aggiornamento 12/11/2026):** ogni veicolo ha un obiettivo **abituale** configurabile nelle Opzioni. La dashboard v0.1 mostrerà un solo obiettivo effettivo, eventualmente modificabile **per la sessione corrente**; alla sessione successiva tornerà all'abituale. **Non esiste «Escludi obiettivo».** Se il target HA è inferiore a 100%, al suo raggiungimento la logica futura **potrà valutare** una pausa attraverso lo **switch di pausa ricarica** (ESPHome Start-Stop), soltanto dopo verifica delle condizioni e autorizzazione delle funzionalità attuative. Se il target è **100%**, il planner stima energia e tempo fino al 100%, ma **non aziona lo switch di pausa ricarica per SOC**, anche se l'auto dichiara 100% e continua a gestire le celle. Non riattiva nemmeno una sessione fermata manualmente. Il limite interno dell'auto non viene letto o modificato. In v0.1 **nessun comando reale**; la logica della sessione e la dashboard sono ancora da implementare.

La dashboard Lovelace è **parte obbligatoria della v0.1**, non un accessorio opzionale. La progettazione e le schermate previste sono in [docs/LOVELACE.md](docs/LOVELACE.md). Si partirà dalle card native HA; eventuali card frontend personalizzate andranno motivate e approvate prima di aggiungere codice JavaScript.

Per attività, verifiche e limiti vedi [NOTE_SVILUPPO.md](NOTE_SVILUPPO.md).

## Processo di release di test

Ogni nuova versione pubblicabile richiede **un cambio esplicito** del campo `version` in `custom_components/easywallbox_smart/manifest.json` e la creazione di `docs/releases/<versione>.md`. Un workflow GitHub Actions sul branch `sviluppo-test` esegue i test statici, rifiuta versioni non `0.x` o tag preesistenti privi di release, e crea una **GitHub release normale** dal commit corrente. Per la release esistente `0.0.1` aggiorna soltanto la classificazione senza alterare il tag. Non pubblica su `main`, non fa merge, non crea PR. Non creare una release di un commit non testato.

Le vecchie release `0.x` verranno riesaminate **dopo il rilascio 1.0**, conservando le versioni necessarie per rollback e migrazione; cancellazioni non automatiche.

## Compatibilità Marketplace

La struttura `custom_components/easywallbox_smart/`, il manifest con `version`, le traduzioni `en.json`/`it.json` e `hacs.json` sono una **predisposizione** per il Marketplace Home Assistant (ex HACS). Le release di prova normali sono disponibili, ma **non** è stata richiesta l'inclusione nel catalogo ufficiale.

## Documentazione tecnica ufficiale

- [Marketplace: pubblicare una custom integration](https://contributors.home-assistant.io/marketplace/guides/integrations/)
- [Config flow](https://developers.home-assistant.io/docs/core/integration/config_flow/)
- [Options flow](https://developers.home-assistant.io/docs/core/integration/options_flow/)
- [Localizzazione custom integration](https://developers.home-assistant.io/docs/internationalization/custom_integration/)

Licenza: MIT.

## Classificazione nell'interfaccia Home Assistant

Dalla **0.0.4** `integration_type` è **`hub`**, non `helper`. EasyWallbox Smart Charging coordina sorgenti dati provenienti da più dispositivi/servizi, mentre `helper` è riservato a funzioni come i contatori e i sensori derivati. `iot_class: calculated` rimane invariato poiché la nostra integrazione elabora stati forniti da altre integrazioni. Questa modifica **non** cambia le entità mappate e non introduce controlli reali.


### Scelta modalità in Home Assistant (miglioramento UI 0.0.7)

La schermata **Misure elettriche — scegli un metodo** presenta **tre alternative esclusive**:

- **A · Casa misurata (es. Shelly):** un elenco di sensori dedicati ai consumi domestici che NON includono la ricarica; opzionalmente un sensore separato per la potenza auto. È il metodo più adatto quando sono disponibili contatori dedicati.
- **B · Casa calcolata (DPM − ricarica):** il totale deve INCLUDERE il ramo auto. Si sottrae la potenza auto letta da ESPHome, Shelly o altra fonte. Il totale può arrivare dal DPM della wallbox **o da un altro contatore generale**. Il DPM non deve essere disattivato, e la sua effettiva copertura va verificata.
- **C · Nessun sensore di potenza:** l'integrazione resta configurabile ma non presume potenza di casa uguale a zero.

**A, B e C sono modalità alternative, non si sommano.** Per l'abitazione utilizzata come banco prova: A con sensori Shelly dei rami domestici e sensore Shelly del ramo auto, mantenendo il DPM attivo.

### Pianificazione e carichi domestici: principio di progetto

Il futuro planner deve **privilegiare il raggiungimento del SOC entro la partenza**, evitando quando c'è margine le fasce di consumo domestico elevato e le continue oscillazioni della potenza imposta dal DPM. Non deve regolare la potenza a ogni picco né replicare le protezioni elettriche del DPM.

Le eventuali abitudini domestiche potranno in futuro essere **parametri generici facoltativi** (fasce prevedibilmente impegnative), non codice specifico per lavastoviglie, lavatrice o climatizzatori. Non è stata approvata alcuna nuova integrazione con i singoli elettrodomestici; prima servono prove di beneficio concreto. Il sensore filtrato e storicizzato è utile per analisi a tempi lenti, non sostituisce la sicurezza rapida del DPM.

## Misure elettriche flessibili — 0.0.5

Nella configurazione si può scegliere una delle seguenti tre situazioni:

- **Casa senza ricarica:** uno o più sensori (da 1 a N) di potenza istantanea che coprano la casa **esclusa la wallbox**, senza sovrapposizioni. Casa = somma dei sensori. La potenza auto, se disponibile da un Shelly o da ESPHome, si può inserire separatamente.
- **Totale comprensivo della ricarica:** un sensore del totale che **comprenda l'auto**, più uno della potenza auto. Casa = totale − auto. Possono essere anche sensori di diversa origine, purché descrivano correttamente lo stesso perimetro e letture sufficientemente sincronizzate.
- **Nessuna misura disponibile:** permesso; il futuro planner dovrà dichiarare indisponibile l'ottimizzazione dei consumi, non sostituire i dati mancanti con zero.

**Firmware controllato:** `Charging Power` e `House total power -DPM-` sono effettivamente esposti da `wallbox.yaml` (`main` firmware, verificato 12/11/2026). Entrambi sono valori in kW calcolati dalla telemetria BLE; il polling nominale è ~30 s e `Telemetry Fresh` segnala dati scaduti dopo ~100 s. **Il codice non prova da solo che il misuratore DPM includa il carico della ricarica**: prima di sottrarre, verificare fisicamente la copertura e confrontare durante una ricarica con un contatore indipendente.

Selezionare sensori di **potenza** (`W` oppure `kW`), non di **energia** (`Wh` o `kWh`). Il nuovo modulo puro `power_model.py` gestisce conversioni, dati assenti, obsoleti, negativi e contraddizioni; nella **0.0.6 non è ancora collegato agli stati HA né espone sensori energetici o dashboard**. Nel futuro planner la qualità e latenza di ogni misura dovranno essere verificate prima dell'uso; il DPM resta responsabile della regolazione rapida.

**Migrazione dalla 0.0.4:** wallbox e profili veicolo vengono conservati. Se i tre sensori preesistenti erano configurati, la vecchia coppia piano terra + primo piano diventa la lista dei sensori casa e il terzo il sensore dell'auto; se il mapping era incompleto, si sceglie «Nessuna misura» fino alla nuova configurazione. Verificare tutto da **Opzioni → Misure elettriche**.

## Sensori disponibili dalla v0.0.6 (prima osservazione)

Dopo aggiornamento Marketplace e riavvio HA, aprire l'integrazione e il dispositivo **EasyWallbox Smart Charging**. Sono previsti cinque sensori nativi:

| Sensore | Significato |
|---|---|
| Active vehicle | Nome dell'auto identificata, solo se univoca |
| Current SOC | SOC (%) confermato e aggiornato |
| Target SOC | Obiettivo abituale (%) configurato sul veicolo |
| Battery energy needed | Energia residua **nella batteria** in kWh, esclusi perdite e bilanciamento |
| Data quality | Stato `ok` o motivo per cui un dato non è calcolabile |

La formula è `max(0, (target - SOC) / 100 × capacità utilizzabile kWh)`. Un target al 100% **non rappresenta un comando di arresto**. Non è una stima della potenza o dell'energia prelevata dalla rete, non considera perdite AC/DC né stima il tempo.

**Riconoscimento prudente:** richiede un sensore wallbox «auto collegata» valido, `Telemetry Fresh` ON se configurato e un solo veicolo riconosciuto come collegato. Se un secondo sensore di collegamento non risponde, la selezione rimane indeterminata; non assumiamo quale auto sia collegata. Quando uno stato è `unknown`, `unavailable`, troppo vecchio o incoerente, i valori non calcolabili rimangono `unknown`, non zero.

Soglie iniziali, **da verificare su HA reale**: fino a 120 secondi per collegamento/telemetria wallbox e fino a 45 minuti per stato collegamento e SOC veicolo. È un controllo osservativo ogni due minuti, **non** un controllore dei picchi. Non aggiunge polling alla BLE, né modifica firmware, DPM o automazioni esistenti. Gli ID effettivi delle entità sono assegnati dal registro Home Assistant e non vanno indovinati.

**0.0.6 vs 0.0.5:** la 0.0.5, già pubblicata, ha introdotto una configurazione energetica flessibile. Questa v0.0.6 conserva la configurazione, ma non usa ancora le letture DPM per stime di carico o pianificazione: la copertura del contatore DPM deve ancora essere verificata confrontandola con gli Shelly.

**Prova e rollback:** aggiorna dal Marketplace alla 0.0.8 e riavvia Home Assistant, poi verifica i cinque sensori. Se ci sono errori consulta il registro HA e riporta soltanto il messaggio/traceback, senza dati personali o file `.storage`. Se necessario reinstalla la release 0.0.5 e riavvia. Non disattivare le automazioni Fiat.

## Prima anteprima del planner — 0.0.8

Nelle **Opzioni → Pianificazione** imposta la sola **potenza massima
continuativa disponibile per casa e auto** (4,4 kW nell'impianto del
banco prova, non la potenza contrattuale né sovraccarichi temporanei),
e l'orario di partenza abituale per feriali e weekend. Non cambia il DPM.

Si aggiungono sei sensori read-only: potenza casa, prossima partenza,
inizio consigliato, fine stimata, stato piano e **Scenario 30% (simulazione)**.
Quest'ultimo funziona anche con auto scollegate e mostra negli attributi,
per ogni veicolo configurato, cosa succederebbe partendo dal SOC ipotetico
30% fino al proprio obiettivo abituale. Non finge che l'auto sia collegata.

**Limiti molto importanti:** previsione momentanea, usa il consumo
domestico attuale come se restasse costante fino alla partenza.
Assume rendimento AC 90% e margine 45 minuti, **non** dedotti da una
specifica automobile. La potenza EV è limitata dal budget elettrico
ipotizzato, non ancora dal limite effettivo e verificato del caricatore:
l'orario calcolato può essere troppo ottimistico. Dati mancanti,
obsoleti o incoerenti non diventano zero. Non ci sono ancora fasce
critiche, sensori opzionali elettrodomestici, ottimizzazione dinamica
o dashboard dedicata. Leggi [le note 0.0.8](docs/releases/0.0.8.md).

Dopo aggiornamento e riavvio HA, imposta Pianificazione, controlla i
sensori nel dispositivo EasyWallbox Smart Charging e apri gli attributi
dello scenario. L'anteprima necessita dei sensori di potenza casa
configurati e aggiornati. I test automatici non sostituiscono il
collaudo Home Assistant reale; se necessario reinstalla la 0.0.7.

## Aggiornamento correttivo 0.0.9

Se `Data quality` segnala `wallbox_telemetry_unavailable`, aprire gli
**attributi** del sensore: indicano l'entità `Telemetry Fresh` effettivamente
configurata, lo stato osservato, l'età della lettura e una causa esplicita.
Il controllo di freschezza non è stato disattivato: senza dato valido non
si riconosce l'auto e non si fornisce una previsione reale.

Letture domestiche Shelly e **prossima partenza** sono adesso indipendenti
dalla telemetria BLE: possono comparire anche senza auto riconosciuta,
se configurate correttamente e aggiornate. La release non cambia firmware,
DPM o automazioni. I test offline sono necessari ma non sostituiscono un
collaudo sul tuo Home Assistant. Per dettagli e rollback vedere
[docs/releases/0.0.9.md](docs/releases/0.0.9.md).

## Correzione fondamentale 0.0.10: ON/OFF non scade dopo due minuti

Il collegamento alla wallbox, il collegamento dei singoli veicoli e
`Telemetry Fresh` sono stati binari, non campioni di potenza che
devono aggiornarsi ogni due minuti. Nella 0.0.9 il tempo trascorso
dall'ultimo stato reportato poteva farli diventare erroneamente
non validi dopo 120 secondi (o 45 minuti per i veicoli), anche quando
l'entità continuava a mostrare ON. La 0.0.10 rimuove questi timeout
artificiali. Il watchdog ESPHome `Telemetry Fresh` resta obbligatorio
se configurato: se è OFF o unavailable il piano non viene calcolato.
SOC e potenza restano soggetti ai propri controlli di freschezza.

**Verifica:** confermare che `Data quality = ok` rimanga tale
oltre i due minuti mentre l'auto è collegata e i dati sono validi;
controllare nuovamente dopo un intervallo superiore ai 45 minuti.
Nessun comando al firmware, wallbox, auto o DPM. Dettagli:
[docs/releases/0.0.10.md](docs/releases/0.0.10.md).

## 0.0.11 — Il parametro centrale: potenza media richiesta alla partenza

La 0.0.11 aggiunge il sensore `Mean power needed by departure` in kW.
Partendo dai kWh mancanti nel veicolo e dalla prossima partenza,
calcola la potenza media **lato rete** necessaria con le ipotesi
temporanee del 90% di rendimento AC e 45 minuti di riserva.

**È indipendente dal consumo domestico momentaneo.** Un forno acceso
non significa che resterà acceso per tutto il resto della notte;
invece la vecchia `Estimated finish` resta soltanto uno **scenario
teorico con l'attuale carico domestico mantenuto costante**. I relativi
stati non devono essere letti come previsione attendibile della
partenza. Il nuovo sensore è calcolabile anche se manca un sensore
Shelly, purché SOC/veicolo/orari siano validi.

Se la media richiesta supera la potenza continuativa configurata
dell'intero impianto, viene segnalato separatamente l'impossibilità
teorica con quel margine. Non viene ancora verificato il limite
effettivamente impostato sulla wallbox, né stimato il carico futuro.

Per la spiegazione tecnica e il rollback vedi
[docs/releases/0.0.11.md](docs/releases/0.0.11.md). Nessuna modifica
ai comandi, alle automazioni o al firmware.

## 0.0.12 — Prima decisione simulata in risposta a un carico ON/OFF

Nelle **Opzioni → Simulazione carico domestico** puoi collegare
facoltativamente il `number` di potenza richiesta (es. Charge power),
il `sensor` di potenza confermata (es. Power set) e **un**
`binary_sensor` di attività di un carico (es. lavastoviglie),
inserendo picco aggiuntivo teorico e durata prudenziale. Sono entità
HA scelte dalla GUI: nessun ID o carico della casa incorporato nel
codice e nessuna modifica ai comandi.

Il nuovo sensore **Decisione carico domestico (solo simulazione)**
mostra quando una riduzione sarebbe teoricamente compatibile
(`temporary_reduction_possible`) oppure deve prevalere la partenza
(`priority_departure_keep_limit`). Gli attributi distinguono
potenza richiesta, confermata, effettiva, proposta ipotetica,
margine energetico e dato di attività ON/OFF.

Se il carico torna OFF può mostrare un **ripristino ipotetico**,
soltanto se in precedenza era stata simulata una riduzione e l'utente
non ha cambiato manualmente il limite. Il numero **non viene mai
modificato**. L'eventuale segnalazione di override è diagnostica.

**È un banco prova**, non ancora la funzione automatica definitiva:
la potenza di picco è sommata per cautela al consumo attuale della
casa e può essere sovrastimata; non usa il comportamento reale delle
singole fasi né il consumo previsto di tutta la notte. La simulazione
di una riduzione NON garantisce protezione elettrica, affidata sempre
al DPM. Test di base sintetici e motivazioni in
[docs/releases/0.0.12.md](docs/releases/0.0.12.md).
