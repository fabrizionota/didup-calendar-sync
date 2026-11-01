# Changelog

🇮🇹 [Italiano](#italiano) · 🇬🇧 [English](#english)

<a id="italiano"></a>

## 🇮🇹 Italiano

Le versioni sono date (`AAAA.MM.GG`): tag `vAAAA.MM.GG`, immagine `ghcr.io/fabrizionota/didup-calendar-sync:AAAA.MM.GG`.

### 2026.11.01
**Novità**
- **Telegram a più chat:** `[[notifiche.telegram.destinatari]]` con filtri facoltativi `tipi` e
  `alunni`, come per Home Assistant (`chat_id` resta valido e riceve tutto). Le comunicazioni della
  bacheca arrivano con il **testo intero** (HTML ripulito); oltre il limite di Telegram sono divise in
  più messaggi (1/3, 2/3…). Home Assistant riceve sempre il riassunto.
- **Medie nei voti:** la notifica di un voto riporta la media della materia e la media generale
  (`📊 media matematica: 7,25 · media generale: 8,00`), dai dati di Argo (`mediaMaterie`,
  `mediaGenerale`) come nell'app, altrimenti dai voti numerici che fanno media; arrotondate al quarto.
- **Comunicazioni senza allegati in PDF** su Drive o Nextcloud, con il link nella notifica (alunno, data,
  autore, categoria, richieste, link, testo completo). `[allegati] comunicazioni_pdf` (default `true`);
  PDF generato con la sola libreria standard. Al primo avvio anche quelle già pubblicate.
- Monitoraggio: `[monitoraggio] kuma_push_url` e `porta` anche nel config (le variabili d'ambiente
  `KUMA_PUSH_URL` e `METRICS_PORT`, se non vuote, vincono).
- `PRIVACY.md` (informativa GDPR) e `TERMS.md` (termini di servizio), in italiano e inglese; nel README
  la sezione "Come funziona".
- PoC 07: verifica e prova anche su tutte le chat Telegram.
- CI Gitea: deploy automatico facoltativo dopo il push di `:edge` (secret `PORTAINER_WEBHOOK`).

**Affidabilità**
- Errori temporanei di Argo (HTTP 500/502/503/504, timeout, rete, login SSO interrotto a metà):
  ripetuti nello stesso giro, `[rete] tentativi` (3) con attesa crescente da `attesa_secondi` (30 s,
  poi 90 s); esauriti i tentativi, il resto del giro di quell'account non riprova.
- Login Argo rifiutato: un solo nuovo tentativo dopo 60 s; nel log gli avvisi della pagina SSO di Argo
  (mai le credenziali) e cosa controllare.
- Avviso di sync fallita solo dopo `[notifiche] dopo_fallimenti` giri falliti di fila (default 2); il
  ripristino si notifica solo se l'avviso era partito. `/healthz` e Kuma restano immediati.
- Log: gli errori noti stanno in una riga, senza traceback né pagine HTML (traceback con `-v`); quelli
  inattesi mantengono il traceback.
- Token Google scaduto o revocato: messaggio chiaro con i passi per rifare il login (e il promemoria
  sullo stato *Test* dell'app OAuth), notificato al primo giro.

**Correzioni**
- Login Argo di nuovo funzionante: dal 28/10 l'SSO di Argo mostra una pagina di conferma
  ("Autenticazione riuscita. Ti stiamo riportando all'applicazione…") che fa l'ultimo passaggio via
  JavaScript invece del redirect, e il login si fermava con `Catena OAuth interrotta (redirect 3)`.
  Il client legge il link `data-auth-app-redirect` della pagina e prosegue.
- Voti non notificati: la chiave usava solo `prgVoto`, che si ripete tra materie e giorni; ora è
  materia + giorno + progressivo. Al primo avvio i voti più vecchi di 10 giorni vengono memorizzati
  senza notifica, quelli recenti ricontrollati (uno già notificato può arrivare una seconda volta).
- Un destinatario ripetuto nel config riceve ogni notifica una volta sola, con un avviso all'avvio.
- Il token del bot Telegram non finisce più nel log quando un invio fallisce; id delle chat abbreviati.
- `HA_TOKEN` e `TELEGRAM_BOT_TOKEN` vuoti valgono come non impostati: si usa il valore del config.

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

### 2026.11.01
**New**
- **Telegram to several chats:** `[[notifiche.telegram.destinatari]]` with optional `tipi` and
  `alunni` filters, as for Home Assistant (`chat_id` still works and gets everything). Notice board
  messages arrive with their **full text** (HTML cleaned); over Telegram's limit they are split into
  several messages (1/3, 2/3…). Home Assistant still gets the summary.
- **Averages in grades:** a grade notification shows the subject average and the overall average
  (`📊 media matematica: 7,25 · media generale: 8,00`), from Argo's data (`mediaMaterie`,
  `mediaGenerale`) as in the app, otherwise from the numeric grades that count; rounded to a quarter.
- **Notices without attachments as PDF** on Drive or Nextcloud, with the link in the notification
  (pupil, date, author, category, requests, link, full text). `[allegati] comunicazioni_pdf` (default
  `true`); PDF generated with the standard library only. The first runs also cover published ones.
- Monitoring: `[monitoraggio] kuma_push_url` and `porta` in the config too (the `KUMA_PUSH_URL` and
  `METRICS_PORT` environment variables win when not empty).
- `PRIVACY.md` (GDPR privacy notice) and `TERMS.md` (terms of service), in Italian and English; a
  "How it works" section in the README.
- PoC 07: checks and tests every Telegram chat too.
- Gitea CI: optional automatic deploy after pushing `:edge` (`PORTAINER_WEBHOOK` secret).

**Reliability**
- Temporary Argo errors (HTTP 500/502/503/504, timeouts, network, SSO login broken off): retried within
  the same run, `[rete] tentativi` (3) with a growing wait from `attesa_secondi` (30 s, then 90 s);
  once exhausted, the rest of that account's run doesn't retry.
- Rejected Argo login: a single retry after 60 s; the log shows the alerts on Argo's SSO page (never
  the credentials) and what to check.
- Sync failed alert only after `[notifiche] dopo_fallimenti` failed runs in a row (default 2); the
  recovery is notified only if the alert went out. `/healthz` and Kuma stay immediate.
- Logs: known errors fit on one line, with no traceback or HTML page (traceback with `-v`);
  unexpected ones keep the traceback.
- Expired or revoked Google token: clear message with the steps to log in again (and a reminder about
  the OAuth app's *Testing* status), notified on the first run.

**Fixes**
- Argo login works again: since 28/10 Argo's SSO shows a confirmation page ("Autenticazione riuscita.
  Ti stiamo riportando all'applicazione…") that does the last step via JavaScript instead of a
  redirect, and the login stopped with `Catena OAuth interrotta (redirect 3)`. The client reads the
  page's `data-auth-app-redirect` link and goes on.
- Grades not notified: the key used only `prgVoto`, which repeats across subjects and days; it is now
  subject + day + sequence number. On the first run grades older than 10 days are stored without
  notification, recent ones re-checked (one already notified may arrive a second time).
- A recipient repeated in the config gets each notification only once, with a warning at startup.
- The Telegram bot token no longer ends up in the log when a send fails; chat ids are shortened.
- Empty `HA_TOKEN` and `TELEGRAM_BOT_TOKEN` count as unset: the config value is used.

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
