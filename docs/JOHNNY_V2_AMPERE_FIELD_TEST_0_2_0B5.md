# Johnny V2 — prova quasi definitiva ampere-aware (0.2.0b5)

**Solo simulazione, branch `stabilizzatore-m1`, non Marketplace.**
Nessun comando reale, nessuna modifica al DPM fisico, firmware ESPHome,
auto, automazioni legacy o release `main` 0.1.0.

## Decisioni di progetto: confermate / sperimentali

**Confermate per la prova:** un solo Johnny V2 (non più wide/medium live);
modello del DPM a **4,4 kW nominali**, pari al comando firmware **19,1 A**;
EV massimo **4,2 kW nominali**, pari al comando firmware **18,3 A**.
Per il laboratorio imposta manualmente 4,2 kW nelle Opzioni, perché i valori
della precedente installazione vengono mantenuti durante l'upgrade.

**Sperimentali, da misurare:** la soglia DPM da 4,4 kW è una corrente
equivalente nominale, **non** un limite assoluto di 4,4 kW attivi al
contatore. La tensione e il fattore di potenza reali possono differire.
L'installatore deve confermare la compatibilità con la potenza contrattuale,
la protezione del ramo e la posizione del trasformatore DPM. Il manuale
easyWallbox raccomanda di basarsi sul limite contrattuale e sulla portata
del circuito. In particolare, 19,1 A × 240 V ≈ **4,58 kVA**, prima di
considerare fattore di potenza e il margine dinamico della wallbox.
Non esiste una garanzia software che DPM 4,4 visualizzato implichi
prelievo effettivo <=4,4 kW in tutte le condizioni.

## Modello in ampere e dati Shelly

ESPHome codifica gli slider tramite `raw = int(kW/0.23*10 + 0.5)`;
la wallbox riceve decimi di ampere via indici BLE 158 (DPM) e
174 (richiesta EV). Il modello esegue **la stessa quantizzazione
a 0,1 A** prima di confrontare limiti.

I Shelly EM misurano potenza **attiva** in W con tensione RMS reale e
potenza reattiva. Il solo watt attivo diviso per 230 V è una **corrente
equivalente approssimata**: non misura direttamente gli ampere DPM, dato
che i carichi domestici hanno fattori di potenza e tensioni differenti.
Questo è dichiarato sia nella diagnostica sia nel file JSONL.
Il DPM reale resta responsabile dei picchi, autonomo e sempre attivo.

## Regole V2 proposte per il replay

- **Carico moderato persistente:** consumo domestico 0,45–1,10 kW,
  pressione DPM equivalente >=0,10 kW per **3 minuti**, su nuovi
  campioni Shelly con gap <=150 s. Un solo cuscinetto nominale
  **−0,4 kW** sul massimo EV (4,2 → 3,8 kW nel test).
- **Uscita dal cuscinetto:** richiesta originaria senza più di
  **0,18 kW** di pressione equivalente per **10 minuti** osservati;
  cooldown 10 minuti per evitare oscillazioni. Migliora la vecchia
  soglia assoluta di 350 W.
- **Carico forte:** eredita la regola Ampio: pressione equivalente
  **0,6 kW**, riconosciuta dopo **2 minuti** continui, con memoria dei
  cicli intermittenti nella finestra da **5 minuti**. Una riduzione
  iniziale robusta basata sul carico osservato, non sulla media globale.
- **Correzioni forti eccezionali:** se, *anche con cap attivo*, rimane
  pressione >=0,25 kW per almeno **5 minuti**, massimo due gradini
  da −0,4 kW, distanziati almeno **10 minuti**. Non inseguire i picchi.
- **Ripristino carico forte:** 15 minuti di quiete della pressione
  originaria, con isteresi. DPM mantiene la risposta immediata.
- **Dati obsoleti:** niente nuova proposta basata su letture non
  valide, niente comando BLE; nel laboratorio il recupero è
  virtuale e marcato come tale.

Queste soglie sono **candidati**, non parametri definitivi del
futuro controller. Il laboratorio infinito ignora intenzionalmente
SOC, arrivo, partenza e budget: questi resteranno vincolanti
in un eventuale controllo reale.

## Installazione del pacchetto di prova

1. Apri la [GitHub Action di sviluppo](https://github.com/paolofaz/EasyWallbox-Smart-Charging/actions/workflows/shadow-test-package.yml)
   e seleziona un run **riuscito** sul branch `stabilizzatore-m1`,
   verificando artifact `easywallbox-shadow-0.2.0b5`.
2. Salva una copia della cartella attuale
   `/config/custom_components/easywallbox_smart`.
3. Sostituiscila con la cartella `easywallbox_smart/` nello ZIP;
   riavvia Home Assistant. Non installare due versioni del dominio.
4. In Impostazioni → Dispositivi e servizi → EasyWallbox Smart Charging →
   Configura / Opzioni → Potenza EV e prova Johnny V2 in ampere,
   imposta massimo EV **4,2 kW** e abilita il laboratorio se disattivato.
   È soltanto la richiesta virtuale EV, non un comando fisico.
5. Verifica il sensore `Johnny V2 — laboratorio` e l'attributo
   `shadow_log_status = ok`.
6. Il file nuovo è
   `/config/easywallbox_smart_shadow/shadow_v2_amps_YYYY-MM-DD.jsonl`.
   Conserva i vecchi `shadow_v2_*` solo come storico del laboratorio
   precedente, non vengono sovrascritti.

Il file contiene timestamp, qualità del dato, `house_window`
(min/max/media/numero campioni), corrente equivalente domestica,
corrente BLE dei due limiti, origine del DPM effettivamente
osservato, ragioni e transizioni V2. Scrittura circa ogni minuto
e immediata sulle modifiche di stato; max 2 MB/giorno.
Nessun polling ESPHome aggiuntivo, nessuna scrittura BLE.

**Ricarica reale:** se desideri testare la coppia DPM 4,4 / EV 4,2,
i relativi slider ESPHome vanno modificati separatamente, manualmente,
solo dopo aver verificato con l'installatore il limite ammissibile.
Non confondere questi slider con quelli della beta, che sono virtuali.

## Riavvii / rollback / prossimi passi

Il reboot della beta azzera il V2 **virtuale** e lo segnala nel log
(`virtual_state_reset_on_this_row`). Non salva un cap elettrico perché
questa release **non invia limiti**. Prima di una futura versione
supervisionata: unico proprietario del comando, persistenza minima
(sessione, limite originario, limite richiesto/confermato), lettura
ESPHome prima di riprendere, conferma e verifica Shelly,
conflitti manuali, sessione terminata, DPM=0 e rollback senza
retry ciechi.

Per fermare il laboratorio, disabilitarlo nelle Opzioni;
per rollback completo, rimettere la cartella precedente e
riavviare Home Assistant. `main` resta alla release 0.1.0.

Per validare il candidato, raccogliere normali consumi domestici
e una sessione ricarica ordinaria, senza creare sovraccarichi:
controllare transizioni, correzioni, tempo in cap, perdita teorica
di energia e se la pressione nominale corrisponde alle reali
modulazioni DPM e letture Shelly. **Mai attribuire al laboratorio
l'effetto elettrico non ancora comandato.**
