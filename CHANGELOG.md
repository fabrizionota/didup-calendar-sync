# Changelog

🇮🇹 [Italiano](#italiano) · 🇬🇧 [English](#english)

<a id="italiano"></a>

## 🇮🇹 Italiano

Le versioni sono date (`AAAA.MM.GG`): tag `vAAAA.MM.GG`, immagine `ghcr.io/fabrizionota/didup-calendar-sync:AAAA.MM.GG`.

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
