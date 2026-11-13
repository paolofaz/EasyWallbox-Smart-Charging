# Diario tecnico — EasyWallbox Smart Charging

## 2026-11-12 — Commit iniziale, infrastruttura pre-alpha

### Stato iniziale verificato
- Repository: `paolofaz/EasyWallbox-Smart-Charging`, pubblico, permesso di scrittura.
- `main` conteneva soltanto `LICENSE` (MIT), commit `a5c2d20f24b562542692e92bfac745967e2229d4`.
- `sviluppo-test` assente; creato dal commit iniziale dopo autorizzazione dell'utente.
- **Non toccare `main` e non creare PR o issue non richieste.**

### Modifiche introdotte
- Struttura custom integration sotto `custom_components/easywallbox_smart`.
- Manifest e `hacs.json` predisposti per Marketplace Home Assistant; versione tecnica `0.0.1`, **non** release v0.1.
- Config Flow a tre passi e Options Flow per mapping di stati HA esistenti; traduzioni IT/EN.
- Entry caricabile/scaricabile, **senza polling, sensori calcolati, servizi o comandi**.
- Test statici offline e workflow CI limitato al branch `sviluppo-test`.
- README con setup, rollback, limiti e roadmap.
- **Nuovo requisito esplicito**: dashboard Lovelace ad hoc parte obbligatoria della v0.1. Design preliminare in `docs/LOVELACE.md`.

### Motivazioni
- Separare mappatura entità e futura logica del planner.
- Impedire in questa milestone l'uso accidentale di controlli BLE/HA.
- Nessun entity_id domestico hardcodato; input GUI configurabile.
- Pochi file e nessuna dipendenza Python aggiuntiva.

### Verifiche / limitazioni
- Verifica preliminare: documentazione ufficiale Home Assistant Config Flow, Options Flow, manifest e Marketplace (12/11/2026).
- Test statici definiti per esecuzione in CI e locale; **esito esecuzione da registrare separatamente**.
- `hassfest` / HACS action **non ancora eseguite**.
- Installazione/config flow/Options Flow su una istanza HA reale **non ancora verificati**.
- Nessuna release/tag; nessuna prova di compatibilità con la versione HA dell'utente.

### Prossimi passi
1. Verificare test CI statici e installazione HA con la versione effettiva.
2. Raccogliere entity_id reali (Fiat/Kia, ESPHome, tre Shelly) e confermare unità/staleness.
3. Aggiungere lettura/qualità dati con test dedicati.
4. Implementare stime, planner e sensori simulati.
5. Realizzare **dashboard Lovelace** dedicata prima di chiudere la milestone v0.1.

### Decisioni di sicurezza immutate
DPM attivo e responsabile dei picchi. Firmware ESPHome non modificato. Automazioni Fiat SOC e potenza mattutina mantenute. Ogni controllo reale è riservato a release future dopo autorizzazione e collaudo.

## 2026-11-12 — Processo pre-release dal branch sviluppo-test

### Decisione approvata
- L'utente desidera installare direttamente dal Marketplace anche durante lo sviluppo.
- Pubblicare **pre-release 0.x** da `sviluppo-test`, mantenendo `main` invariato fino a 1.0 esplicitamente approvata.
- Alla v1.0 valutare rimozione delle pre-release obsolete **solo dopo migrazione e verifica rollback**, evitando cancellazioni automatiche.

### Modifiche
- Aggiunto workflow `.github/workflows/release-test.yml`: su modifica del manifest o del workflow nel branch di sviluppo, esegue test statici e crea release GitHub pre-release con tag uguale al manifest. Rifiuta tag esistenti privi di release e versioni fuori serie 0.x.
- Aggiunte note `docs/releases/0.0.1.md` e istruzioni Marketplace nel README.
- Nessun comando al caricatore/automobili, nessuna modifica firmware, nessuna modifica `main`.

### Da verificare
- **Verificato:** workflow Publish test pre-release riuscito (run `43261535382`), tag `0.0.1` pubblicato come pre-release sul commit `d6c5dbd2c0fbd563de85930a3182daa27a9d7387`; verificato anche il test statico (run `43261535410`). Prima esecuzione del workflow fallita per regex troppo escapata, corretta in commit successivo; nessun tag/release creato da quella prima esecuzione.
- Possibile limite del Marketplace nel registrare una custom repository con `main` ancora privo di `hacs.json`: non installare il fallback di `main`.
- Installazione e Config Flow su Home Assistant 2026.11 dell'utente.
- Validazione hassfest/HACS action e successive verifiche di compatibilità reale.

