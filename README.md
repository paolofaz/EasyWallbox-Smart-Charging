# EasyWallbox Smart Charging — Release Candidate

**Integrazione Home Assistant nativa, con controllo reale della wallbox.**
Nessun container, nessuna automazione esterna necessaria e nessuna modifica
al firmware ESPHome. Il **DPM fisico resta sempre attivo** e gestisce i
picchi rapidi: questa integrazione pianifica e regola lentamente il limite EV.

**Stato:** codice RC destinato a collaudo supervisionato. I test Python e le
verifiche del manifest non certificano gli effetti elettrici. Il controllo
reale è **disabilitato a ogni avvio o reload** finché l'utente non lo abilita.
Non consentire a due automazioni di comandare gli stessi elementi.

## Configurazione interamente grafica

In **Impostazioni → Dispositivi e servizi → Aggiungi integrazione →
EasyWallbox Smart Charging** si configurano:

- **Da uno a N sensori di potenza domestica**, selezionati liberamente:
  la somma rappresenta la potenza di casa, **escludendo il circuito EV**.
  Può essere uno Shelly o una combinazione di sensori indipendenti,
  non necessariamente due piani o due dispositivi.
- **Un sensore di potenza wallbox separato**, usato per confermare
  assorbimento EV e verificare la soglia di parcheggio di **30 W**.
- Wallbox ESPHome: sensori cavo e Charging, Telemetry Fresh,
  DPM Active, Fault, Charge Enabled, limite DPM confermato,
  `Power set` confermato, `Charge power` (entità number),
  `Start-Stop` (entità switch), `Command status` e
  il pulsante `Refresh data`.
- **Limite DPM positivo di riferimento**, normalmente **4,4 kW**,
  potenza EV ordinaria **4,0 kW**, boost **4,2 kW**.
- **Uno o più profili veicolo**: nome, sensore cavo, SOC, capacità
  utilizzabile della batteria in kWh, rendimento AC, orari di
  partenza feriali e weekend, eventuale pulsante aggiornamento dati e
  timestamp dell'ultimo aggiornamento.

