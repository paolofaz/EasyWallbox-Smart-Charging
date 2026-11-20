# EasyWallbox Smart Charging — RC 0.3.0rc1

Custom integration Python **nativa Home Assistant**, per Fiat 500e, Kia EV3
o altri veicoli con sensori configurati. Il firmware ESPHome della wallbox non
è modificato. **Non è una protezione elettrica:** il DPM fisico resta SEMPRE
attivo e conserva il controllo rapido dei carichi e dei picchi.

> **Stato:** RC di sviluppo con comandi reali implementati e disabilitati di
> default. I test Python/CI non equivalgono al collaudo sulla wallbox.
> Non è una release verificata al 100% sul campo. Prima della prova reale
> servono verifica delle entità, delle conferme BLE e della disattivazione
> delle automazioni che potrebbero comandare gli stessi dispositivi.
> `main` e il Marketplace non vengono modificati.

## Schema preciso dei comandi

| Situazione | Cosa può inviare Johnny |
|---|---|
| Cavo scollegato, anche in Automatico | **NULLA** a ESPHome, alla wallbox o alle auto |
| Cavo collegato, auto identificata, carica confermata | **Solo** `number.set_value` sull'entità ESPHome **Charge power**, per il cap EV |
| Cavo collegato, carica **confermata assente** e avvio posticipato attivo | **Solo** `switch.turn_off/on` sull'entità ESPHome **Start-Stop**, se la pausa è di Johnny |
| Cavo collegato, non in carica, senza avvio posticipato | Nessun avvio elettrico automatico |
| Modalità Manuale, Pausa esplicita o dati incompleti | Nessun comando automatico |

La sequenza Start-Stop attuale nel firmware è **DPM 0 A per pausa**;
`Start-Stop ON` recupera l'ultimo DPM positivo memorizzato dal firmware.
**DPM Active non deve essere spento**; è un parametro diverso. Johnny non
modifica mai l'impostazione di attivazione del DPM.

`Charge power` rappresenta la richiesta numerica; `Power set` è la
conferma da ESPHome. Lo switch Start-Stop può anticipare l'esito BLE;
`Charge Enabled` e `Limit house power set -DPM-` sono riscontri separati.
Per attuare una nuova decisione Johnny richiede conferma `Verified ...`
dopo il comando, un limite coerente, una sessione valida e la proprietà
del setpoint. Se non arriva conferma entro 3 minuti: **blocco senza retry**.
La conferma a 0,1 kW HA non permette di recuperare il raw BLE esatto:
va controllata sul campo prima di considerare definitiva la garanzia di ACK.

Con `Avvio posticipato`, la pausa è permessa soltanto **dopo** che
il cavo risulta inserito e la carica risulta assente. **Se l'auto comincia
a caricare prima che HA possa osservarla ferma, Johnny NON la interrompe**:
l'orario posticipato non è garantito in questa circostanza, proprio perché
la regola «mentre carica, soltanto potenza» ha la precedenza. Senza
un altro meccanismo autorizzato non possiamo promettere entrambe le cose.

## Planner e modalità

- **Automatico:** un solo veicolo identificato in modo certo; SOC e target
  aggiornati, partenza feriale/weekend per singola auto, capacità utile e
  rendimento configurati. Stima energia AC da recuperare e margine fino alla
  partenza, compresa riserva prudenziale di 30 minuti.
- **Manuale:** Johnny cede completamente il controllo fino a modifica
  esplicita o scollegamento; NON ripristina neppure un DPM rimasto a zero.
- **Pausa esplicita:** il pulsante della dashboard sospende la gestione
  automatica; per fermare fisicamente una ricarica già attiva si usa
  direttamente lo switch ESPHome, perché Johnny non può comandare lo switch
  mentre è in carica.
- **Carica subito:** salta l'attesa futura di cui Johnny possiede la pausa,
  ma non crea un avvio se il DPM zero proviene da un intervento esterno.
- **Avvio posticipato:** switch + ora preferita (anche oltre mezzanotte),
  calcolata alla connessione e bloccata per la sessione; attesa solo se
  l'ultimo avvio utile permette di rispettare il target. Una stima non è
  una garanzia di ricarica: il DPM può ridurre la potenza.
- **Override prossima partenza:** entità `datetime` con annullamento
  esplicito; gli orari ordinari si impostano per ciascuna auto nel config
  flow e si modificano dalle opzioni dell'integrazione.
- La velocità prudenziale di pianificazione è un **dato configurabile per
  ciascuna auto**, non derivato da un solo assorbimento istantaneo.
  Non si promette un completamento quando i dati sono incompleti.

## Stabilizzatore Johnny RC — soglie candidate

Riferimento di prova: potenza EV ordinaria **4,0 kW**; boost
**4,2 kW**; DPM ordinario nominale **4,4 kW**. Sono limiti
configurabili con i passi del firmware (0,2 kW). La conversione BLE
effettiva usa ampere a 230 V: 4,2 kW visualizzati corrispondono a
18,3 A nel comando, non esattamente a 4200 W attivi.