## 2026-11-12 — Passaggio alle release normali 0.x

### Richiesta utente e motivo
- L'aggiunta del repository personalizzato nel Marketplace non ha funzionato con la pre-release `0.0.1`; l'errore esatto lato HA resta da acquisire.
- Scelta: pubblicare release **normali** anche per le versioni 0.x, mantenendo il codice di sviluppo e i tag provenienti esclusivamente da `sviluppo-test`.
- Una release normale in questo contesto **non significa software collaudato o pronto per produzione**.

### Modifiche
- Workflow adattato per creare release normali 0.x e convertire la release 0.0.1 già esistente, senza spostare il tag e senza nuove versioni inutili.
- README aggiornato per l'installazione senza switch Pre-release.
- Il branch `main` non viene modificato. `main` contiene soltanto `LICENSE` e potrebbe impedire il riconoscimento del repository nel Marketplace: **ipotesi da verificare** e non risolvibile con la sola tipologia release.

### Verifiche aperte
- **Verificato 12/11/2026:** workflow `Publish 0.x test releases` riuscito (run `43285119169`), release `0.0.1` trasformata in normale (`prerelease=false`) mantenendo tag e commit originari. Test statici riusciti (run `43285119190`).
- Nuovo tentativo dal Marketplace e testo esatto dell'errore se permane.
- Se emerge la necessità di aggiungere file a `main`, chiedere prima consenso esplicito; la policy corrente vieta modifiche a `main`.

## 2026-11-12 — V0.0.2: profili veicolo senza vincolo marca

### Feedback test reale
- Marketplace ha installato correttamente la release 0.0.1 su HA 2026.11.
- Config Flow wallbox visualizzato e compilato; schermata auto Fiat/Kia mostrata, ma l'utente si è fermato perché era richiesto un inesistente sensore target. Non è ancora verificato il completamento integrale del flow.

### Decisioni approvate
- Da 1 a N veicoli, nome e sensori specifici, senza nomi Fiat/Kia codificati.
- Obiettivo SOC **abituale** numerico in Opzioni; override di sessione nella Lovelace v0.1 (mostra un unico target effettivo) e **Escludi obiettivo** per lasciare che l'auto interrompa autonomamente.
- Limite interno auto non letto. Se auto interrompe prima dell'obiettivo HA, annotare arresto prematuro senza ritentare comandi.
- DPM 0 A come futura azione a target HA raggiunto **solo dopo fase simulazione e autorizzazione**; non inviare comandi se ricarica è già arrestata dalla macchina. Conferme fisiche richieste.

### Codice 0.0.2
- Nuova selezione ripetibile veicoli nel Config Flow; obiettivo abituale e capacità utilizzabile configurabili; gestione profili in Options Flow e ID stabile.
- Test di normalizzazione profili, duplicati e validazione; manifest aggiornato per release normale 0.0.2.
- Vecchie mappe auto 0.0.1 non migrate automaticamente: manca la capacità batteria, vietato indovinarla. Riconfigurazione necessaria nelle Opzioni.

### Verifiche da completare
- **Verificato**: test CI statici e pubblicazione release normale 0.0.2 riusciti (runs 43291593790 e 43291593712).
- Test su HA reale: installazione, aggiunta due veicoli, aggiunta terzo, modifiche/ rimozione, reload, aggiornamento da 0.0.1.
- Hassfest/HACS action e test Config Flow con mock HA (non coperti dai test statici).
- Nessuna entità di sessione, dati o Lovelace funzionale in 0.0.2.

## 2026-11-12 — Correzione 0.0.3: migrazione ConfigEntry

- Durante la revisione di 0.0.2 verificata la documentazione Home Assistant 2026.11 sulla migrazione: quando `ConfigFlow.VERSION` passa da 1 a 2 serve `async_migrate_entry`.
- 0.0.3 implementa la migrazione: mantiene i dati originali di 0.0.1, aggiunge una lista vuota `vehicles` senza inventare capacità batteria o ID e aggiorna la versione della ConfigEntry.
- I profili devono essere completati attraverso le Opzioni; nessun comando wallbox o auto.
- Questa release sostituisce 0.0.2 come candidata alla prova reale. Test HA e Marketplace effettivo ancora aperti.
- **Verificato**: test statici e pubblicazione GitHub 0.0.3 riusciti (runs 43291913566 e 43291913523); tag 0.0.3 punta al commit 006e5f97d97d7053ff00bd55b34a73f549be5abd. `main` invariato.

