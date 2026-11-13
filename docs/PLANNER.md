# Pianificatore: primo prototipo matematico, non ancora rilasciato

**Stato:** funzione pura in `planner.py`, disconnessa da HA e dagli attuatori. La versione installabile resta 0.0.7.

## Principio
Ogni casa può avere un contratto, un misuratore e abitudini differenti.
L'algoritmo non contiene riferimenti a Fiat/Kia, Shelly, induzione o lavastoviglie.

Gli ingressi del prototipo sono:
- kWh mancanti **nella batteria**, orario di partenza e ora attuale;
- kW contrattuali e **potenza continuativa disponibile** (distinti);
- consumo domestico di riferimento **esplicito** e prudente;
- limite di carica dell'auto e rendimento AC ipotizzato;
- margine temporale e possibile orario preferito.

La potenza EV stimata è `min(limite_veicolo, disponibile_continua - consumo_casa_riferimento)`, solo se positiva.
Da questa e dal rendimento si ricavano durata, ultimo inizio prudenziale e verifica della compatibilità con l'orario preferito.

Le tolleranze temporanee del contatore NON sono disponibili continuativi; non si pianifica a 5,2 kW su un contratto da 4 kW.
Il DPM rimane attivo e intoccato. Non è aggiunto un secondo controllore di picchi.

## Due prove indicative, non misure dell'impianto

Arrivo 18:00, partenza 08:00, 4 kW contrattuali, 4,4 kW continui, consumo casa di riferimento IPOTETICO 0,6 kW, efficienza IPOTETICA 90%, margine 45 minuti:
- Fiat 30→80%: circa 18,65 kWh nella batteria. L'avvio alle 01:00 potrebbe essere compatibile.
- Kia EV3 Long Range 30→80%: circa 39 kWh nella batteria. Aspettare le 01:00 è troppo tardi: il prototipo consiglia di partire prima.

Lo stato `feasible_estimate` significa **compatibile solo con le ipotesi**, NON una garanzia del raggiungimento del SOC.
Se un dato necessario manca o è incoerente, ritorna `insufficient_data`; se la scadenza è critica, `deadline_at_risk`.

## Prima di collegarlo a Home Assistant
- Decidere GUI per partenza, potenza disponibile e riferimento domestico, inclusi i casi senza sensori.
- Verificare il limite DPM reale e la potenza media effettiva, non quella nominale.
- Usare valori filtrati/stabili per la previsione, senza inseguire picchi.
- Progettare fasce preferite per feriali/weekend; l'orario preferito del prototipo è solo un istante.
- Simulare cambiamenti durante la sessione e l'isteresi delle eventuali variazioni di potenza.
- Dashboard Lovelace nella milestone v0.1, sempre solo simulazione.

**Non implementati:** comandi BLE, pausa ricarica, regolazione potenza, sensori elettrodomestici, lettura reale energia e dashboard.