| Evento | Regola RC |
|---|---|
| Forte | Pressione DPM nominale ≥0,6 kW per 2 minuti di nuovi campioni Shelly, o cicli intermittenti documentati |
| Primo cap forte | Cap unico stimato da DPM − casa − margine 0,2 kW, arrotondato per difetto a passi 0,2; minimo 1,4 kW |
| Moderato | Casa 450–1100 W e pressione ≥100 W-equivalenti per almeno 10 minuti osservati negli ultimi 12 → −0,4 kW |
| Già LIMITED | Pressione residua ≥250 W per almeno 5 minuti osservati sugli ultimi 7, ancora presente → ulteriore −0,4 kW; almeno 10 minuti dall'ultimo cambiamento, massimo due correzioni |
| Ripristino | 15 minuti **documentati** di margine per il limite originale; ritorno diretto a 4,0 kW, mai risalita a piccoli gradini |
| Budget | Se la partenza è a rischio o il budget stimato della sessione è esaurito, non spendere altro margine con riduzioni |
| Boost **solo urgente** | Margine prudente ≤60 minuti **e** casa sotto 150 W per 15 minuti → da 4,0 a 4,2 kW |
| Isteresi boost | Disattivazione quando casa >200 W; se margine recuperato, solo dopo stima attendibile ≥75 minuti e quiete della stima; in caso di incertezza non iniziare un boost |

La potenza Shelly domestica è la somma dei rami della casa **senza**
il circuito EV. Le soglie sono approssimazioni di pressione, NON la corrente
misurata dalla pinza DPM. La policy non insegue i picchi di secondo in
secondo: il DPM protegge l'impianto.

## Configurazione grafica

In `Impostazioni → Dispositivi e servizi → EasyWallbox Smart Charging`
scegliere: tutti i Shelly **domestici**, Shelly EV separato, **Car Connected**,
**Charging**, **Telemetry Fresh**, **DPM Active**, **Wallbox Fault**,
**Charge Enabled**, **Start-Stop**, **Command status**,
**Charge power** (number), **Power set** e
**Limit house power set -DPM-**. Impostare potenza ordinaria, boost,
DPM positivo atteso e profili di Fiat/Kia (cavo, SOC, target, capacità,
rendimento, potenza prudenziale, orari feriali/weekend).
Nessun `entity_id` di un'abitazione è hardcoded.

**Prima di abilitare il controllo reale** occorre disattivare e verificare
le automazioni concorrenti (riduzione mattutina della potenza e limite SOC
Fiat, se controllano le stesse risorse). Per prudenza l'utente deve
confermare esplicitamente questa verifica nel Config Flow; un flag
non prova da solo l'assenza di altri scrittori.

Il controllo reale è un interruttore apposito in Lovelace ed è **OFF
a ogni avvio o reload di HA**. Per abilitarlo servono modalità Automatica,
cavo realmente collegato e conferma di assenza di automazioni concorrenti.
Manuale non lo riabilita da solo. I parametri e gli override di UI
sono persistiti in HA Store, **non** cronologie continue.

## Dashboard e diagnostica essenziale

Due sensori aggiornati **soltanto quando cambia il significato del
risultato**, senza copiare ogni watt Shelly nel Recorder:

- `Johnny RC`: stato, motivo, modalità, ultima richiesta, conferma,
  ownership, fase e motivo di blocco.
- `Pianificatore RC`: target, partenza, fascia margine, avvio posticipato.
  Non pubblica un countdown al secondo.

Inoltre: selettore Automatica/Manuale; interruttori Controllo reale,
Avvio posticipato e Laboratorio H24; orario di avvio; override partenza;
pulsanti Carica subito / Pausa gestione / Riprendi / Annulla override.

Una dashboard Lovelace senza plugin esterni è in
[`docs/LOVELACE_RC.yaml`](docs/LOVELACE_RC.yaml). Sostituire i segnaposto
con gli ID generati dalla propria installazione (non inventati qui).

## Laboratorio H24: separato dal controllo reale

Il laboratorio può restare attivo **anche con cavo scollegato**, ma
**non impartisce alcun comando**. Usa i consumi Shelly osservati e
un'auto sintetica sempre in carica per generare decisioni RC virtuali.
Un JSONL privato al giorno viene scritto sotto
`/config/easywallbox_smart_lab/rc_shadow_YYYY-MM-DD.jsonl`, massimo
circa 2 MB/file. Non committare questi dati al repository pubblico.
È una prova sui consumi, senza vero SOC/partenza, senza ACK BLE.

## Riavvii, guasti e recupero

- Una sessione e un lease **non vengono mai recuperati automaticamente**
  dopo reload o reboot. Il controllo reale torna OFF. Nessun retry cieco.
- Dati `unknown`, `unavailable`, stantii, non coerenti, macchina non
  identificata o comando non confermato → niente nuovi comandi automatici.
- Se la wallbox resta con DPM 0 durante un guasto o una disinstallazione,
  **non** riattivarla alla cieca: verificare il limite originale, la
  presenza dell'auto e lo stato elettrico da ESPHome prima di intervenire
  manualmente. Nessuna promessa di avvio senza supervisione.
- **Limite noto da collaudare:** il firmware può non aggiornare spesso
  il registro DPM confermato. La RC richiede letture recenti per scrivere:
  quindi può restare intenzionalmente bloccata. Non aggiungiamo polling
  BLE continuo per aggirare questa condizione.
- I test automatizzati non certificano la sicurezza di linea, il
  funzionamento delle pinze o l'effetto fisico del DPM. Il collaudo va
  effettuato sul campo, con modalità Manuale e possibilità di rollback.

## Installazione / rollback

Questo branch non è `main` e **non è rilasciato sul Marketplace**.
Non sostituire la beta 0.2.0b5 prima della verifica CI e di una
installazione guidata. Il Config Flow RC richiede nuove entità: non migrare
la vecchia config entry facendo supposizioni sui sensori mancanti.
Prima di provarla, conservare la versione precedente e i suoi riferimenti.
Per tornare indietro, disabilitare Controllo reale, ripristinare la
versione precedente, riavviare HA e verificare manualmente DPM/ricarica.
Non manipolare `.storage` con editor o script.

Il repository firmware
[`Easywallbox---Esphome`](https://github.com/paolofaz/Easywallbox---Esphome)
rimane completamente separato e non modificato.
