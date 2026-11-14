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

## 2026-11-13 — Fix: stati ON/OFF indebitamente scaduti (0.0.10)

### Regressione funzionale osservata nell'installazione HA
- All'avvio di Smart Charging 0.0.8/0.0.9 si vedono EV3, SOC 37,5%,
  obiettivo 80%, energia batteria 33,15 kWh, potenza casa 0,824 kW
  e la prima previsione. Poco dopo i sensori diventano indisponibili.
  Non significa che la Kia abbia smesso di caricare.
- Analisi di `snapshot.py`: la funzione `_binary` usava `_fresh` con
  timeout 120 secondi per stato wallbox/Telemetry Fresh e 45 minuti
  per collegamento delle auto. Questi stati sono persistenti e possono
  restare ON/OFF a lungo senza aggiornare `last_reported` in HA.
- Il watchdog `Telemetry Fresh` è già gestito da ESPHome e va a OFF
  in caso di assenza di telemetria BLE (default circa 100 secondi);
  questo controllo sorgente e l'availability HA non vengono aggirati.
  SOC e potenza numerica continuano a richiedere letture aggiornate.

### Correzioni
- `snapshot.py`: nessuna TTL sugli stati binari ON/OFF; nessun bypass
  di `unknown/unavailable`; l'identificazione richiede ancora
  `Telemetry Fresh = ON` se configurato, wallbox collegata e veicolo univoco.
- `sensor.py`: diagnostica coerente con stato del watchdog e non con
  età dell'ultimo cambio ON/OFF. Lo stato ON è `watchdog_on` anche
  se invariato a lungo; timestamp esposto solo informativamente.
- `tests/test_snapshot.py`: caso con 8 ore di ON/OFF invariati,
  OFF/unavailable, SOC >45 minuti non aggiornato, altri stati.
- Manif. 0.0.10 e changelog; test automatici CI da verificare.
- Nessun firmware, DPM, automazioni, `main` o comandi reali modificati.
  Per il collaudo in HA servono stato corretto oltre 2 minuti, poi
  oltre 45 minuti con SOC aggiornato; controllare un eventuale vero
  stato Telemetry Fresh OFF/unavailable.

## 2026-11-13 — EV3: confronto Pilot Advertised Power e Charging Power
- Durante la ricarica EV3 l'utente legge 3,19 kW di Pilot Advertised Power e 3,03 kW di Charging Power: scarto 160 W; differenze analoghe osservate con Fiat 500e.
- Verifica firmware main: Pilot Advertised Power deriva dal PWM del Control Pilot e da 230 V fissi (formula pwm_raw * 0.06 * 0.23); Charging Power deriva dalla telemetria BLE (campo AD p[11]/1000). Il primo non è una misura della potenza realmente assorbita.
- In uno screenshot precedente erano visibili 222 V (non necessariamente contemporanei). A parità di corrente, una potenza teorica di 3,19 kW a 230 V equivale a circa 3,08 kW a 222 V: circa 110 W dello scarto possono essere spiegati solo dalla tensione. I restanti ~50 W possono dipendere da regolazione dell'auto o misure; serve acquisizione sincronizzata.
- Non confondere differenza pilot/assorbimento con perdite energetiche o intervento DPM. Per il modello usare Charging Power/Shelly come assorbimento effettivo; pilot come limite teorico di corrente. Non introdurre correzioni fisse.
- Nessun cambio software attuativo, release, DPM o firmware.

## 2026-11-13 — Calcolo della domanda media invece della falsa proiezione della cena (0.0.11)

### Problema osservato
- In carica EV3 alle 19:44: SOC 39%, target 80%, 31,98 kWh da
  reintegrare nella batteria, consumo domestico circa 2,07 kW,
  limite impianto 4,4 kW. La precedente anteprima mostrava
  `deadline_at_risk` e ~15 ore perché assumeva consumi domestici
  della cena costanti tutta la notte. Non è una previsione credibile.