## 2026-11-12 — Requisito target SOC 100% e terminologia DPM

### Decisioni dell'utente (sostituiscono indicazioni precedenti)
- **Eliminata** l'opzione «Escludi obiettivo». Il target SOC può essere 100%, sempre con previsione energetica/temporale fino al 100%.
- Target **inferiore al 100%**: una futura release di controllo potrà considerare una pausa raggiunto l'obiettivo, con stato coerente e conferma indipendente. Non attiva in simulazione.
- Target **100%**: **mai azionare lo switch di pausa ricarica per raggiungimento SOC**, anche se il valore raggiunge 100%; lasciare che il veicolo termini autonomamente l'eventuale bilanciamento delle celle. Mai riavviare una pausa manuale per effetto di questa regola.
- Terminologia obbligatoria: **switch di pausa ricarica** = comando Start-Stop ESPHome, pausa con **limite DPM a 0 A**. **Il DPM deve sempre rimanere attivo e non deve mai essere impostato OFF**. La pausa del flusso non equivale a disattivazione DPM.
- Distinguere comando, conferma, carica reale e potenza Shelly. Stop automatici futuri solo dopo consenso e test.

### Modifiche nel branch di test (non rilasciate)
- README e specifica Lovelace allineati; conservato nel diario lo storico delle decisioni superate.
- Aggiunto modulo puro `soc_policy.py` che valuta esclusivamente la soglia SOC e test offline (nessun servizio Home Assistant, nessun comando BLE).
- Nessun incremento del manifest e nessuna nuova GitHub release per questa sola decisione; includere nel prossimo rilascio con il planner v0.1.

## 2026-11-12 — Correzione tipo integrazione (0.0.4)

### Problema segnalato
- Home Assistant mostra EasyWallbox Smart Charging nella categoria **Helper** a causa del valore `integration_type: helper` introdotto nello scaffolding.

### Correzione e motivazione
- Documentazione ufficiale Home Assistant consultata: `helper` per entità di ausilio; `hub` per una integrazione che aggrega più dispositivi/servizi.
- Cambiato solo `integration_type` da `helper` a **`hub`**; mantenuto `iot_class: calculated`.
- Incrementata versione manifest a **0.0.4**, test statico esplicito sul tipo; README e note release aggiornati. Nessun cambio a config entry, firmware, DPM, automazioni, servizi o comandi.
- La regola della pausa di ricarica per target 100%, definita nel commit precedente, è inclusa nel codice sorgente ma **non ancora collegata a un controllore**.

### Verifiche ancora necessarie
- **Verificato:** test statici CI superati (run `43305338006`) e release GitHub **0.0.4** pubblicata regolarmente (run `43305338160`), tag su commit `7f7b41d03a0ca8d42d19b9f7a49443d78e51b072`. Restano da verificare installazione Marketplace su HA 2026.11, riavvio e classificazione visualizzata nell'istanza dell'utente.
- Validazione runtime Config Flow e compatibilità completa non ancora certificata.

## 2026-11-12 — Misure energetiche: fallback non ancora approvato

- Nella configurazione dell'utente i tre Shelly EM (piano terra, piano primo, wallbox) rimangono le sorgenti preferite. Non serve sostituirle con le letture ESPHome.
- Per altri utenti senza misure dedicate si potrà valutare un fallback documentato e facoltativo: ESPHome espone `House total power -DPM-` (corrente AD p[14] convertita in kW) e `Charging Power` (AD p[11] / 1000, in kW).
- Non è ancora dimostrato con misure reali che il primo comprenda l'intero impianto incluso il veicolo. La sottrazione totale - ricarica è **una ipotesi da validare**, non una formula abilitata.
- Configurazioni con più sensori o miste Shelly/ESPHome sono candidate future; non imporre a tutti la struttura piano terra / primo piano / wallbox.
- Decisione: **nessuna modifica al Config Flow energia per ora**. Confronto programmato con l'utente venerdì 13 novembre 2026 durante una ricarica.
- Confrontare Shelly piano terra + primo piano + ramo wallbox e letture ESPHome in assenza di carica e durante ricarica stabile, tenendo conto di W/kW, timestamp e latenza (BLE circa 30 s, telemetria stale oltre 100 s).
- Non usare le letture ESPHome per inseguire picchi, non modificare firmware, DPM (sempre ON), automazioni o switch di pausa ricarica durante il test osservativo.

