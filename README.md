# EasyWallbox Smart Charging

Integrazione Python nativa per Home Assistant che legge gli stati di
ESPHome e dei veicoli per pianificare le ricariche. Supporta più veicoli
configurati (es. Fiat 500e e Kia EV3).

> **Versione 0.0.13: sola osservazione e stima.** Nessun comando alla
> wallbox o alle auto. La prima v0.1 completa dovrà avere un vero
> pianificatore e una dashboard Lovelace, sempre in simulazione.

## Cosa mostra la 0.0.13

Solo le informazioni necessarie durante una ricarica:

1. Veicolo collegato
2. SOC attuale e SOC obiettivo
3. Energia ancora da caricare (kWh nella batteria)
4. Prossima partenza abituale
5. **Fine stimata alla potenza di ricarica attuale**

Inoltre è disponibile **Qualità dati**, classificato come entità
**diagnostica** e non come sensore principale.

La stima di fine è calcolata da:

`ore = kWh_mancanti_batteria / (potenza_effettiva_ricarica_kW × 0,90)`

Il rendimento AC 90% è **un'ipotesi provvisoria**, non una misura
dell'efficienza della Fiat o della Kia. La potenza effettiva va letta
da **Charging Power** ESPHome oppure dallo **Shelly sul ramo wallbox**,
non dai valori `Charge power` o `Power set` che rappresentano
limiti richiesti/confermati. L'orario stimato presuppone che la
potenza osservata rimanga costante; il DPM, la temperatura e i
consumi della casa possono cambiare il risultato.
In caso di sensori mancanti, obsoleti o carica ferma non viene
inventato un orario.

La previsione **non usa il consumo della cucina o il margine del
contatore come se fossero potenza di ricarica effettiva**.

## Configurazione

Installa la release di prova dal repository GitHub o copia la cartella
`custom_components/easywallbox_smart` nell'installazione HA;
riavvia Home Assistant e apri **Impostazioni → Dispositivi e servizi**.

Configura:
- I sensori di stato ESPHome (collegamento, telemetria).
- Uno o più veicoli con nome, sensori collegamento/SOC,
  capacità **utilizzabile** batteria e target abituale.
- **Una** delle tre modalità di misura:
  A. Casa misurata: uno o più sensori domestici, senza l'auto, e
     facoltativamente un sensore di potenza ricarica.
  B. Casa calcolata: totale impianto *inclusa auto* meno potenza
     ricarica effettiva; scegliere entrambi i sensori.
  C. Nessuna misura di potenza.

**Per vedere la fine stimata è necessario configurare anche il
sensore di potenza effettiva della ricarica** nel metodo A oppure B.
Il metodo C non può fornire un ETA reale. Nelle Opzioni →
Pianificazione si possono indicare potenza continuativa dell'impianto
e orari abituali di partenza feriali/weekend. Questi parametri NON
modificano il DPM.

La vecchia pagina sperimentale con `Charge power`, `Power set` e
**un solo sensore elettrodomestico** è stata rimossa dalle Opzioni:
non era un modello di configurazione generale soddisfacente.
I suoi eventuali valori salvati non causano più simulazioni o comandi.

### Pulizia dei sensori dalla 0.0.12

La 0.0.13 ritira le entità sperimentali ridondanti (potenza casa
duplicata, media necessaria, avvio consigliato, scenario di carico,
scenario 30% e decisione su elettrodomestico). **Durante l'avvio
elimina dal registro entità soltanto queste entità generate
da EasyWallbox Smart Charging**, identificate dal suo config entry ID.
Se le avevi inserite manualmente in schede/automazioni HA, rimuovi
i riferimenti obsoleti. Gli Shelly e le entità ESPHome non vengono
modificati. I dati e i comandi dei dispositivi restano invariati.

## Cosa ancora non fa

Non gestisce direttamente orari di avvio, ripristini dopo
lavastoviglie, eccezioni per sessione, o controllo della potenza:
sono requisiti futuri **da progettare, simulare e autorizzare**,
non funzioni già disponibili. Il codice dei primi esperimenti
matematici resta nel repository ma non genera sensori aggiuntivi.

Il **DPM** resta sempre attivo e si occupa dei picchi; la wallbox
non viene mai comandata da questa versione. Restano attive le
automazioni domestiche preesistenti, fino a una migrazione collaudata.

## Repository, rilascio e test

- `sviluppo-test`: sviluppo di tutte le release 0.x.
- `main`: non modificato senza consenso (può contenere solo LICENSE).
- Le release sono pacchetti sperimentali pubblicati da GitHub Actions.
- [Note specifiche v0.0.13](docs/releases/0.0.13.md).
- [Diario tecnico](NOTE_SVILUPPO.md).
- [Release precedenti](https://github.com/paolofaz/EasyWallbox-Smart-Charging/releases).
- I test automatizzati **non sostituiscono** il collaudo Home Assistant
  e la validazione della potenza effettiva.
- Rollback alla 0.0.12 scaricando la release precedente; alcune entità
  sperimentali potrebbero essere ricreate al ritorno alla versione
  precedente.

**Nota Marketplace:** `main` potrebbe non contenere il manifest e
`hacs.json`, quindi l'aggiunta da link potrebbe non riconoscere il
repository. In caso di errore non installare `main` come fallback:
usare esplicitamente la release di prova da GitHub e verificarla.
Non committare credenziali, PIN BLE o la cartella `.storage` di HA.

## Dimostrazione offline: una notte di ricarica senza auto

Prima di aggiungere altri sensori o rilasci HA, è disponibile un motore
di **replay deterministico di una sessione completa**, con tre scelte:
lascia il DPM, riduci per tutta la lavastoviglie e ripristina, oppure
riduci e dimentica. Il test su Kia 21:13 e partenza 08:00 evidenzia
che una riduzione prolungata può essere peggiore del DPM già attivo.

Non è un controllore e non invia comandi. Leggi
[la prova dettagliata](docs/PROVA_NOTTE_2026-11-13.md) e ripeti
i test puramente Python con
`python -m unittest discover -s tests -p 'test_session_replay.py' -v`.
La pagina HTML interattiva della stessa prova è stata allegata alla
conversazione ChatGPT del progetto: si apre in browser senza HA
o auto collegata. Nessuna release dell'integrazione è stata creata
per il solo prototipo di replay.