- Priorità del progetto: SOC entro la partenza, controllo lento e
  spiegabile, nessun nuovo comando.

### Modifiche in sviluppo-test
- Aggiunta funzione pura `departure_demand` in `planner.py`.
  Calcola potenza media richiesta **lato rete**, con obiettivo SOC,
  tempo utile fino alla partenza meno riserva ed efficienza ipotetica,
  senza usare il consumo istantaneo domestico.
- `live_planning.py` separa `DepartureDemand` dallo scenario
  `current_load_scenario_*`; restituisce domanda media anche con
  casa non misurata, se auto e orari sono validi. Evidenzia separatamente
  quando la domanda supera il limite continuo di impianto.
- Nuova entità read-only `required_mean_power`; attributi del
  sensore scenario e scenario 30% espongono la domanda. Labels IT/EN
  distinguono scenario da previsione reale.
- Esempio **non attuale**: ore 19:44→08:00 = 12h16; 31,98 kWh
  batteria, 90% ipotetico, 45m riserva → **3,09 kW medi**;
  senza riserva servono circa 2,90 kW.
- Test unitari per carichi temporanei, calcolo medio, SOC zero,
  input incoerenti e dati domestici mancanti. Verifica finale CI e HA
  reale ancora necessarie.

### Limiti confermati
- Nessuna previsione futura realistica dei carichi, nessun profilo orario
  codificato e nessuna modifica alla potenza EV, wallbox, DPM,
  automazioni o firmware. Non usare il dato di potenza media richiesta
  per dichiarare garantita la partenza.

## 2026-11-13 — Primo simulatore di decisione su carico ON/OFF (v0.0.12)

### Decisioni e motivazioni
- Problema reale: Kia EV3 in carica mentre si cucina e si usa la
  lavastoviglie. L'utente deve abbassare manualmente il limite della
  wallbox e ricordarsi di ripristinarlo. Una semplice fascia oraria
  non può capire quando questa riduzione compromette il SOC alle 08:00.
- **Requisito confermato**: nessun comando nella v0.1 simulata; DPM
  4,4 kW attivo e gestione dei picchi interamente hardware.
- Per la prima prova soltanto **un carico anticipabile opzionale**.
  Non vincolare il codice a nome, orario o marca dell'elettrodomestico.
  I successivi N carichi vanno valutati dopo il test del primo.

### Implementato su sviluppo-test
- Nuovo `load_scenario.py`, funzione pura per confrontare una
  limitazione ipotetica a passi di 0,2 kW con il margine energetico
  residuo prima della partenza, usando la domanda grid-side.
- Nuovo `simulation.py`, lettura delle entità HA in sola lettura:
  potenza richiesta (`number`), confermata (`sensor`) e potenza
  effettiva già configurata in misura, attività ON/OFF facoltativa.
  Divergenze richiesta/conferma e dati obsoleti non sono ignorati.
- Aggiunta nelle Opzioni la scheda `scenario`, con picco aggiuntivo
  e durata ipotetica, e una sola entità diagnostica della decisione
  simulata, con attributi completi.
- Ripristino **solo ipotetico** dopo OFF; un cambio manuale della
  potenza annulla la proposta e viene rispettato. Stato RAM non
  persistente. Nessun servizio HA, BLE o comando alla wallbox.
- Test isolati di Kia con partenza urgente, veicolo con ampio margine,
  carico ON/OFF/unknown, divergenza limite richiesto/confermato,
  potenza reale obsoleta, intervento manuale e ripristino virtuale.
- Test statici, traduzioni IT/EN, README e note della 0.0.12.

### Limiti
- La potenza di picco configurata è considerata **aggiuntiva** al
  consumo domestico attuale; può contare due volte un picco già in
  corso. Questo è volutamente prudenziale e NON costituisce un
  calcolo certificato di capacità elettrica.
- Mancano ancora previsione consumi nel resto della notte,
  controllo anti-oscillazione di eventuali comandi futuri, più
  carichi simultanei e dashboard v0.1 completa.
