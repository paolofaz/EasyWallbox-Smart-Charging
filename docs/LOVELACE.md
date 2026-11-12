# Dashboard Lovelace — requisito della v0.1 (simulazione)

**Decisione approvata il 12/11/2026:** EasyWallbox Smart Charging deve avere una **interfaccia Lovelace ad hoc**. Non deve essere soltanto un elenco di sensori e non va rimandata a v0.2/v1.0.

## Obiettivo dell'interfaccia

Dare una risposta immediata a:
- quale auto è collegata e quanto è affidabile il riconoscimento;
- SOC attuale, SOC obiettivo e scadenza prevista;
- energia richiesta, durata e margine temporale stimati;
- raccomandazione di inizio ricarica e sua **motivazione**;
- consumi **domestici separati** da quelli della wallbox;
- qualità/freschezza dei dati e limiti delle stime.

Il badge **SIMULAZIONE — NESSUN COMANDO INVIATO** deve essere sempre evidente nella v0.1.

## Layout previsto (da implementare e testare in v0.1)

1. **Sintesi sessione**: auto, stato sessione, SOC attuale/target, orario di partenza.
2. **Pianificazione**: kWh residui, tempo stimato, inizio consigliato, margine e motivo della decisione; per target 100% la stima rappresenta il raggiungimento indicativo del 100%, **non** il termine certo dell'eventuale bilanciamento celle.
3. **Potenza**: casa distinta dalla ricarica, usando una topologia di sorgenti scelta dall'utente (N sensori casa o totale con EV meno EV), con indicazioni di qualità, latenza e metodo impiegato.
4. **Diagnostica**: connessione wallbox, telemetria fresca, SOC vecchio, stati incoerenti; errori espliciti.
5. **Impostazioni non attuative v0.1**: obiettivo SOC effettivo della sessione (default dall'abituale), inclusa la scelta del 100%. Nessuno switch «Escludi obiettivo». **Controlli futuri**: Manuale, Pausa, Carica subito soltanto quando autorizzati; nessun comando wallbox in v0.1.

## Scelte tecniche iniziali

- Preferire **card Lovelace native** e dashboard dedicata in YAML o istruzioni per editor grafico; evitare dipendenze da plugin esterni senza benefici concreti.
- Fornire un esempio riutilizzabile con entity_id delle **entità proprie dell'integrazione**, non hardcodare quelli privati della casa.
- Le opzioni di configurazione delle sorgenti restano nel **Config Flow/Options Flow** dell'integrazione, non duplicate in Lovelace.
- La dashboard deve restare leggibile su desktop e smartphone.
- Progettare gli stati `unknown`, `unavailable`, incoerenti e i casi di stima non disponibile; non mostrare falsa certezza.
- La prima bozza Lovelace utilizzabile arriverà **insieme ai sensori simulati**; non inserire oggi riferimenti a entità inesistenti.

## Criteri di accettazione v0.1

- Dashboard importabile/realizzabile con istruzioni riproducibili, senza comandi verso le auto o la wallbox.
- Tutte le informazioni principali sono visibili e spiegabili.
- Stati mancanti non appaiono come carica completata, auto assente o previsioni certe.
- Nessun firmware o automazione esistente deve essere cambiato per visualizzarla.

**Stato:** requisito e progetto preliminare registrati; dashboard non ancora realizzata o collaudata.

## Modello dei target approvato il 12/11/2026

- Ogni veicolo ha `default_target_soc` **abituale**, modificabile nelle Opzioni dell'integrazione.
- La dashboard della v0.1 mostrerà **un solo target effettivo**, con modifica opzionale valida solo per la sessione; un override non diventa automaticamente il nuovo abituale. Riavvii HA non cancellano l'override di una sessione ancora valida.
- **Nessuna opzione «Escludi obiettivo»**. Impostando **100%**, il planner calcola energia e tempo fino al 100% ma il futuro controllo **non mette in pausa per SOC**, lasciando all'auto eventuale gestione/bilanciamento finale delle celle. Non deve forzare il riavvio di una sessione interrotta manualmente.
- Il limite SOC interno alla Kia/altre auto **non viene letto o impostato**. Se l'automobile interrompe prima del target HA, segnalare stop anticipato / obiettivo non raggiunto, senza retry Start/Stop.
- Solo dopo v0.1, test e consenso esplicito: **target HA inferiore a 100%** raggiunto → valutazione di una pausa mediante lo **switch di pausa ricarica** (ESPHome Start-Stop, limite DPM posto a 0 A). **DPM attivo sempre; non è uno switch di disattivazione DPM**. Occorrono conferma indipendente ed esclusione di stop già effettuati dall'auto.
- In v0.1 **nessun comando elettrico**; le automazioni preesistenti restano operative.

## Terminologia vincolante (12/11/2026)

- **DPM**: protezione e gestione dinamica del carico **sempre attiva**. Mai introdurre un controllo per metterlo su OFF.
- **Switch di pausa ricarica**: lo Start-Stop della integrazione ESPHome (entity ID specifico da confermare live). Nelle future versioni autorizzate la pausa è ottenuta richiedendo il limite DPM **0 A**, senza spegnere la funzione DPM. Il ripristino usa il limite valido precedentemente confermato, con verifiche e senza retry ciechi.
- Non confondere comando richiesto, conferma DPM non-zero, stato di ricarica e lettura elettrica Shelly.
- Obiettivo HA **100%**: nessuna pausa automatica per SOC; non interpretare il valore 100% come prova che il processo di bilanciamento sia terminato.
