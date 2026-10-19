# Changelog

🇮🇹 [Italiano](#italiano) · 🇬🇧 [English](#english)

<a id="italiano"></a>

## 🇮🇹 Italiano

Le versioni sono date (`AAAA.MM.GG`): tag `vAAAA.MM.GG`, immagine `ghcr.io/fabrizionota/didup-calendar-sync:AAAA.MM.GG`.

### 2026.10.15
- Errori temporanei di Argo (HTTP 500/502/503/504, timeout, rete): la richiesta viene ripetuta nello
  stesso giro, `[rete] tentativi` (3) con attesa crescente da `attesa_secondi` (30 s, poi 90 s).
  Esauriti i tentativi, il resto del giro di quell'account non riprova.
- Avviso di sync fallita solo dopo `[notifiche] dopo_fallimenti` giri falliti di fila (default 2);
  il ripristino si notifica solo se l'avviso era partito. `/healthz` e Kuma restano immediati.
- Log: gli errori noti di Argo stanno in una riga (`HTTP 500 su login`), senza traceback né pagina
  HTML; la notifica di errore riporta la stessa descrizione.
- Token Google scaduto o revocato: messaggio chiaro con i passi per rifare il login (e il
  promemoria sullo stato *Test* dell'app OAuth), senza traceback, notificato al primo giro.
- `PRIVACY.md` (informativa GDPR) e `TERMS.md` (termini di servizio), in italiano e inglese.
- Telegram a più chat: `[[notifiche.telegram.destinatari]]` con filtri facoltativi `tipi` e `alunni`,
  come per Home Assistant; `chat_id` resta valido e riceve tutto. Messaggi oltre 4000 caratteri troncati.
- Sicurezza: il token del bot Telegram non finisce più nel log quando un invio fallisce; id delle chat
  abbreviati in log e metriche.
- `HA_TOKEN` e `TELEGRAM_BOT_TOKEN` vuoti valgono come non impostati: si usa il valore del config
  (prima una variabile vuota nello stack lo cancellava). Errore chiaro se manca il token del bot.
- PoC 07: verifica e prova su tutte le chat Telegram (getChat).
- Monitoraggio: `[monitoraggio] kuma_push_url` e `porta` anche nel config, per chi non può aggiungere
  variabili al container (`KUMA_PUSH_URL` e `METRICS_PORT`, se non vuote, vincono).

### 2026.10.14
- Monitoraggio: endpoint `/metrics` per Prometheus (giri, durata, eventi, notifiche, allegati,
  elementi visti per tipo, versione dell'app Argo) e `/healthz` (200/503), attivi con `METRICS_PORT`
  (9105 nel compose, pubblicata solo su localhost: `METRICS_BIND`). Solo libreria standard.
- Uptime Kuma: push a fine giro (`up` con durata, `down` con l'errore) con `KUMA_PUSH_URL`.
- `deploy/compose.monitoraggio.yml`: reti Docker di Prometheus e Kuma configurabili
  (`PROMETHEUS_NETWORK`, `KUMA_NETWORK`).
- Regole Prometheus d'esempio nel README, compreso il controllo di plausibilità sulle lezioni.

### 2026.10.13.1
- Notifiche Home Assistant a più telefoni: `[[notifiche.homeassistant.destinatari]]`, ognuno con
  filtri facoltativi `tipi` e `alunni`; `service` resta valido e riceve tutto.
- Ogni notifica inviata viene scritta nel log (tipo, destinatari, titolo).
- PoC 07: verifica e prova su tutti i destinatari.

### 2026.10.13 — prima versione pubblica
- Più alunni, più scuole e account Argo, senza account principale; impostazioni globali
  sovrascrivibili per alunno.
- Orario scolastico su Google Calendar (un calendario per alunno), con fasce orarie configurabili,
  ore consecutive unite, compresenze, materie ignorate e titoli con l'abbreviazione Argo.
- Compiti nella descrizione della lezione del giorno di consegna, o evento giornaliero 📚.
- Promemoria/verifiche e scadenze di adesione della bacheca come eventi.
- Notifiche Home Assistant e/o Telegram per voti, bacheca, note, promemoria (assenze e compiti
  facoltativi), con link all'allegato.
- Allegati della bacheca su Google Drive o Nextcloud (link interno o pubblico con scadenza),
  cartelle e nomi file configurabili, senza mai segnare la presa visione.
- Immagine multi-arch (amd64, arm64) su GHCR, compose con healthcheck e hardening, PoC per
  verificare ogni integrazione.

---

<a id="english"></a>

## 🇬🇧 English

Versions are dates (`YYYY.MM.DD`): tag `vYYYY.MM.DD`, image `ghcr.io/fabrizionota/didup-calendar-sync:YYYY.MM.DD`.

### 2026.10.15
- Temporary Argo errors (HTTP 500/502/503/504, timeouts, network): the request is retried within the
  same run, `[rete] tentativi` (3) with a growing wait from `attesa_secondi` (30 s, then 90 s).
  Once retries are exhausted, the rest of that account's run doesn't retry.
- Sync failed alert only after `[notifiche] dopo_fallimenti` failed runs in a row (default 2); the
  recovery is notified only if the alert went out. `/healthz` and Kuma stay immediate.
- Logs: known Argo errors fit on one line (`HTTP 500 su login`), with no traceback or HTML page;
  the error notification carries the same description.
- Expired or revoked Google token: clear message with the steps to log in again (and a reminder
  about the OAuth app's *Testing* status), no traceback, notified on the first run.
- `PRIVACY.md` (GDPR privacy notice) and `TERMS.md` (terms of service), in Italian and English.
- Telegram to several chats: `[[notifiche.telegram.destinatari]]` with optional `tipi` and `alunni`
  filters, as for Home Assistant; `chat_id` still works and receives everything. Messages over 4000
  characters are truncated.
- Security: the Telegram bot token no longer ends up in the log when a send fails; chat ids are
  shortened in log and metrics.
- Empty `HA_TOKEN` and `TELEGRAM_BOT_TOKEN` count as unset: the config value is used (an empty
  variable in the stack used to wipe it). Clear error if the bot token is missing.
- PoC 07: checks and tests every Telegram chat (getChat).
- Monitoring: `[monitoraggio] kuma_push_url` and `porta` also in the config, for those who can't add
  variables to the container (`KUMA_PUSH_URL` and `METRICS_PORT`, when not empty, win).

### 2026.10.14
- Monitoring: `/metrics` endpoint for Prometheus (runs, duration, events, notifications,
  attachments, items seen per type, Argo app version) and `/healthz` (200/503), enabled by
  `METRICS_PORT` (9105 in the compose, published on localhost only: `METRICS_BIND`). Standard
  library only.
- Uptime Kuma: push after each run (`up` with duration, `down` with the error) via `KUMA_PUSH_URL`.
- `deploy/compose.monitoraggio.yml`: configurable Prometheus and Kuma Docker networks
  (`PROMETHEUS_NETWORK`, `KUMA_NETWORK`).
- Example Prometheus rules in the README, including the plausibility check on lessons.

### 2026.10.13.1
- Home Assistant notifications to several phones: `[[notifiche.homeassistant.destinatari]]`, each
  with optional `tipi` and `alunni` filters; `service` still works and receives everything.
- Every notification sent is logged (type, recipients, title).
- PoC 07: checks and tests every recipient.

### 2026.10.13 — first public release
- Several pupils, schools and Argo accounts, no main account; global settings overridable per pupil.
- School timetable on Google Calendar (one calendar per pupil), with configurable time slots,
  consecutive hours merged, co-teaching, ignored subjects and titles with the Argo abbreviation.
- Homework in the description of the lesson on the due day, or an all-day 📚 event.
- Reminders/tests and notice board sign-up deadlines as events.
- Home Assistant and/or Telegram notifications for grades, notice board, notes, reminders (absences
  and homework optional), with a link to the attachment.
- Notice board attachments on Google Drive or Nextcloud (internal or expiring public link),
  configurable folders and file names, never marking notices as read.
- Multi-arch image (amd64, arm64) on GHCR, compose with healthcheck and hardening, PoCs to check
  every integration.
