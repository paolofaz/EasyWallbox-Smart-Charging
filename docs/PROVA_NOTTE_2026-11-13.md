# Prova di una notte, riproducibile senza auto (13 novembre 2026)

Questa è **la prima prova comparativa completa** prima di aggiungere altri
sensori o comandi alla custom integration. Non è una release HA.

## Domanda precisa

Se l'obiettivo è portare la Kia all'80% entro le 08:00, conviene
abbassare il limite della wallbox durante *tutto* il ciclo lavastoviglie,
oppure lasciare che il DPM riduca soltanto i picchi? Quanto costa
**dimenticare di ripristinare** il limite manuale?

## Dati di partenza e ipotesi

- [Osservato nella sessione] Kia 44,5%, target 80%, energia necessaria
  stimata 27,69 kWh **nella batteria**; orario di confronto 21:13.
- [Impostazione impianto] Soglia totale DPM 4,4 kW, sempre attivo.
- [Osservazione momentanea] Casa dopo cena nell'ordine di 0,2 kW.
- [Ipotesi di scenario] Potenza di rete EV con limite alto: **3,85 kW**.
  Non abbiamo una serie sincronizzata che dimostri questa potenza
  durante tutta la notte: non introdurre una correzione fissa di 150 W.
- [Ipotesi basata su una lettura puntuale] Potenza EV con limite ridotto:
  **3,00 kW**, simile ai 2,995 kW rilevati in uno screenshot.
- [Ipotesi] Efficienza da rete a batteria **85%**, non verificata per
  ogni fase di quella specifica sessione; è modificabile nel simulatore.
- [Scenario basato sulla precedente traccia lavastoviglie] Durata 102
  minuti, con 23 minuti totali di riscaldamento (cluster indicativi
  +4..12, +21..30 e +64..70 minuti) e incremento di carico 2,1 kW.
  È un esempio, NON la misura dei rami dell'impianto durante la
  serata della Kia.
- [Ipotesi] Consumo domestico restante stabile 0,2 kW. Altri carichi
  non rilevati qui possono cambiare completamente il risultato.
- [Modello] DPM **ideale e istantaneo**:
  potenza EV = min(limite EV, max(0, 4,4 kW - carico casa)).
  Il modello non rappresenta i ritardi reali del DPM né le protezioni
  per ramo. Sotto 1,4 kW di disponibilità la ricarica viene azzerata
  *solo nella simulazione*.

## Tre strategie identiche tranne la richiesta di ricarica

| Strategia simulata | Limite durante la lavastoviglie | Dopo OFF |
|---|---|---|
| DPM soltanto | limite alto (il DPM taglia nei picchi) | limite alto |
| Manuale con ripristino | limite basso per 102 minuti | limite alto |
| Manuale senza ripristino | limite basso per 102 minuti | rimane basso |

Con questi parametri il modello riproducibile `session_replay.py`
calcola, a partire dalle 21:13:

| Strategia | Fine stimata *nello scenario* | Margine alle 08:00 |
|---|---|---|
| DPM soltanto | circa **05:51** | +2h09 |
| Riduci e ripristina | circa **06:09** | +1h51 |
| Riduci senza ripristinare | circa **08:11** | **11 min oltre** |

Questi valori NON sono previsioni collaudate: dipendono fortemente
dai 3,85 kW ipotizzati con limite alto, dalla durata dei carichi
e dall'efficienza. Non usare la simulazione per cambiare limiti
elettrici o ignorare allarmi.

## Come si ripete senza auto

Il motore puro Python è in
`custom_components/easywallbox_smart/session_replay.py`.
I test in `tests/test_session_replay.py` verificano: confronto tre
strategie, interruzioni DPM ideali, energia alla partenza, effetti del
consumo domestico, calo di efficienza, parametri incoerenti e
assenza di invio comandi.

Dalla radice repository, senza Home Assistant:

```bash
python -m unittest discover -s tests -p 'test_session_replay.py' -v
```

Lo stesso caso è presentato in una **pagina HTML interattiva e
autonoma**, allegata nella conversazione ChatGPT del progetto:
seleziona Kia/Fiat, visualizza grafico/eventi e cambia i parametri.
La pagina HTML resta un prototipo **separato dall'integrazione HA**;
non richiede di collegare auto né di eseguire software sul server.

## Prima conclusione tecnica — da verificare, non da approvare a priori

La riduzione a 3 kW per tutta la lavastoviglie **può risultare
peggiore** del DPM attivo con limite alto: il DPM riduce la ricarica
solo durante i picchi, invece di mantenerla bassa durante tutto
il ciclo. Non vuol dire che sia sicuro aumentare il limite della
wallbox in qualsiasi situazione: l'utente ha allarmi di 4.600 W
globali e **3.700 W su ciascuno dei due rami domestici**;
questi ultimi **NON sono simulati** dal DPM ideale qui descritto.

Il futuro Smart Charging deve aggiungere valore **solo quando
reale**: organizzare l'avvio rispetto alla partenza, motivare
eventuali rinvii e ricordare un *proprio* limite ridotto (mai uno
impostato manualmente); evitare interventi BLE frequenti.
Se nei casi testati la raccomandazione ragionevole è «lascia il DPM
lavorare», essa non deve generare comandi.

### Prossima milestone proposta (ancora non implementata)

Inserire una **pagina di simulazione delle sessioni** accessibile
senza auto e una sintesi HA piccola (veicolo, partenza, target,
ETA alla potenza realmente misurata e motivazione della decisione).
Prima di qualsivoglia controllo reale, simulare casi di avvio,
pausa, override manuale, interruzione SOC e riavvio HA;
verificare che i confronti siano sensati e diagnostici.

**Non sono stati modificati** firmware ESPHome, DPM, automazioni
esistenti, protezioni o branch main.
