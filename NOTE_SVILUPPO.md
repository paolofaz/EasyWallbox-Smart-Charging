# NOTE_SVILUPPO — ramo RC

## 20 novembre 2026 — ricostruzione pulita

**Scopo:** una sola integrazione RC nativa HA, con controllo reale
esplicitamente abilitabile, due modalità, avvio posticipato, override della
partenza, Johnny RC e laboratorio H24 indipendente.

**Origine:** branch `stabilizzatore-m1` HEAD
`a8c57b8d1d6b86db303779f50ea4e209404dceed`.
Branch `RC` creato su richiesta dell'utente. `main`, altri branch
e firmware ESPHome conservati.

**Regola più recente che prevale:** con cavo scollegato, nessuna scrittura
alla wallbox. La precedente proposta AUTO_READY con DPM zero pre-connessione
è quindi ritirata. Con cavo collegato e Charging vero soltanto EV number;
con Charging verificato falso, soltanto Start-Stop per avvio posticipato.
Se Charging diventa vero prima della pausa, Johnny non tenta uno stop
tardivo. La UI spiega il limite.

**Policy:** base 4,0, boost 4,2 soltanto con margine ≤60 minuti e casa
<150 W per 15 min; >200 W esce, margine >=75 min per rientro (isteresi).
Forti dopo 2 min, moderati su 10/12 min, ulteriore riduzione dopo
5/7 min in LIMITED a pressione ≥250 W, con ripristino diretto dopo
15 min documentati; conteggi riavviati dopo variazione.

**Comandi:** un solo dispatcher usa servizi HA di number/switch.
Richiesta non equivale a BLE confermato, DPM0 non equivale a spegnere il
DPM attivo. Il firmware arrotonda Power set a 0,1 kW e può mantenere
vecchia la lettura DPM; impossibile garantire un ACK raw esatto dal solo
pubblicato. Necessaria prova reale con comandi supervisionati e verifica
indipendente dell'effetto; nessun retry.

**Persistenza:** preferenze UI salvate tramite Store, non campioni.
Autorizzazione al controllo reale e lease non persistiti: dopo riavvio
controllo reale OFF. Recorder solo su cambi semantici. Laboratorio
scrive JSONL privati fuori dal repository e dal Recorder, solo su nuovi
campioni e con limite dimensione.

**Test ancora necessari:** prima installazione, HA 2026.11, registrazione
entità, config/options flow e traduzioni; reale qualità/freschezza dei
sorgenti DPM e command status, pause/resume dopo l'inserimento cavo,
BLE offline, SOC lento, automazioni Fiat, target Kia, reboot con DPM=0,
Manuale durante cap, override e scadenza partenza, time zone/DST.

**Invarianti di sicurezza:** DPM sempre attivo, nessun comando quando
cavo scollegato, nessuna azione a stati incerti, nessun Start/Stop durante
Charging, nessuna doppia gestione delle stesse entità.

**Nessun test automatico o parere di progetto è un collaudo elettrico.**


## 20 novembre 2026 — RC: lifecycle e refresh confermati

**Decisione utente**: abbandonato il veto assoluto ai comandi con cavo
scollegato; unica eccezione `Start-Stop OFF` dopo transizione fisica
ON→OFF confermata da wallbox + Shelly EV <30 W per almeno 30 s.
Un solo tentativo, conferma DPM0 e Charge Enabled OFF. Nessuna
azione se si trova già scollegata all'avvio HA. Il firmware ESPHome
Start-Stop è già stato testato e non viene modificato.

**Modalità**: durante Manuale, nessun comando automatico di carica.
Alla fine sessione (cavo OFF) ritorno ad AUTO; conservazione del
consenso al parcheggio solo se il controllo reale era stato esplicitamente
abilitato. AUTO con cavo ON e wallbox parcheggiata verifica un solo
veicolo, SOC, target, capacità, efficienza, programma di partenza e
ultimo avvio sicuro; attende eventuale orario posticipato; verifica
EV 4,0 kW prima di uno `Start-Stop ON`; controlla DPM positivo dopo
l'effetto. In carica Johnny può scrivere soltanto il limite EV.

**Refresh**: dopo 20 s di cavo ON, `button.press` dell'auto identificata,
o entrambi se l'identità è ancora ignota, una sola richiesta senza retry.
Sorgente `last info update` opzionale, altrimenti nuova pubblicazione
SOC dopo la richiesta; attesa massima 120 s per nuovi dati. Se non
arrivano, niente avvio. Il pulsante ESPHome Refresh data viene richiesto
nel Config Flow e usato soltanto al collegamento e, se necessario,
una seconda volta quando si deve riprendere dopo una lunga attesa.
Il laboratorio non preme questi pulsanti.

**DPM**: per i calcoli usare il limite POSITIVO configurato
(es. 4,4 kW), mai lo zero del sensore durante la pausa. Il sensore è
una conferma dello stato osservato. DPM Active rimane ON. Valori
positivi divergenti o stantii sospendono scritture automatiche.

**Riavvii**: stato fisico invariato. Provenienza di un DPM0 verificato
persistita, ma dopo reload/riavvio `Controllo reale` OFF per
autorizzazione esplicita; nessun avvio cieco. Non si tentano retry
di alcun comando. Manuale, PAUSA gestione, SOC mancante e sorgenti
contraddittorie sono veti.

**Stato di sviluppo**: ramo `RC`; `main` e repository ESPHome
invariati. Nuovi test simulano richiesta di parcheggio dopo quiete,
refresh veicolo dopo 20 s, pre-arming con EV 4 kW, ACK successivi e
nessun Start-Stop su una carica in corso.
Test automatici e validazione manifest NON costituiscono collaudo
elettrico. Nessun file privato o credenziale inserito su GitHub.
