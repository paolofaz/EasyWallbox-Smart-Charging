# EasyWallbox Smart Charging

**1.0.0rc4 — release candidate Home Assistant: test automatici effettuati, collaudo reale della nuova ETA e della migrazione ancora necessario. RC3 superata da questa correzione dello storico.** 

L'integrazione gestisce la pianificazione della carica e una stabilizzazione *lenta* del limite EV tramite le entità del firmware EasyWallbox ESPHome. Non sostituisce il **DPM della wallbox**, che deve rimanere attivo e continua a occuparsi dei picchi elettrici e delle protezioni.

## Architettura

- **ESPHome + BLE**: legge e conferma registri e stati della wallbox; esegue i comandi richiesti.
- **Home Assistant / EasyWallbox Smart Charging**: identifica l'auto, legge SOC e orari, calcola i margini, prende decisioni e invia comandi soltanto dopo le verifiche previste.
- **Tre Shelly EM** nel setup di riferimento: due rami dei consumi domestici e un ramo dedicato alla wallbox. Per la policy si usano soltanto i consumi domestici, escludendo l'EV.
- **La wallbox con DPM attivo** resta l'unico controllore rapido di corrente. Un comando BLE, uno switch o un ACK non dimostrano da soli la potenza effettivamente erogata.

Firmware ESPHome: https://github.com/paolofaz/Easywallbox---Esphome. Questo progetto è separato e non modifica il firmware.

Nessun Docker aggiuntivo, script esterno, fotovoltaico, tariffe dinamiche o decisioni AI.

## Installazione e aggiornamento

Richiede una versione di Home Assistant compatibile con **2026.11** (quality gate su **2026.11.1**) e una EasyWallbox ESPHome già funzionante. Installare tramite HACS/Marketplace come integrazione personalizzata da questo repository, oppure copiare `custom_components/easywallbox_smart` in `config/custom_components/` e riavviare HA.

Aprire *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → EasyWallbox Smart Charging* e completare il config flow grafico. In caso di installazione preesistente, usare le Opzioni.

### Entità richieste

Selezionare le sette entità obbligatorie della **stessa** wallbox ESPHome: Connection BLE, Car Connected, Charging, Start-Stop, Charge power richiesto, limite EV confermato e **Charge Enabled**. **Non** è richiesta la lettura numerica del DPM. Specificare **Potenza massima contrattuale** (ad esempio 4,4 kW) come riferimento solo matematico, la potenza EV predefinita, le sorgenti Shelly del consumo domestico **senza EV** e lo Shelly EV separato. Il DPM reale può essere configurato separatamente nel firmware (ad esempio 4,6 kW): la custom integration non lo cambia né lo ripristina. Il solo Start-Stop eventualmente azionato da Smart Charging provoca la pausa a 0 A o il ritorno all'ultimo valore positivo gestito da ESPHome. Prima di aggiornare un'installazione 0.9.x, aprire Opzioni → Wallbox e mappare **Charge Enabled**, quindi riavviare/ricaricare l'integrazione. Sono disponibili fonti opzionali per Charge State, Session Energy, Session Duration e relè fisico di alimentazione.

Configurare uno o più profili auto con sensore cavo, SOC, capacità batteria, rendimento AC, orari feriali/festivi e target SOC da entità o fisso. È possibile selezionare un pulsante di aggiornamento dati veicolo e, se voluto, lo Stop SOC gestito da questa integrazione. Nel setup di riferimento: Fiat 500e e Kia EV3.

### Evitare comandi concorrenti

Prima del primo collaudo, verificare che le vecchie automazioni HA che comandavano *Charge power* o *Start-Stop* non siano contemporaneamente attive. Lo Stop SOC Fiat legacy, in particolare, non deve duplicare quello dell'integrazione. Conservare l'automazione precedente come riferimento fino alla migrazione collaudata, ma non lasciarle comandare indipendentemente lo stesso dispositivo.

## Come funziona

- **Automatica**: legge stato fisico, dati auto e Shelly; calcola il margine rispetto alla partenza; in condizioni verificate può ridurre il limite EV con una policy lenta e anti-oscillazione.
- **Manuale**: la gestione automatica lascia la sessione all'utente sino alla disconnessione fisica.
- **Avvio posticipato**: da predisporre prima di collegare l'auto, se desiderato; usa il meccanismo di pausa DPM0 già funzionante. Non anticipa automaticamente l'ora scelta.
- **Potenza desiderata sessione**: slider conforme a min/max/step esposti da ESPHome. La preferenza non equivale a un comando scritto o a potenza misurata.
- **Target SOC**: un target fisso o una entità HA, con Stop SOC soltanto per auto abilitate e con conferme indipendenti.
- **Riavvio HA e BLE**: verifica le prove di sessione e il limite precedentemente confermato senza ripetere comandi alla cieca. Se non può riconciliare un LIMITED o un override in sicurezza, blocca i nuovi comandi. Lo sblocco ordinario avviene dopo il distacco fisico confermato; non esiste uno switch UI dedicato a forzarlo.

Il supervisore non segue i picchi secondo per secondo. Un LIMITED può rientrare in NORMAL dopo 15 minuti *osservati* di headroom nominale, o in caso di urgenza con effettiva opportunità di potenza. La condizione di quiete è attualmente `potenza contrattuale - casa - baseline ≥ −0,02 kW`; è **da verificare sui dati reali**, non va modificata preventivamente.


### ETA: previsione della fine ricarica (solo informativa)

