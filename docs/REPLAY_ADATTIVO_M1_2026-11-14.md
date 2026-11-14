# M1 — Replay regolatore adattivo e planner (14 novembre 2026)

**Stato:** simulatore offline Python puro, non una release o una funzione attiva in Home Assistant. Il firmware ESPHome e il DPM non vengono comandati o modificati.

## Obiettivo

Confrontare sullo **stesso** consumo domestico tre strategie:
1. **Solo DPM:** limite wallbox originale di 4,0 kW, con modulazione autonoma simulata
2. **Limite fisso:** 2,0 kW per tutta la sessione, scenario «mi dimentico di rialzarlo»
3. **Adattivo:** primo superamento totale valido della soglia 5,0 kW; riduzione proposta usando **solo** potenza casa senza wallbox; memoria dei successivi riscaldamenti domestici, recupero graduale e veto se la partenza è a rischio

Nessuna fascia preferenziale o riconoscimento elettrodomestico. Il planner mantiene soltanto il vincolo della **partenza**.

## Scenario sintetico riproducibile

- Inizio venerdì 13/11/2026 alle **21:13** (Europe/Rome), partenza sabato **08:00**
- Energia ancora necessaria **24 kWh in batteria** (esempio, **non** il SOC reale della Fiat/Kia)
- Potenza impianto 4,4 kW; soglia allarme 5,0 kW; cap alto 4,0 kW, basso 2,0 kW
- Casa normalmente 0,35 kW, con cinque episodi ipotetici da 2,5 kW: minuti 3–11, 28–35, 66–73, 108–115 e 151–157 dall'avvio
- Efficienza rete-batteria 90% **ipotizzata**, non misurata; potenza sostenibile per stimare lo slack del planner **3,2 kW ipotizzati** e riserva 30 minuti **ipotizzata**
- Campionamento sintetico ogni **20 secondi**. Il ritardo di risposta DPM **non è noto né misurato**. Per testare la sensibilità si considerano **0, 20 e 40 secondi**, valori artificiali.
- Il cap simulato reagisce al campione successivo, **senza simulare il ritardo del comando BLE, letture asincrone o interventi dell'auto**. Non dedurre fattibilità di controllo reale dalla simulazione.
- Il modello assume che se la potenza disponibile scende sotto 1,4 kW l'auto non carichi: semplificazione non verificata sul dispositivo.

## Risultati eseguiti localmente sullo scenario (DPM ipoteticamente ritardato di 20 secondi)

| Strategia | Episodi sintetici >=5 kW | Durata >=5 kW | Cap simulati cambiati | Energia alla partenza | Fine stimata |
|---|---:|---:|---:|---:|---|
| Solo DPM | **5** | 100 s | 0 | 24 / 24 kWh | **04:11** |
| Limite fisso 2,0 kW | **0** | 0 s | 0 | **19,358 / 24 kWh** | **Non raggiunta** |
| Adattivo **prima** correzione (risalita troppo precoce) | **5** | 100 s | 25 | 24 / 24 kWh | **05:09** |
| Adattivo **con memoria carico domestico** | **1** | 20 s | **7** | 24 / 24 kWh | **05:53** |

Il risultato precedente alla correzione viene riportato come confronto di sviluppo; il codice del repository implementa ora **solo** la variante corretta. La differenza fra 04:11 e 05:53 è il costo temporale del cap aggiuntivo, nel modello.

Per una domanda più urgente di **27 kWh** dalla stessa ora di partenza, la simulazione adattiva recupera il cap quando il margine scende sotto la guardia e può produrre **3 episodi**, mantenendo target raggiunto. **Questo è un trade-off di ottimizzazione, non un rilassamento dei limiti elettrici: il DPM non viene toccato.**

### Sensibilità fondamentale del risultato al DPM

| Ritardo DPM **ipotizzato** | Solo DPM: episodi >=5 kW | Adattivo: episodi >=5 kW |
|---|---:|---:|
| **0 secondi** (ideale) | 0 | 0 |
| **20 secondi** | 5 | 1 |
| **40 secondi** | 5 | 1 |

**Non è una misura del DPM reale.** Se il DPM è effettivamente istantaneo per i consumi rappresentati, un modello ideale non prevede né allarmi né benefici del nostro cap. Le notifiche reali oltre 5 kW dimostrano che occorre chiarire le dinamiche elettriche, i timestamp e la misura totale prima di abilitare qualsiasi comando.

## Come il regolatore simula la risalita