## 2026-11-12 — Configurazione energetica generica (0.0.5)

### Intervento dopo la proposta multi-sorgente
- L'utente chiede di non legare l'integrazione a piano terra/piano primo e di ammettere una o più misure casa, uso dei sensori firmware o configurazioni miste.
- Aggiunto **solo il modello di configurazione**: casa senza EV con 1..N sensori non sovrapposti, oppure totale che include EV e lettura EV indipendente, oppure nessuna misura. Le fonti sono selezionabili esplicitamente, **senza attivare automaticamente la sottrazione dal valore DPM**.
- `power_model.py` è un modulo offline: valida topologie, converte W/kW, distingue missing e stale e segnala misure contraddittorie; **non** è ancora un lettore di stati Home Assistant né guida il planner.
- Vecchi 3 campi convertiti solo se la mappatura completa è disponibile (somma dei due sensori casa + sensore EV); le configurazioni incomplete diventano «non configurato». Il resto dei dati è preservato.
- Traduzioni IT/EN, test, README, Lovelace plan e note release aggiornati. Nessun comando reale, firmware non modificato e DPM sempre ON.

### Punto da validare prima di usare il fallback in decisioni
- `House total power -DPM-` proviene da AD p[14] e **non è garantito dal solo codice** che includa l'EV. Occorre la prova comparativa con Shelly durante ricarica e pausa (prevista il 13/11/2026).
- Solo dopo verifica: abilitare la lettura nel planner con controlli di timestamp e `Telemetry Fresh`, senza inseguire picchi.
- La 0.0.5 resta una milestone di configurazione: **nessun sensore e nessuna dashboard effettiva**, nessun automatismo elettrico.

### Verifica della release 0.0.5
- Static checks CI: **successo**, run `43315382062`.
- Release normale GitHub `0.0.5`: **presente e verificata**, tag su commit `6d711ed4cd349bb317deb5d9f0a332697da12508`.
- Config Flow/Options Flow nella vera istanza Home Assistant e misure reali: **non ancora verificati**.

## 2026-11-12 — Release read-only 0.0.6: osservazione veicolo e SOC

### Motivazione
- L'utente ha chiesto i primi sensori prima della verifica energetica del 13/11/2026.
- La versione 0.0.5 è stata nel frattempo già pubblicata con mappatura energia flessibile: mantenere quel tag immutabile. La prima osservazione diventa perciò **0.0.6**.
- La validazione del totale DPM e la logica di pianificazione dei carichi restano in sospeso; questa modifica non le usa.

### Modifiche
- `snapshot.py`: calcolo puro e verificabile di auto collegata, SOC, target abituale, kWh teorici nella batteria, diagnostica. Richiede stato wallbox e unicità del profilo.
- `sensor.py`: cinque entità HA native read-only, ascolto solo delle entità configurate, ricontrollo obsolescenza ogni 2 minuti. Nessuna interrogazione BLE o servizio Home Assistant.
- Piattaforma `sensor` caricata e scaricata correttamente attraverso ConfigEntry; callback registrati in `async_on_unload`.
- Test offline per auto ambigua, vecchi SOC, telemetria indisponibile, target 100% e assenza profili.
- Versione manifest 0.0.6; traduzioni italiane e inglesi per i nomi predisposte.
- Nessuna modifica a firmware, DPM (sempre ON), switch di pausa ricarica, automazioni esistenti o `main`.

### Limiti e test necessari
- **Verificato:** CI Static checks superato (run `43317219784`) e GitHub release normale `0.0.6` pubblicata con successo (run `43317219671`), tag sul commit `35009c66f8a5240fd0f0ffbf8b958070f2183bff`. Questo non equivale a un test runtime in HA.
- Test reale con HA 2026.11, verifica entità generate, aggiornamenti, data quality, `last_reported` e relative soglie.
- Non ancora presenti dashboard dedicata, target SOC della singola sessione, planner, calcolo tempi e lettura affidabile del consumo domestico.
- I kWh esposti rappresentano energia teorica mancante **alla batteria** senza perdite di ricarica.