- CI e verifica sul vero HA sono da completare prima di dichiarare
  la funzionalità collaudata. Firmware, automazioni, DPM e main invariati.

## 2026-11-13 — Semplificazione e ETA con potenza EV effettiva (0.0.13)

### Problema reale
- Kia EV3 SOC 50,5%, target 80%, 23,01 kWh mancanti. La 0.0.12 stimava ~6h perché scambiava la disponibilità 4,4 kW meno casa per potenza effettiva di ricarica; la wallbox stava invece erogando circa 3 kW.
- La pagina sperimentale con Charge power, Power set e un solo sensore lavastoviglie era troppo tecnica e rigida. Erano esposti troppi sensori duplicati o non utilizzabili, e i nomi inglesi erano hardcoded.

### Decisioni
- La previsione di fine deriva da kWh ancora necessari nella batteria / (kW effettivamente misurati dalla wallbox × efficienza AC ipotetica 0,90). Non usare la potenza residua contrattuale come potenza EV.
- Presentare soltanto veicolo, SOC, target, energia necessaria, prossima partenza, fine stimata. La qualità dati è diagnostica; eliminare i sensori di prova ridondanti.
- Mettere da parte l'opzione singolo elettrodomestico anziché irrigidire un modello ancora non concordato. Il motore sperimentale rimane isolato e non è attivo in HA.

### Modifiche sviluppo-test
- Nuovo charging_eta.py con controlli su W/kW, sensore EV configurato, data freshness <=300s, potenza nulla/non valida, SOC assente; nessuna ETA inventata.
- Sensor platform ridotta a sei sensori principali più diagnostica, nomi da traduzioni IT/EN via translation_key, attributi sulla stima chiari. Le entità di prova precedenti sono ritirate.
- Rimozione dal registro solo degli ID di entità sperimentali di questa config entry; non toccare Shelly/ESPHome. Eventuali dashboard utente che le richiamavano vanno aggiornate.
- Options Flow senza pagina di simulazione per un singolo carico; modalità energetiche A/B continuano a permettere la scelta della potenza EV effettiva.
- Test isolati/stati validi, obsolescenza e test di configurazione; README, docs/LOVELACE.md e note release aggiornati.

### Limiti
- ETA è una proiezione della potenza attuale costante, NON una previsione garantita; il DPM può limitarla. Il rendimento AC 90% è provvisorio.
- Nessun servizio HA, comando BLE, modifica al DPM, firmware, automazioni o branch main. Dashboard v0.1 ancora da realizzare.
- Aggiornare la fonte di progetto con questa decisione dopo collaudo HA.

## 2026-11-13 — Dimostrazione reale di processo, simulazione completa offline

### Motivo
- L'utente ritiene giustamente insufficiente una successione di release
  con sensori numerici. Prossima carica Kia forse tra circa dieci giorni:
  lo sviluppo non deve dipendere da un'auto collegata.
- Decisione: **non pubblicare una nuova versione dell'integrazione HA
  finché non è dimostrato un comportamento completo**, spiegabile e
  superiore (quando possibile) alla semplice gestione DPM.

### Risultato verificabile
- Aggiunto `session_replay.py` puramente Python, senza dipendenze HA,
  che simula dal SOC al target tre politiche di limite EV: lascia DPM,
  riduci per un ciclo domestico e ripristina, riduci e dimentica.
- Aggiunti `tests/test_session_replay.py` e
  `docs/PROVA_NOTTE_2026-11-13.md`, con dati osservati distinti
  da assunzioni e risultati riproducibili.
- Creato un simulatore HTML offline interattivo allegato nella
  conversazione di progetto: Kia 21:13, Kia 30%, Fiat con carica breve;
  grafico di avanzamento, timeline completa, tre strategie, controlli
  per ricalcolare ipotesi. Il prototipo HTML non è collegato a HA,
  né al server, né alla wallbox; non attua nulla.