**Dopo la configurazione puoi gestire le auto senza reinstallare:**
`Impostazioni → Dispositivi e servizi → EasyWallbox Smart Charging →
Configura` apre le **Opzioni**, da cui puoi **modificare tutti i campi
di un'auto**, **aggiungere una nuova auto** o **rimuoverne una con
conferma** (l'ultima auto non può essere rimossa). Il profilo SOC,
la sua sorgente target, sensori, refresh, capacità, rendimento e orari
sono tutti modificabili. Salvare le Opzioni ricarica l'integrazione
e disabilita per sicurezza il controllo reale, da riabilitare
soltanto dopo aver verificato la nuova configurazione.

Ogni veicolo richiede una **sola fonte per il SOC obiettivo**:
**Target fisso** (esempio 80%) oppure **Target da entità Home Assistant**
(esempio sensore del limite impostato in auto). È una scelta guidata
in due passaggi, non occorre compilare entrambe le opzioni.

La **potenza disponibile per pianificare viene calcolata dall'integrazione**:
non esiste un campo manuale "potenza AC media" o un valore fisso presunto
di 2,4 kW. Un breve storico Shelly domestico (finestra fino a 20 minuti,
75° percentile) permette di stimare il margine sotto il limite DPM
positivo configurato; durante la ricarica, uno storico valido della
potenza EV effettiva può correggere la previsione verso il basso.
Le letture sono mantenute temporaneamente **in RAM**, non trasformate in
nuovi sensori o scritte continuamente nel Recorder. Se mancano campioni
affidabili, la durata stimata è **sconosciuta**: non inventiamo un valore.
L'avvio posticipato rimane rispettato; per evitare di superare la
partenza si usa soltanto il limite EV configurato come **massimo
fisicamente possibile**, mai come media dichiarata. Il DPM continua
a proteggere l'impianto.

## Comandi reali: sequenza di sicurezza

| Evento | Azione |
|---|---|
| HA avviato con cavo già scollegato | Nessun comando automatico |
| Cavo wallbox **ON → OFF** verificato | Dopo **30 s** con Shelly EV **sotto 30 W**, una sola richiesta `Start-Stop OFF` → DPM 0 A, se autorizzata e confermata |
| Manuale → scollegamento | La modalità torna **Automatica** al termine della sessione |
| Cavo **OFF → ON** | Attende **20 s**, identifica l'auto e richiede il refresh dati una sola volta; non interpreta il pulsante premuto come dati confermati |
| Auto con SOC/target aggiornati | Calcola energia necessaria, ora di partenza e ultimo avvio utile |
| Partenza posticipata | Mantiene DPM 0 A finché l'ultimo avvio utile lo consente |
| Avvio consentito | Prima imposta/verifica il limite EV ordinario (es. 4,0 kW); **solo dopo** richiede `Start-Stop ON` |
| Ricarica effettivamente in corso | Cambia soltanto il numero `Charge power`, mai lo switch Start-Stop |
| Fine carica | Nessun avvio automatico; prepara la sessione successiva allo scollegamento |
| Dati incompleti, incoerenti o obsoleti | Nessuna nuova scrittura, blocco diagnosticato e **nessun retry cieco** |

**Start-Stop OFF non disattiva il DPM hardware.** Il firmware usa DPM
0 A per la pausa e conserva il limite positivo da ripristinare con
Start-Stop ON. È un comportamento già verificato sul firmware ESPHome.
La chiamata HA non è una conferma elettrica: il controller verifica
riscontri BLE, stato Charging e potenza Shelly.

**Il planner usa il limite DPM positivo configurato (es. 4,4 kW)
anche durante la pausa**. Il sensore DPM può allora indicare 0 A:
serve a confermare lo stato reale, non come riferimento matematico.

## Regole dello stabilizzatore

| Regola | Criterio |
|---|---|
| Carico forte | Pressione nominale ≥0,6 kW per 2 minuti, oppure cicli intermittenti significativi; cap basato sul 75° percentile dei campioni recenti |
| Carico moderato | Casa tra 450 e 1.100 W con pressione ≥100 W, per 10 minuti osservati negli ultimi 12 |
| Già in LIMITED | Ulteriore correzione di 0,4 kW quando pressione ≥250 W è stata osservata per 5 minuti su 7 ed è ancora presente |
| Recupero | Ripristino diretto al limite ordinario dopo 15 minuti di quiete documentata |
| Boost | +0,2 kW solo con casa <150 W per 15 min e **margine alla partenza ≤60 minuti** |
| Isteresi boost | Uscita con casa >200 W; uscita per margine recuperato solo quando ≥75 minuti stabili |
| Sicurezza | Nessuna regolazione continua dei picchi: li governa il DPM fisico |

I livelli iniziali sono configurabili nei passi consentiti dal firmware;
le riduzioni non possono scendere sotto il minimo EV supportato.

## Controlli e diagnostica

L'integrazione espone modalità **Automatica/Manuale**, abilitazione
esplicita del controllo reale, **Avvio posticipato**, ora preferita,
override della prossima partenza e pulsanti Carica subito, pausa/ripresa
della gestione e annullamento override.

Sono presenti soltanto **due sensori diagnostici** per stato della
sessione e pianificazione. Non ripubblicano ogni watt Shelly e non
producono un countdown al secondo nel Recorder.

La dashboard personalizzata installata automaticamente dall'integrazione
**non è ancora presente**: i controlli sono accessibili dalle entità HA.
Non viene creata né alterata automaticamente una dashboard dell'utente.
L'interfaccia integrata è un obiettivo separato da collaudare.

## Riavvii, installazione e rollback

L'autorizzazione ai comandi reali torna **OFF** a ogni riavvio, reload
o reinstallazione; il riavvio HA non cambia da sé lo stato elettrico
della wallbox. Preferenze e orari possono essere recuperati, ma lo
stato fisico viene sempre verificato prima di una nuova azione.

Per passare dalla precedente beta occorre installare una prerelease
della RC tramite Home Assistant Marketplace e poi riavviare HA.
Se in Config Flow compaiono `house_downstairs`,
`house_upstairs`, `target_default` o `sustainable_kw`,
**non è stata caricata questa RC**: verificare i file effettivamente
presenti in `custom_components/easywallbox_smart` e l'entry esistente.
Non correggere direttamente i file `.storage`.

Leggere [la checklist dei collaudi](docs/CHECKLIST_COLLAUDO_RC.md)
prima di abilitare i comandi; per rollback disabilitare Controllo reale,
controllare il DPM e ripristinare la versione precedente.
