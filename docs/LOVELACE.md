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
2. **Pianificazione**: kWh residui, tempo stimato, inizio consigliato, margine e motivo della decisione.
3. **Potenza**: casa (piano terra + primo piano) distinta dal ramo wallbox, con indicazioni di qualità misura.
4. **Diagnostica**: connessione wallbox, telemetria fresca, SOC vecchio, stati incoerenti; errori espliciti.
5. **Controlli futuri**: Manuale, Pausa, Carica subito e deroghe solo quando esisteranno semantiche/test autorizzati. **Nessun controllo operativo in v0.1**.

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