- Esempio con 27,69 kWh batteria Kia, 4,4kW DPM, baseline casa 0,2kW,
  potenza EV scenario alta 3,85kW e ridotta 3,00kW,
  efficienza ASSUNTA 85%, lavastoviglie 102min con 23min di picchi:
  DPM-only ~05:51; manuale con restore ~06:09;
  ridotta senza restore ~08:11. **Non sono misure della notte**.
- Conclusione non ovvia: sotto un DPM già efficiente ridurre manualmente
  la potenza per **l'intero ciclo** della lavastoviglie può peggiorare
  il raggiungimento del target. L'integrazione non deve comandare
  per forza: deve sapere suggerire di **non intervenire**.
- Il replay non modella allarmi da 3700W dei singoli rami domestici,
  ritardi DPM, congiunture di carichi non osservati o watt effettivi
  sincronizzati durante la notte. Non prova la sicurezza di un setpoint.

### Passi ancora aperti
- Eseguire/controllare CI offline sulla commit; non spacciare il modello
  ideale per una calibrazione delle efficienze della Kia.
- La prossima milestone v0.1 deve integrare questa logica di sessione
  con una UI semplice e senza comandi, mantenendo diagnostica chiara
  e dati incompleti non validi.
- Firmware ESPHome, soglia DPM, automazioni, main invariati.


## 2026-11-14 — Rifondazione ispirata a evcc, nuovo branch e specifica M0

### Stato GitHub verificato e autorizzazione
- L'utente ha chiesto esplicitamente un **branch nuovo**, separato da `sviluppo-test`.
- Creato `rifondazione-evcc` dal commit esatto `ab6b2b279e724ee0629aa80eaf7dfed64d3953d0`. Il branch `main` e `sviluppo-test` restano invariati; il firmware ESPHome non si tocca.
- La linea 0.0.x rimane **storica**: codice ancora presente nel nuovo branch solo per conservazione e futura rimozione deliberata, non baseline funzionale della riscrittura.

### Decisioni architetturali di principio approvate (M0 parziale)
- Prendere da evcc l'architettura logica di sessioni, veicoli, SOC e obiettivi temporali, **non** copiarne integralmente Go, driver o attuatore.
- Pianificatore deterministico a scala di minuti: affronta genericamente carichi domestici variabili, tempi di collegamento imprevisti e scadenze; **nessun orario domestico hardcoded e nessuna integrazione obbligatoria per singoli elettrodomestici**.
- Wallbox/ESPHome sono proprietari del BLE e il DPM è sempre attivo, unico responsabile della gestione rapida dei picchi; il planner osserva risultati misurati senza inseguire oscillazioni con ripetuti Start/Stop.
- Separare modalità utente, fase di sessione, ETA misurata, piano di partenza e comandi futuri; nessuna riattivazione automatica di pausa esplicita o sessione interrotta.
- **v0.1 simulazione senza comandi**; Lovelace e replay offline obbligatori. Automazioni legacy invariate.
- Profilazione storica dei carichi **non prevista nella v0.1**: eventuale miglioramento futuro solo se i test mostrano benefici. In GitHub usare esclusivamente fixture sintetiche, non pubblicare abitudini e dati domestici reali.

### File modificati e verifiche
- Creato `docs/ARCHITETTURA.md`: contratto dati con provenienza e freschezza, macchine a stati, ETA distinta dal piano, sicurezza, UX e piano di test. Il documento identifica esplicitamente i parametri **non ancora approvati**.
- Aggiornato questo diario senza rimuovere lo storico precedente.
- Nessun file di programma modificato, nessun test applicativo o hardware eseguito, nessuna release/tag, nessuna azione sulla wallbox o su Home Assistant.

