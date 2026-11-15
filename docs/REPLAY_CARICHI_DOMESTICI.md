# Replay dei consumi domestici intermittenti — prova ferro da stiro

**Preparazione del 15 novembre 2026 — sviluppo M4, SOLO SIMULAZIONE.** La persona che utilizza la wallbox ha segnalato una sessione di stiratura in corso, mentre l'auto probabilmente non verrà collegata prima di sabato 21 novembre. Il carico del ferro è un buon caso di cicli termostatici, ma la forma reale dei cicli **non è ancora stata osservata**: non dedurre frequenze, altezze o intervalli dal nome dell'elettrodomestico.

## Obiettivo

Confrontare un pattern domestico reale con le proposte **virtuali** dello stabilizzatore M1/M4, mantenendo il DPM responsabile del controllo rapido dei picchi. Lo scopo non è ottimizzare il controllo elettrico second-by-second, né disattivare il DPM, né proporre start/stop basati su ogni ciclo.

In `tests/household_replay.py` è stato aggiunto un lettore rigoroso di tracce anonime e `replay_trace` che invoca il **core puro**. I test in `tests/test_household_replay.py` coprono cicli sintetici, intervalli di quiete, letture mancanti, misure obsolete, intervalli di campionamento irregolari e assenza di ricarica. Non sono dati dell'abitazione dell'utente: sono campioni generati esclusivamente per verificare il programma.

## Come fornire il pattern per l'analisi

- Va bene inizialmente uno **screenshot di Home Assistant** della curva di potenza, con scala, unità, durata e orari leggibili. Specificare se è un sensore del singolo ramo domestico o già il totale domestico **senza EV**: non sommare un totale a un ramo già incluso.
- Se si vuole un replay numerico più preciso, fornire una tabella CSV con campi `timestamp,power,unit,quality`; un timestamp ISO 8601 con fuso esplicito per riga, numeri con punto decimale, unità `W` o `kW`, qualità `ok` oppure `unavailable`/`stale`/`incoherent`.
- Per poter riprodurre la somma della casa con più Shelly, occorrono i dati sincronizzati di ciascun ramo oppure una serie del totale domestico che **escluda la wallbox**. Un singolo sensore isolato non rappresenta automaticamente l'intera casa.
- Non pubblicare i dati grezzi di consumo domestico sul repository pubblico: gli orari di attività domestica possono essere privati. Se ricevuti in chat, analizzarli localmente e inserire nei test GitHub **soltanto una traccia sintetica o anonimizzata**, se utile.
- Uno screenshot non consente di verificare con certezza campioni nascosti e qualità dello stream: distinguere sempre le misure osservate dalle interpolazioni.

## Come leggere il risultato

- `reduce`: proposta di **un solo limite virtuale**, non un comando BLE.
- `hold`: il limite virtuale resta stabile durante cicli brevi.
- `restore`: ripristino proposto dopo un intervallo realmente quieto (candidato 10 minuti) o per necessità del planner. Non equivale a un ripristino fisico.
- `insufficient_data`: manca un dato attendibile; **non** equivalere a 0 W.
- `inactive`: nessuna sessione di carica osservata. Nel replay della stiratura si può usare una *sessione EV artificiale*, marcata come ipotetica, per capire cosa avrebbe fatto il controllore se l'auto fosse stata in carica.

## Decisioni dopo aver visto i dati

Rilevare durata dei cicli ON, pause OFF, potenze e intervallo di campionamento. Valutare il comportamento con le soglie **candidate**, senza modificarle su una sola curva e senza introdurre controlli rapidi ridondanti rispetto al DPM. Ripetere eventualmente con consumi differenti prima di decidere una taratura. Durante il test reale di sabato 21 novembre mantenere il DPM e le automazioni esistenti invariati.

**Stato:** simulatore di replay pronto in CI; **pattern reale non ancora ricevuto né analizzato**. Nessuna nuova release, nessuna modifica al firmware, a `main` o alla wallbox.
