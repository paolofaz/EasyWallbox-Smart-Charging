# Banco prova delle strategie: replay read-only

Modulo `custom_components/easywallbox_smart/replay.py`, utilizzabile
**fuori da Home Assistant**, senza comandi alla wallbox o alle auto.

## Scopo

Confrontare limiti di potenza EV differenti sulla stessa traccia di consumi
domestici. Il modello assume **solo per il test** che un DPM ideale limiti
istantaneamente la potenza EV affinché:

`potenza_casa_misurata + altri_carichi_ipotizzati + potenza_EV <= limite_impianto`

Per ogni limite EV restituisce kWh teorici assorbiti dall'auto, kWh di
riduzione teorica, minuti e periodi in cui sarebbe servita una limitazione.
**Questi non sono interventi del DPM realmente osservati**. Non rappresenta
il comportamento temporale BLE/DPM, né il bilancio energetico della batteria.

Le misure devono essere dichiarate complete oppure parziali: se arrivano
da un solo ramo Shelly, aggiungere solo come *scenario* un valore esplicito
degli altri carichi, senza considerarlo dato misurato.

La sorgente filtrata, con timestamp e valori non uniformi, viene
integrata per intervalli a gradini. Eventuali `unknown`, valori incoerenti
o intervalli con letture obsolete sono **esclusi**, non trasformati in zero.
La scelta dello staleness massimo è esplicita.

## Esito indicativo del primo ciclo, non salvato in GitHub

Il CSV fornito dall'utente rimane privato e **non viene committato**.
Ciclo 12/11 22:37–13/11 00:19, budget impianto 4,4 kW, ramo casa
misurato (solo uno) e ulteriori 0,3 kW *ipotizzati* per simulazione:

| Limite EV richiesto | kWh teorici EV lato rete | Minuti di limitazione teorica |
|---|---:|---:|
| 3,8 kW | 5,74 | 23 |
| 3,0 kW | 4,69 | 23 |
| 1,8 kW | 3,05 | 0 |

Intervalli con dati mancanti: circa 0,4 min. Il replay assume che i valori
del sensore filtrato siano rappresentativi fino al campione successivo.
I carichi degli altri rami e la wallbox **non sono stati misurati nello
stesso intervallo**. Non scegliere una strategia produttiva da un solo
campione o da una stima dei picchi.

## Prossimi test prima di progettare il controllore

1. Confrontare misure contemporanee del ramo casa completo, ramo EV e
   telemetria DPM durante una ricarica e un ciclo elettrodomestico.
2. Estendere il replay con verifica della scadenza SOC e previsione
   conservativa delle ore successive, con dati realmente disponibili.
3. Confrontare riduzioni preventive, nessuna riduzione e interventi DPM;
   misurare il beneficio effettivo e la perdita di energia prima di
   decidere se usare sensori opzionali.
4. Collegare il modello alla dashboard della v0.1 SOLO in simulazione,
   gestendo riavvii, disponibilità sensori e qualità dati.

Il firmware ESPHome, il suo DPM 4,4 kW dell'impianto utente e la versione
Marketplace restano invariati.
