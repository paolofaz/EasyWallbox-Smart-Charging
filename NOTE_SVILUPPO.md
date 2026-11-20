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