## 2026-11-13 — Etichette energia alternative e principio anti-oscillazione (0.0.7)

### Feedback
- Il menu «Sensori casa / Totale meno auto / Nessuna misura» non rendeva abbastanza evidente che le tre scelte sono alternative.
- Confermata la priorità: raggiungere il SOC richiesto **entro la partenza**, preferendo se possibile evitare ricarica ad alta potenza durante periodi domestici impegnativi; il DPM rimane responsabile delle protezioni rapide.

### Modifiche
- UI IT/EN: modalità A (casa misurata con sensori dedicati tipo Shelly), B (casa dedotta da totale comprensivo auto, spesso DPM, meno potenza auto), C (nessuna misura). Menu chiaramente alternativi anche nelle Opzioni.
- Nella descrizione del metodo B è confermato che il totale deve includere l'auto: non assumere che il DPM lo includa finché non verificato.
- Nessuna variazione a formule, configurazioni salvate, entità, firmware, attuatori o automazioni. Solo etichette, documentazione e test di coerenza.
- Esaminato un campione di carico domestico fornito dall'utente (file CSV **non pubblicati** e non committati): il profilo mostra più brevi intervalli a carico elevato invece di una richiesta continua. Lo stato dell'elettrodomestico include periodi sconosciuti, quindi non adottarlo come prerequisito del planner.
- Nessuna integrazione per singoli elettrodomestici approvata. Periodi domestici impegnativi, se utilizzati, restano preferenze generiche subordinate all'orario di partenza; non inseguire campioni istantanei.
- Manifest 0.0.7; release normale generata da sviluppo-test, main invariato.

### Verifiche
- **Verificato**: test statici GitHub Actions superati (run `43403413847`); release normale GitHub `0.0.7` pubblicata con successo (run `43403413504`) sul commit `3926f327440f309029826ec92dd6eb2dcb901b20`. Resta da verificare su HA reale.
- Verifica delle nuove etichette su Home Assistant reale; con la v0.1 sarà necessario il collaudo della pianificazione in sola simulazione.

## 2026-11-13 — Prototipo isolato di pianificazione verso la partenza

### Motivazione
- L'utente ha confermato contratto da 4 kW, con disponibilità continuativa italiana ordinaria di 4,4 kW; i superamenti temporanei non sono un budget garantito per la pianificazione.
- Confermata la priorità del SOC alla partenza, evitando quando possibile sovrapposizioni domestiche e oscillazioni del DPM.
- Universalità tramite **parametri di installazione**, senza codificare gli orari della cena o modelli di elettrodomestici.
- DPM sempre attivo e soglia normale DPM mai regolata dal planner.

### Modifiche in sviluppo-test, non rilasciate
- `planner.py`: funzione matematica pura, nessun Home Assistant, nessun comando. Distingue potenza contrattuale e continuativa, richiede una stima prudente esplicita dei consumi domestici, calcola potenza EV, durata, ultimo avvio utile e compatibilità di un orario preferito.
- `tests/test_planner.py`: prove Fiat/Kia 30→80%, assenza dati, casa impegnata, tolleranze temporanee non utilizzate, obiettivo già raggiunto.
- `docs/PLANNER.md`: specifiche e limiti di validità del calcolo.
- **Nessun cambio manifest, nessuna nuova release, nessuna nuova entità HA o configurazione grafica**. Versione installabile 0.0.7 invariata. Non modificati firmware, automazioni, `main`, DPM o switch di pausa ricarica.
- Collegamento dei calcoli ai sensori e alla dashboard rinviato a una milestone successiva dopo convalida dei dati reali.

### Riferimenti
- E-Distribuzione: https://www.e-distribuzione.it/open-meter/come-leggere-contatore-luce.html
- ARERA: https://www.arera.it/consumatori/potenza-del-contatore

## 2026-11-13 — Potenza unica e fasce condizionali (requisiti)