### Ancora aperto prima del core M1
- Riserva temporale, selezione della potenza prudente, rendimento/efficienza e soglie di freschezza/persistenza dei carichi.
- Precedenze esatte tra Manuale, Pausa esplicita, Carica subito, stop auto, cambio target e restart HA; piano di migrazione/rollback da 0.0.13.
- Verificare le entità reali e le unità prima dell'integrazione HA (M2).
- Allineare la fonte viva del Progetto alla nuova decisione del branch e ai criteri generali M0. Non dichiarare M0 completamente chiusa né M1 implementata.

## 2026-11-14 — M0: proposta per limitazione adattiva, picco singolo e scadenza

### Feedback e requisito corretto
- Durante la ricarica, la presenza di elettrodomestici intermittenti genera picchi che nel caso osservato hanno attivato ripetutamente l'automazione di allarme consumi, anche con DPM operativo. Il limite portato manualmente a 2 kW è poi rimasto basso fino al ripristino manuale. L'obiettivo include **anche il ripristino automatico** dei momenti di maggior headroom, non solo la scelta dell'ora di partenza.
- L'utente propone che **un solo picco verificato** possa far scendere il cap; indicativamente rivalutazione dopo 10 minuti, modificabile in base allo slack di pianificazione. Soglie e tempi **non ancora approvati come numeri definitivi**.

### Modifiche documentali
- Aggiornato `docs/ARCHITETTURA.md` con il supervisore adattivo simulato, formula candidata del cap, segnali indipendenti casa/EV, risalita a passi, limite di comandi e veto planner sulle riduzioni facoltative quando la partenza è a rischio.
- Distinzione da evcc: planner per SOC/partenza e gestione dei carichi sono separati; evcc sconsiglia il proprio load management in sovrapposizione a controllori integrati. Noi lasciamo DPM attivo e proponiamo **solo una supervisione lenta**, non copiamo il suo attuatore.
- La protezione elettrica prevale sempre sull'urgenza. Se il DPM non contiene un sovraccarico reale, il planner non può garantire sicurezza né raggiungimento del SOC. Serve diagnostica delle letture e dell'eventuale ritardo.

### Test e limiti
- **Eseguiti:** lettura/verifica file GitHub sul nuovo branch e confronto mirato con documentazione e codice evcc al commit di studio. Nessuna esecuzione di planner/replay Python, nessuna prova su HA/wallbox, nessun comando BLE o modifica firmware, nessuna release.
- **Da fare:** fixture su singolo picco valido e spurio, consumi casa intermittenti, risalita anticipata/ritardata, margine grande/nullo, soglia inferiore al minimo slider, dati Shelly non allineati, carica già limitata dal DPM, intervento manuale concorrente, target raggiunto. Confronto quantitativo DPM-only vs cap fisso vs cap adattivo.
- Il grafico HA disponibile usa un recorder filtrato; non prova tempo di risposta DPM né fornisce tutti i picchi. Non dichiarare l'ottimizzazione testata o accettata prima di replay e misure.


## 2026-11-14 — M0: dettaglio operativo per soglie e risalita (ancora PROPOSTA)

- L'utente propone di configurare separatamente potenza disponibile impianto (es. 4,4 kW) e soglia di intervento Smart Charging (es. 5,0 kW). **Il DPM resta attivo e immutato**.
- Al primo picco validato leggere la potenza domestica **escludendo la wallbox** e proporre un cap massimo: 4,4 − 2,1 − 0,2 = 2,1 kW, arrotondato a 2,0 kW con step firmware 0,2. La soglia d'allarme non è un vincolo elettrico autorizzativo.
- Per risalire, non aspettare rigidamente «casa sotto 1 kW»: recuperare margine anche quando si passa da casa 2,1 a 1,2 kW. Prima ipotesi testabile: rivalutazione ogni 1 minuto, attesa iniziale 10 minuti con margine ampio, incremento massimo 0,4 kW ogni 3–5 minuti, rollback su nuovo picco.
- Il planner valuta l'energia sacrificata **nel periodo temporaneo di cap**, non simula erroneamente l'intera notte al limite ridotto; riduzioni aggiuntive sono vietate se consumano margine di partenza insufficiente.
- Verificata lettura `wallbox.yaml` del firmware `main` al commit `094bd04cc9649ff87380013936799ae2788f0d43`: slider `Charge power` minimo 1,4 kW e step 0,2 kW, con conferma separata da richiesta. **Nessuna modifica firmware**; step 0,1 non giustificato senza misure.
- Ho ampliato `docs/ARCHITETTURA.md` riportando tutto come **parametri candidati da simulare**, non come soglie definitive approvate, e senza includere grafici domestici privati.
- **Non eseguiti:** test planner/replay, installazione HA, attuazione o letture domestiche live. Restano da definire freschezza/sincronizzazione Shelly, soglia di margine per veto, intervalli anti-oscillazione, riconciliazione con modifiche manuali e automazioni legacy.

