# Contratto M1 — SOLO simulazione

`new_state, proposal = evaluate(now, session, house, limits, previous_state, config)`

## Sorgenti e modellazione
- `SessionSnapshot`: un solo veicolo univoco, modalità AUTO/MANUAL/PAUSE, `charging` osservato, SOC e istante, target, partenza, capacità utilizzabile, rendimento AC e potenza sostenibile stimata. Se manca un dato, `Plan.reason` spiega perché non si consiglia un cap.
- `HouseSnapshot`: somma `downstairs_kw + upstairs_kw` in kW, senza wallbox. `quality=ok` è attestata dall'adapter; zero e dati mancanti sono fatti diversi. Il terzo Shelly misura solo EV, non entra nel trigger.
- `LimitSnapshot`: massimo richiesto e confermato ESPHome, flag di proprietà manuale; in simulazione il cap non altera nessuno dei due valori.
- `CoreState`: due stati NORMAL/LIMITED, limite originario e cap virtuale, candidato iniziale, quiete, cooldown, budget consumato cumulativamente; permane soltanto in RAM nel M1.
- `Proposal`: `action`, `state`, `proposed_cap_kw`, `reason`, `slack_minutes`, `budget_kwh`, `spent_kwh_upper_bound`, `next_check_at`, `simulation_only=True`. Le azioni non sono comandi.

## Politica candidata
- All'avvio non si impone un cap; serve carica realmente in corso, sessione AUTO, flessibilità calcolabile, dati casa buoni e limiti ESPHome coerenti.
- Carico casa significativo `>=1.5 kW`, confermato da una seconda osservazione dopo almeno 60 s e entro 180 s. La seconda osservazione può essere una verifica evento/timer su stato HA attendibile, non un secondo pacchetto BLE.
- Un unico cap `floor_step(4.3 - casa - margine, 0.2)`, min 1.4 kW, riduzione utile almeno 0.6 kW. Il 4.3 rappresenta SOLO un candidato del modello DPM usato nell'impianto di prova, non limite contrattuale o dispositivo.
- LIMITED resta invariato mentre la casa oscilla, finché non ci sono 10 min di quiete `<=1.0 kW` documentata; ripristino virtuale diretto al massimo originale e cooldown 10 min.
- Il planner ricalcola il tempo necessario a caricare l'energia residua da SOC, target, capacità, rendimento, potenza sostenibile, ora della partenza e riserva. Se il margine decade o il budget è consumato, propone subito ritorno al limite originale, lasciando agire DPM.
- In M1 il budget è `25%` del margine di tempo moltiplicato per potenza sostenibile: SOLO ipotesi interna di simulazione, non decisione approvata. `spent_kwh_upper_bound` usa (limite originale − cap) × tempo trascorso, anche con osservazioni mancanti: prudente ma non perdita AC misurata.
- Se durante LIMITED arriva una modifica manuale, nessun ripristino su limite altrui; la proposta virtuale viene ritirata.
- Se la sessione termina, il core dimentica il cap virtuale senza inviare comandi, evitando confusione tra stop reale e limite immaginario.

## Eventualità da verificare prima di HA
- Replay HA `time_throttle`: l'utente conferma che un valore storico non aggiornato è spesso rimasto stabile. Il replay può ricostruire l'ultimo valore valido dichiarandone la provenienza; **non** può equiparare `unknown`, `unavailable`, offline, perdita timestamp o sensori incoerenti alla stabilità.
- Nel live, un sensore che non cambia `last_changed` non è automaticamente guasto; il futuro adapter deve verificare salute e letture disponibili secondo API HA correnti e le specifiche Shelly.
- Questo core non pianifica ancora il momento di inizio della carica né il calendario feriali/weekend; per M1 testa il **budget di stabilizzazione durante una carica già attiva**. Il planner completo e il config flow arriveranno dopo la validazione di questo contratto.
- La v0.1 non può attuare `reduce`/`restore`. Per una futura v0.2 serviranno conferme e interlock espliciti. Nessuna modifica a firmware/automazioni legacy.