Il primo allarme viene riconosciuto *dopo* il suo verificarsi: si possono prevenire soltanto episodi successivi. Il cap viene calcolato da `4,4 − casa − 0,2` (passo 0,2 kW; mai inferiore al minimo firmware ammesso).

Con cap ridotto la casa può tornare a 2,5 kW **senza superare 5 kW**, perché la wallbox è già limitata. Perciò il regolatore considera **anche questi riscaldamenti domestici**: finché si ripresentano, la finestra di «tranquillità» viene rinviata. La variante di test richiede **35 minuti dall'ultima lettura domestica elevata rispetto al picco che ha avviato il cap**, poi la finestra mobile di 5 minuti permette, se coperta da dati freschi e coerenti, una risalita per passi massimi di 0,4 kW ogni 5 minuti.

- **35 minuti non sono approvati come taratura definitiva**: derivano dall'esigenza di testare pause intermittenti dell'ordine di 25–37 minuti osservate nei CSV **filtrati a un minuto**, che non certificano la durata reale delle pause.
- Il riconoscimento di una nuova fase domestica usa una soglia interna derivata dal consumo casa misurato al primo allarme (70% con minimo candidato 1,0 kW). Non richiede configurazioni per elettrodomestico.
- Se il margine residuo stimato del planner scende sotto la guardia ipotetica di 20 minuti, il cap facoltativo viene rimosso **solo all'interno della simulazione**. Un'altra modifica manuale dell'utente non deve mai essere sovrascritta nella futura integrazione attuativa.
- Nessun valore `unknown` / `unavailable` / stale abilita una nuova modifica facoltativa.

## Riproduzione

Dalla radice del repository:

```bash
PYTHONDONTWRITEBYTECODE=1 python -m unittest discover -s tests -p 'test_adaptive_replay.py' -v
```

Il file `custom_components/easywallbox_smart/adaptive_replay.py` espone `dishwasher_example()` e `run_replay(scenario, strategy)`; le strategie sono `dpm_only`, `fixed_low` e `adaptive`.

Gli otto test offline aggiunti coprono confronto notte, DPM ideale, sensibilità al ritardo ipotetico, partenza più urgente, energia zero, validazioni, passaggio ora legale/solare Europe/Rome e assenza I/O. **I test sono stati eseguiti in laboratorio locale sul codice della simulazione; i risultati della CI GitHub/HA runtime vanno verificati separatamente**.

## Cosa NON prova questa analisi

- Non ricostruisce il tempo reale di risposta DPM né il picco effettivo sopra 5 kW.
- Non certifica che 35 minuti / 400 W / 5 minuti siano ottimali.
- Non simula tempi di conferma BLE, variazioni di assorbimento del veicolo, pause reali, limiti per ramo, restart HA o errori del contatore.
- Non usa come input nel repository il file CSV domestico privato: il `time_throttle` a un minuto può perdere picchi reali e rende la controfattuale indimostrabile.
- Non garantisce il completamento su una Kia o Fiat reale: capacità, SOC, efficienza e potenza sostenibile devono essere verificati.

## Vincolo persistente: non riempire il Recorder

- **M1:** modulo puro, scenari sintetici in memoria, nessun import HA, nessuna lettura/scrittura di file, nessun servizio BLE/HA, nessun salvataggio campioni. L'eventuale `first_actions` del replay contiene **massimo 30** eventi diagnostici in RAM.
- **M2 futuro:** listener dei Shelly puntuali **solo durante ricarica**, con deque 20 minuti / 1200 campioni in RAM; stop immediato/clear quando la carica finisce; no sensori di telemetria duplicati o pubblicazioni a ogni campione.
- Il vecchio `sensor.py` della 0.0.13 contiene ancora un aggiornamento di entità ogni due minuti: da **sostituire e collaudare** prima della release v0.1, senza modificare le automazioni o il Recorder dell'utente.

## Iterazione successiva

1. Rileggere i test e la CI sul ramo isolato; correggere eventuali fallimenti.
2. Raccordare `slack` con sessione, SOC ufficiale, potenza misurata e fonte della stima prudente (oggi ipotesi esplicita).
3. Confrontare la sensibilità alle finestre (per es. 20/30/35/40 minuti), anziché considerare migliore solo lo scenario che produce meno allarmi.
4. **Prima del futuro controllo autorizzato**: verificare i dati puntuali Shelly, la risposta effettiva del DPM e l'assenza di conflitti con le automazioni legacy.