## 2026-11-14 — M1 primo incremento: finestra Shelly volatile e vincolo di inattività

### Decisione dell'utente e architettura
- La nuova integrazione deve rimanere inattiva quando la wallbox non sta caricando: niente raccolta puntuale, nessuna scrittura regolare in file/Recorder e nessuna elaborazione inutilmente continua. Durante `COLLEGATA/ATTESA` deve restare soltanto la possibilità di fare una valutazione sporadica del piano; non registrare un flusso domestico fuori carica.
- Storicizzazione dei consumi domestici quando non si ricarica: **non approvata**. Possibile futura lettura in sola consultazione dei sensori già filtrati e registrati da HA. Per un profilo feriale/weekend semplice non serve un modello AI. Il firmware e i 3 Shelly esistenti non sono modificati.

### Codice introdotto sul solo branch rifondazione-evcc
- Nuovo modulo **puro e non collegato ad HA**, `custom_components/easywallbox_smart/charging_window.py` con deque RAM limitata a 20 minuti/1200 campioni, attivazione soltanto con `set_charging(True)`, svuotamento all'arresto, dati incoerenti o non freschi mai trasformati in zero, finestra mobile 5 minuti per proposta di rialzo fino a 400 W, cap facoltativo calcolabile dal consumo casa al picco validato.
- Nuovi test offline `tests/test_charging_window.py` con nove casi di inattività, memoria, primo picco, ultimo campione ingannevole, dati incompleti, cap, stale e no-stop implicito.
- Aggiornato il workflow statico per eseguire anche sul branch isolato; workflow release resta limitato al vecchio `sviluppo-test` e non è stato toccato.
- Specifica `docs/ARCHITETTURA.md` aggiornata su comportamento spento, ciclo di vita RAM, futuro adapter HA e possibilità di leggere statistiche già disponibili senza un nuovo storico.

### Verifiche e limitazioni dichiarate
- Verificati via GitHub i file del vecchio branch **prima** delle modifiche. Identificato `sensor.py` storico: `Monitor.refresh` usa `async_write_ha_state` ogni 2 minuti anche quando inattivo. **Non ancora sostituito**, perciò non va installato/considerato conforme il nuovo branch come integrazione v0.1.
- I test sono stati aggiunti ma **il loro esito non è ancora confermato**: l'ambiente Python locale non può scaricare il repository GitHub e la lista degli status Actions non ha restituito un risultato verificabile in questa sessione. Non dichiarare test OK senza evidenza.
- Il modulo puro non effettua I/O, non registra eventi HA, non usa BLE, non attua limiti DPM e non aggiunge una fonte di scritture Recorder.
- Restano da implementare: adapter eventi Shelly filtrati per entità e sincronizzazione, distinzione tra sessione e carica reale, regole di precedenza planner, simulatore completo con replay DPM e confronto quantitativo, sostituzione del sensore storico a pubblicazione periodica, dashboard e prove runtime su HA reale.
- Soglie 4,4/5,0/0,2/0,4 kW, finestra 5 minuti, conservazione 20 minuti e freschezza 60 s sono valori **candidati per simulazione**, non taratura validata della parete elettrica.


## 2026-11-14 — M1: prima politica adattiva puramente simulata, senza fasce preferite