La previsione **non pilota Start-Stop, il DPM o NORMAL/LIMITED**: il margine prudente per la partenza resta calcolato come prima.

La versione 1.0 RC adotta una previsione **a due regimi**, sviluppata a partire dall'analisi della ricarica del 23–24 novembre:

- **Potenza libera di riferimento**: mediana di almeno 20 letture EV indipendenti (almeno 10 minuti) in questa sessione, con consumo domestico ≤0,3 kW e limite EV effettivamente a NORMAL. Se questi dati mancano, usa provvisoriamente il minore fra il 96% della potenza desiderata e la potenza contrattuale meno 0,2 kW. Questo ripiego *non è* una misura.
- **Potenza attuale**: media delle misure Shelly EV degli ultimi 10 minuti, comprese le pause DPM osservate. Questa stima vale solo per i prossimi **30 minuti**; il resto dell'energia viene previsto alla potenza libera. Non si proietta il forno acceso su tutta la notte.
- **Energia residua**: capacità/rendimento del profilo auto, meno energia AC Shelly osservata dall'ultimo SOC. Nella stessa sessione, dopo almeno **5 punti di SOC** misurati senza vuoti Shelly, il coefficiente kWh/% può essere corretto con peso progressivo e massimo ±15%. Non viene appreso permanentemente da una sola ricarica.
- **Stabilità**: l'orario indicato è aggiornato in blocchi da 10 minuti; normalmente non varia più di 15 minuti per aggiornamento. Un cambiamento esplicito del veicolo, del target SOC o della potenza desiderata avvia una nuova previsione.
- **Trasparenza**: il sensore Fine carica prevista riporta la qualità *provvisoria/consolidata*, la potenza libera, la potenza recente e un orario *teorico* a potenza libera. Sono riferimenti di calcolo, non garanzie. Con SOC assente, incoerente o obsoleto, la previsione resta indisponibile.

Il modello non conosce i futuri utilizzi di forno, lavastoviglie o altri elettrodomestici: in particolare le prime ore possono avere errori importanti. Non si mostra un falso «orario massimo» o un intervallo statistico non calibrato. Servono ulteriori sessioni reali per validare l'accuratezza e considerare eventuale apprendimento persistente.

## Interfaccia

Sono disponibili entità di stato, pianificatore/avvisi, auto identificata, fase stabilizzatore, stime di energia e completamento, selezione modalità, orari, slider potenza sessione e, ove configurato, slider SOC. Non vengono duplicati i sensori di corrente/potenza Shelly o gli stati BLE. È disponibile una card storico sessioni per Lovelace: l'integrazione registra la risorsa JavaScript ma **non crea una dashboard**. La card legge solo le sessioni **chiuse da distacco fisico del cavo**, una riga per collegamento con colonne **Fine ricarica, Automobile, Energia, Durata**. Le pause e gli azzeramenti dei contatori non producono righe: il modulo conserva le porzioni in .storage e le somma in kWh e minuti. Durante un'interruzione BLE o riavvio conserva lo stato parziale e lo segnala come tale quando la continuità non è certa. Se l'auto non è identificabile, mostra «Non identificata». Una precedente riga beta senza prova del distacco non viene spacciata per una sessione completata.

Un avviso di limite precedente mostra l'**ultimo valore confermato**, non una lettura attuale: verificare sempre il valore effettivo di ESPHome e le misure Shelly prima di intervenire.

## Diario diagnostico — attivabile dalle Opzioni

In **Impostazioni → Dispositivi e servizi → EasyWallbox Smart Charging → Configura → Diario diagnostico** è disponibile il flag **“Scrivi il diario delle decisioni su disco”**.

- **Attivo di default** durante il collaudo; può essere disattivato anche in seguito.
- Quando è attivo, produce file JSONL giornalieri sotto `/config/easywallbox_smart/decision_logs/decisions_YYYY-MM-DD.jsonl`, con eventi, decisioni, comandi richiesti, conferme e motivazioni.
- Quando è disattivo, **non vengono registrati nuovi eventi**; il salvataggio dell'opzione ricarica l'integrazione. I file già esistenti non vengono cancellati e gli eventuali eventi già in scrittura possono terminare durante il cambio.
- Il diario usa una coda limitata, scrittura serializzata e permessi locali restrittivi. Non provoca nuove letture o comandi BLE. Evitare di pubblicare i log: possono contenere orari, identificativi e dati d'utilizzo.

Questa impostazione è destinata a rimanere disponibile anche dopo la beta, senza legare l'attivazione a una versione software.

## Collaudo e sicurezza

La versione precedente 0.9.2b1 è stata collaudata sul campo per NORMAL/LIMITED e ritorno automatico. La release candidate 1.0 modifica l'archivio e l'associazione Charge Enabled, per cui **richiede ancora una verifica reale di scollegamento, somma dei contatori, pausa Start-Stop e riavvio**; i test automatici non sostituiscono la prova elettrica. La logica anti-oscillazione e le soglie dello stabilizzatore restano invariate.

**Rollback:** ripristinare la release 0.9.2b1, riassociare nelle Opzioni la sorgente «Limit house power set -DPM-» e il valore DPM numerico esattamente corrispondente al firmware; non installare 0.9.2 con DPM fisico e riferimento contrattuale diversi. Un backup della directory .storage di HA prima dell'aggiornamento è consigliato per verificare o recuperare lo storico. Non modificare direttamente .storage per correggere le righe.

[Licenza](LICENSE)
