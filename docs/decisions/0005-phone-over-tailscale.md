# 0005. The phone reaches the app over Tailscale
Date: 2026-11-11 · Status: accepted

## Context
I open documents on my laptop and on my phone, and search is the main way into the vault. With only the Drive app on the phone there would be no search away from the Mac. The app cannot be public (ADR 0001). Reminders also have to reach an Android phone, so Apple Reminders is out, and sending email would need a stored mail credential.

## Decision
The app listens on the Mac only and is published to my own devices with `tailscale serve`, which gives it an HTTPS address on my private Tailscale network. On the phone it installs to the home screen as a web app. The app has its own sign-in on top (an Argon2 password hash, sessions that expire, a way to end a lost phone's session). Secrets ask for the master password on every reveal. Reminders come three ways: a Coming up list in the app, a push notification to the installed app while the Mac is awake, and an Add to Google Calendar link for renewals and expiries that fires from my calendar even when the Mac is off. The link carries a short title only, never a policy or card number. When the Mac is asleep or off, the PDFs in Drive are the fallback.

## Alternatives considered
- **The Drive app alone on the phone.** No search or reminders away from the Mac.
- **A public deployment.** Ruled out by ADR 0001.
- **Reminder emails through a Gmail app password.** Google marks app passwords as not recommended, and it adds another stored credential.

## Consequences
Search from the phone works only while the Mac is awake and on the network. Push notifications share that limit, which is why renewal reminders also go to the calendar. Losing the phone means removing it from Tailscale and ending its session.
