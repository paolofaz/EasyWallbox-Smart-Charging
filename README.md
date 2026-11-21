# EasyWallbox Smart Charging — Release Candidate

Custom integration nativa Home Assistant con **controllo reale** della
wallbox tramite le entità ESPHome esistenti. Nessun container, nessuna
modifica al firmware e nessuna dipendenza da dashboard di terze parti.
La wallbox conserva il **DPM attivo** per limitare i picchi elettrici;
Home Assistant esegue soltanto decisioni lente e verificate.

> **RC sperimentale**: test automatici e hassfest non equivalgono a
> collaudo elettrico. Prima del primo utilizzo reale verificare i sensori
> e disabilitare le automazioni HA che comandano indipendentemente
> `Charge power` o `Start-Stop`, in particolare lo Stop SOC Fiat
> legacy se si abilita lo Stop SOC dell'integrazione.

## Configurazione iniziale e autorizzazione

Menu **Impostazioni → Dispositivi e servizi → EasyWallbox Smart Charging →
Configura**. L'integrazione supporta:

- **Uno o più** sensori di potenza domestica selezionati liberamente,
  escludendo il ramo wallbox; Shelly wallbox separato per verificare
  assorbimento e arresto, senza creare sensori watt duplicati.
- ESPHome wallbox: sensori cavo, Charging, Telemetry Fresh, DPM Active,
  Fault, Charge Enabled, potenza EV richiesta e confermata, DPM
  confermato, Command status, switch Start-Stop e pulsante Refresh data.
- **Connessione BLE** ESPHome, facoltativa ma **fortemente consigliata**:
  con `Connection=OFF` la wallbox è semplicemente non disponibile,
  normalmente perché è spenta col teleruttore. L'integrazione resta
  caricata e si risveglia sugli eventi BLE ON, senza ricaricare HA o
  interrogare BLE continuamente.
- DPM positivo configurato (es. 4,4 kW), limite EV ordinario 4,0 kW
  e boost condizionato 4,2 kW. Il sensore DPM può riportare 0 A
  quando è in pausa; **nei calcoli si usa il DPM positivo configurato**.
- Profili auto aggiungibili, modificabili e rimovibili dalle Opzioni:
  SOC, target da entità o fisso, sensore cavo, capacità, rendimento,
  pulsante/tempo aggiornamento e orario feriale/weekend.
  **Nessuna potenza media AC manuale**: il planner la stima dai
  campioni Shelly e dalle letture EV, senza valori arbitrari.

**Abilita controllo automatico reale** è una singola autorizzazione
nelle **Opzioni**, **OFF per le installazioni precedenti**. Quando
abilitata e le automazioni concorrenti sono state disattivate,
il controllo rimane abilitato dopo il riavvio di HA ma **non invia
comandi prima di leggere dati coerenti**. Non esiste più lo switch
quotidiano «Controllo reale». Errori e ACK mancanti arrestano
le nuove azioni senza retry ciechi.

## Comandi quotidiani