- Decisione: un solo campo elettrico di impianto, «Potenza massima disponibile dell'impianto (kW)», 4,4 kW per il proprietario. Non chiedere 4 kW di contratto né 5,2 kW di sovraccarico temporaneo, e non calcolare aumenti automatici.
- Eliminato dal prototipo puro `planner.py` il campo `contract_kw`, che era ridondante e inutilizzato. Test e specifica aggiornati; nessuna modifica alla GUI esistente.
- Proposta ancora da simulare: fasce potenzialmente critiche configurabili e facoltative, eventualmente condizionate a sensore ON oppure a consumi persistentemente elevati. Non codificare lavastoviglie, piano cottura o orari domestici.
- I sensori in stato OFF disattivano soltanto la propria condizione; gli stati unknown/unavailable non devono diventare OFF impliciti. ON non equivale sempre ad assorbimento elevato. Le fasce condizionali non prevedono accensioni future.
- Il planner è subordinato al target SOC entro la partenza. Nessun Start/Stop o variazione immediata a ogni cambio sensore. DPM sempre attivo e unico responsabile dei picchi.
- Nessuna nuova release; il prototipo non è collegato ad HA e non comanda nulla. Aggiornare la fonte di progetto quando saranno stabiliti i dettagli delle fasce.

## 2026-11-13 — Banco prova replay carichi (solo simulazione offline)

### Motivazione
- Validare su un tracciato reale il compromesso fra potenza EV costante,
  riduzione preventiva e limitazioni DPM, evitando di approvare automatismi
  basati soltanto sul sensore ON della lavastoviglie.
- Con limite impianto reale 4,4 kW, uno Shelly di un ramo casa e 0,3 kW
  **ipotetici** di altri consumi, il replay mostra che 3,8→3,0 kW
  abbasserebbe i kWh EV ma non la durata teorica delle limitazioni
  durante le fasi a circa 2,1 kW. Il risultato dipende dalle ipotesi.

### Modifiche
- Nuovo `replay.py` puro: dati di potenza timestamped, esplicito carico
  di altri rami come scenario, calcolo teorico di limitazione istantanea,
  conteggio periodi e kWh, segmenti `unknown`/obsoleti esclusi.
- Test offline su picco, assenze, staleness e parametri anomali.
- `docs/REPLAY.md` spiega ipotesi, limiti ed esperimenti futuri.
- **Nessun file CSV privato committato. Nessun controllo HA aggiunto,
  nessuna modifica firmware/DPM, nessuna nuova release né cambio main.**
- Da validare: test statici CI, potenza misurata effettiva e comportamento
  nel sistema HA reale; il replay ideale non prova eventi DPM reali.

## 2026-11-13 — Anteprima HA e simulazione auto scollegata (0.0.8)

### Perché
- L'utente non può attendere una nuova ricarica della Kia, che avviene
  approssimativamente ogni due settimane. Sviluppo e verifica funzionale
  devono procedere su scenari sintetici, non richiedere N sessioni reali.
- La cronologia di otto sessioni e la precisazione Fiat 31/10 16→90% e
  08/11 28→90% sono state elaborate **in conversazione** per verificare
  ordini di grandezza, ma **non copiate nel repository** e non usate
  per fissare rendimenti specifici della Fiat o della Kia.

### Modifiche
- Aggiunto calendario locale `schedule.py`, con partenza futura e
  distinzione feriali/weekend.
- `live_planning.py` legge sorgenti HA già configurate, con qualità e
  obsolescenza, per produrre una previsione read-only con ipotesi
  esplicite, senza inventare W per misure mancanti.
- Aggiunta nelle Opzioni una pagina Pianificazione: unico parametro
  di potenza elettrica **continuativa disponibile** e due ore di
  partenza; nessun valore d'impianto preconfigurato.
- Aggiunti sensori passivi del piano: potenza casa, partenza, inizio,
  termine stimato, stato; un sensore di prova espone negli attributi
  scenari **ipotetici dal 30%** per tutti i veicoli, anche scollegati.
- Traduzioni IT/EN, test di calendario/qualità fonte e README.
- `docs/releases/0.0.8.md` segnala le limitazioni e la procedura di
  verifica. Manifest 0.0.8.

### Sicurezza e limiti
- Prototipo usa consumo domestico corrente come costante e potenza
  teorica residua come massimo veicolo; **può sottostimare il tempo**
  e non modella ancora la potenza reale limitata dalla wallbox/DPM.