### Decisione architetturale
- **Eliminate dalle specifiche della rifondazione le fasce preferenziali di ricarica**: non chiedere finestre relative a cena, lavastoviglie, phon o lavatrice. Restano obiettivi e orari di **partenza** per feriali/weekend ed eccezioni di sessione; il `preferred_start` del precedente prototipo non è un requisito da trasferire.
- Il DPM rimane sempre attivo come controllo elettrico rapido. Il nuovo supervisore non lo copia: agisce solo se si verifica un evento totale sopra soglia attendibile, usando la lettura della **casa senza wallbox** per proporre un limite facoltativo, e restituisce gradualmente la potenza.
- Con un trigger da 5,0 kW, **il primo picco è già avvenuto e non può essere prevenuto** dal supervisore; solo i successivi possono essere mitigati. Il pre-trigger basato su consumi domestici alti è un'ipotesi distinta da valutare in replay, non un automatismo introdotto.

### Piccolo incremento M1
- Aggiunto `custom_components/easywallbox_smart/adaptive_policy.py`, **core Python puro**: modalità inattiva se non in carica, rilevamento dell'attraversamento della soglia (non ogni report alto), cap simulato con 4,4 − casa − 0,2 e passi da 200 W, veto al cap con margine di partenza insufficiente, finestra RAM da 5 minuti per la risalita a 400 W, 5 minuti tra risalite, anti-oscillazione da 5/10/15 minuti secondo episodi osservati negli ultimi 60 minuti. I valori sono ipotesi da ottimizzare. La politica riceve uno slack già calcolato, **non** implementa ancora il planner di sessione completo.
- Aggiunti otto test `tests/test_adaptive_policy.py` per inattività, un picco, hold, finestra con ultimo dato ingannevole, nuova ricorrenza, fine carica, dati obsoleti e configurazione invalida.
- Aggiornati `docs/ARCHITETTURA.md` e README per distinguere il vecchio software 0.0.13 già installabile dalla nuova rifondazione offline.

### Verifiche e confini
- **Verificato in laboratorio locale:** otto test del modulo puro superati con un duplicato funzionale semplificato del buffer `ChargingWindow`. I test esatti sono stati poi aggiunti al repository. **Esecuzione completa GitHub Actions e runtime HA non ancora verificati**; non presentare l'esito locale come prova CI del commit.
- Non esiste nel nuovo modulo alcun adapter per leggere eventi Shelly, nessun servizio HA, comando BLE, scrittura di file, registro di campioni, release o modifica DPM. Il `cap_kw` si aggiorna esclusivamente **nella simulazione**, non rappresenta un comando richiesto/confermato né una misura reale.
- `sensor.py` storico 0.0.13 continua a pubblicare aggiornamenti periodici: sostituzione necessaria prima di dichiarare soddisfatto il vincolo zero registrazioni in idle. Non installare `rifondazione-evcc` come release approvata.
- CSV privati di consumi domestici **non committati**. Il filtro `time_throttle` a un minuto non consente di certificare la durata dei picchi o il numero reale di superamenti; in seguito test comparativi DPM-only/limite fisso/adattivo con scenari sintetici e dati validati.
- `main`, `sviluppo-test`, firmware EasyWallbox e automazioni HA legacy devono restare invariati; nessuna release né PR.

### Prossimi passi
1. Verificare CI del nuovo ramo, correggere eventuali problemi e provare replay integrato con casi sintetici (episodi separati di 25–37 minuti, potenza assente, secondo picco e margine alla partenza).
2. Collegare un planner puro per calcolo reale dello slack (SOC, efficienza esplicita, potenza sostenibile), senza fasce preferenziali.
3. Realizzare successivamente l'adapter eventi Shelly in M2, con timestamp coerenti e nessuna scrittura per campione, sostituendo il monitor storico e testando l'inattività su HA.
4. Riportare questa decisione nella fonte viva di progetto oltre al diario.