| Entità | Significato |
|---|---|
| Modalità di ricarica | **Automatico** (gestisce) oppure **Manuale** (nessun comando dell'integrazione; usare ESPHome); torna Automatico alla disconnessione confermata |
| **Avvio ricarica posticipato** | Switch **di una sola sessione**. ON richiede una pausa fino all'orario scelto |
| **Inizia non prima delle** | Orario HH:MM associato allo switch; la prossima occorrenza deve essere nel futuro ed entro **12 ore** quando lo switch viene attivato o modificato |
| **Auto pronta entro** | Caricato automaticamente dall'orario feriale/weekend dell'auto riconosciuta; modificabile durante la sessione. Non interrompe la carica all'ora richiesta; è una scadenza da rispettare se possibile |
| Limite SOC (ove presente) | Slider 80–100% a passi di 5 solo per veicoli con target fisso e Stop SOC abilitato; se si usa un'entità target HA non si duplica |

**Esempio:** alle 20:00 il valore 19:00 significherebbe domani
alle 19:00, cioè 23 ore. **ON viene rifiutato**, non modifica
lo switch fisico e il sensore **Avviso ricarica** mostra il motivo.
Alle 20:00 scegliere 01:00 significa **domani alle 01:00**:
5 ore, richiesta valida. Sono ammesse fino a 12 ore **effettive**
di attesa, anche attraversando mezzanotte.

Se abiliti il posticipo **mentre l'auto sta già caricando**,
l'integrazione può richiedere **una sola volta Start-Stop OFF**
(DPM 0 A) dopo tutte le verifiche; non presume una pausa
elettrica riuscita senza BLE, Charging e Shelly <30 W.
All'ora programmata prepara e conferma il limite EV, poi
richiede Start-Stop ON e verifica il DPM positivo. Lo switch
**Avvio posticipato torna OFF soltanto quando Charging è
effettivamente confermato**, oppure allo scollegamento del cavo.
Non si disattiva automaticamente allo scoccare dell'ora se l'auto
non sta ancora caricando.

**L'orario posticipato esplicito non viene anticipato dal planner.**
Se l'ultima partenza utile stimata è 00:15 ma hai chiesto 01:00,
l'integrazione mantiene 01:00 e produce un avviso leggibile
del possibile mancato completamento entro la scadenza.

Se disattivi il posticipo prima dell'orario, il controller può
riprendere la ricarica appena la pausa DPM precedentemente
richiesta e **confermata da lui** è stata riconciliata.
Non riprende pause impostate manualmente o da altre automazioni.

## Preparazione, ricarica e fine sessione

1. Prima della ricarica il controller identifica un'unica auto,
   aggiorna i suoi dati una volta dopo 20 secondi dalla connessione
   (entrambe solo se non ancora identificata) e verifica SOC e target.
2. In Automatica, con DPM 0 A effettivamente gestito da questa
   integrazione, conferma **Charge power 4,0 kW** prima di riprendere
   con Start-Stop ON. La wallbox/DPM provvede ai picchi.
3. Durante Charging stabilizza l'EV lentamente: forte, moderato,
   finestra 5/7 min, ripristino su quiete 15 min; boost a 4,2 solo
   con marginalità <=60 min e isteresi fino a >=75 min.
4. Lo **Stop SOC facoltativo** è l'altra eccezione a Start-Stop
   durante Charging, solo per veicoli senza stop autonomo
   (es. Fiat). Per Kia, che gestisce il limite internamente,
   lasciarlo OFF. Non ci sono retry e si verifica fine carica
   tramite DPM 0 A, Charging OFF e Shelly <30 W.
5. Dopo cavo ON→OFF verificato e Shelly <30 W per almeno 30 s,
   una singola richiesta di parcheggio **Start-Stop OFF → DPM 0 A**.
   In Manuale il profilo ritorna Automatico al termine della sessione.

## Stati informativi e Recorder

- **Stato ricarica** (diagnostica)
- **Avviso ricarica** (testo: avvio rinviato, rischio orario, problema BLE;
  nessun messaggio aggiornato ogni secondo)
- **Veicolo rilevato** (nome o Nessuna)
- **Stabilizzatore** (INATTIVO/NORMAL/LIMITED/BOOST)
- **Energia residua stimata** (kWh AC fino al target, da SOC/capacità/rendimento)
- **Fine carica prevista** (stima arrotondata a blocchi di **10 minuti**)

Nessuna entità dedicata a watt, cavo, DPM o Bluetooth già esposti
dalla wallbox. Non vengono replicati nel Recorder i campioni dei
sensori Shelly: gli storici brevi del planner restano in RAM.
Lo stato viene pubblicato soltanto quando cambiano valori/decisioni
significative, non tramite un timer che aggiorna gli attributi
ogni minuto.

Le entità appartengono al dispositivo logico
**EasyWallbox Smart Charging**; ESPHome rimane il dispositivo
fisico separato. I vecchi pulsanti Carica subito, Pausa gestione,
Riprendi gestione, Annulla eccezione, Controllo reale e la
precedente data/ora eccezionale vengono rimossi dal registro
dell'integrazione senza toccare entità di terze parti.

## Sicurezza e rollback

- Modalità Manuale **non** cambia lo stato elettrico della carica:
  per fermare o regolare manualmente si usano i comandi ESPHome.
- BLE OFF / wallbox senza alimentazione è **normale**: nessuna
  azione e nessun polling aggiuntivo. Su BLE ON, riconciliazione
  prima di scrivere; un sensore cavo che rimane OFF per ore non
  diventa errore per il solo trascorrere del tempo.
- Se mancano dati, i sensori sono contraddittori, la carica non è
  verificata o manca un ACK, **nessun nuovo comando**. Nessun
  retry cieco di Start/Stop o disattivazione del DPM di sicurezza.
- Conservare la precedente release per rollback e fare un backup
  di HA prima dell'aggiornamento; non modificare mai manualmente
  `.storage` e non committare credenziali.
- La dashboard Lovelace auto-installata è un lavoro separato:
  questa RC usa le entità native nel dispositivo Home Assistant.

Per il primo collaudo supervisionato:
[`docs/CHECKLIST_COLLAUDO_RC.md`](docs/CHECKLIST_COLLAUDO_RC.md).