- Rendimento AC 90% e margine 45 minuti sono provvisori, non stimati
  automaticamente dai pochi dati storici.
- Nessun comando a ESPHome, wallbox, auto o DPM. DPM attivo (4,4 kW
  nell'impianto del banco prova), firmware e automazioni invariati.
- Nessun collegamento dashboard Lovelace completa: requisito v0.1.
- Verificati test statici CI sul commit preparatorio
  `8ad317e98f31a57dc0de086a2d6a4c7a02a4c817`. Ancora da
  verificare: release finale, Home Assistant 2026.11 reale, formato
  timestamp, validazione dati e presentazione della UI.
- Nessun merge su `main`.

## 2026-11-13 — Correzione diagnostica e indipendenza letture (0.0.9)

### Anomalia osservata su HA
- Durante una ricarica reale della Kia EV3, in EasyWallbox Smart Charging v0.0.8 comparivano `Active vehicle`, SOC, piano e potenza casa come sconosciuti, con `Data quality = wallbox_telemetry_unavailable`.
- DPM reale 4,4 kW, limite EV richiesto 3,2 kW, misure contestuali circa 2.526 W EV e 4.349 W totali, indicative di riduzione DPM. L'automazione domestica avvisa oltre 4.600 W globali o 3.700 W sui singoli rami. Uno screenshot istantaneo non dimostra assenza di picchi precedenti.
- Verifica GitHub: `snapshot.py` è identico tra tag 0.0.7 e 0.0.8. Il blocco del riconoscimento per `Telemetry Fresh` configurato e non valido è preesistente. Lo stato reale dell'entità Telemetry Fresh è ancora da verificare in HA; NON presumere regressione o errore del firmware.
- Firmware main prevede Telemetry Fresh OFF dopo ~100s senza messaggi AD validi (default), Smart Charging richiede stato ON e lettura non più vecchia di 120s.

### Correzioni read-only
- `live_planning.py`: valutare i sensori di potenza di casa e la prossima partenza in modo indipendente dallo snapshot auto. Solo il piano reale continua a richiedere SOC, identificazione e dati validi. Nessun dato mancante diventa zero.
- `sensor.py`: aggiunti a `Data quality` gli attributi dell'entità configurata Telemetry Fresh, stato, età, soglia e causa distinta (off, non trovata, unavailable, obsoleta, ecc.). Non vengono allentate le verifiche di sicurezza.
- Test isolati e statici aggiunti; README e changelog 0.0.9 aggiornati.
- **Nessun comando BLE o elettrico, nessun cambio DPM o automazione, nessuna modifica firmware o main.**
- Prossima verifica nell'HA dell'utente: leggere gli attributi del sensore Data quality e confrontarli con Telemetry Fresh ESPHome. Il problema di telemetria non può essere considerato risolto dalla sola patch UI.

## 2026-11-13 — Osservazione empirica: potenza richiesta, erogata e confronto Shelly

- L'utente riferisce che, **anche senza un intervento evidente del DPM**, la potenza di ricarica effettiva della wallbox tende a essere circa **100–200 W inferiore** a quella impostata. È una caratteristica osservata, non una calibrazione universalmente verificata e non un nuovo setpoint.
- Le misure di **consumo domestico** e di **potenza/energia della ricarica** rese disponibili dalla wallbox risultano generalmente coerenti con quelle degli Shelly; gli scostamenti **di potenza** osservati sono dell'ordine di **100 W al massimo**. Distinguere la verifica di potenza istantanea dalla validazione di energia cumulata, che necessita confronto nelle stesse finestre temporali.
- Implicazione per il planner: distinguere `potenza richiesta`, `potenza effettiva` e `limitazione DPM`. Non dedurre automaticamente un intervento DPM da 100–200 W di differenza; non applicare però una sottrazione fissa nascosta ai setpoint.
- Preferire per la stima dell'energia erogata e per il feedback sensori di potenza effettiva adeguatamente freschi e verificati; gestire piccoli disaccordi tra fonti come diagnostica/tolleranza da collaudare, **mai** come margine aggiuntivo di sicurezza elettrica. Il DPM resta attivo e impostato normalmente a 4,4 kW nell'impianto utente.
- Nessuna modifica firmware, controllo, parametri o versione. Osservazione registrata per i successivi test del simulatore.
