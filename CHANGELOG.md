# Changelog

All notable changes to CHISEL. Versions follow [Semantic Versioning](https://semver.org/): the Android app's `versionName` and the web app's `APP_VERSION` share one number.

## [1.1.0] — 2026-11-22

Compatible with 1.0.0: the message format, hidden-bit layout and API are unchanged, so 1.0.0 and 1.1.0 apps can message each other. The APK is signed with the same key and installs over 1.0.0, keeping keys and chats. Needs a new APK for the interface changes; the server and web app update when this is deployed.

### Server
- **More varied cover pictures.** Prompts are drawn from **100 subjects** × **10 styles** (was 15 × 5) with a random seed, so a chat rarely shows similar pictures. Covers already in the buffer are used up first. (`server/pool.py`)

### App (Android and web)
- **Pull down to refresh** the chats list; the refresh button in the top-right corner is gone.
- **New-chat button** is a round glass circle like the tab bar, with no drop shadow.
- **Send button** has no drop shadow.
- **No yellow highlight** around text fields while typing (message box, search, sign-in fields).
- **Safety number on the contact's profile:** tap the name at the top of a chat to see their safety number next to yours and compare them in person.
- **New-message notifications** naming the sender (never the message). Android: while open, and about every 15 minutes while closed (Background Runner); browsers: while the tab is in the background. On/off in Settings → Notifications. Tapping a notification opens that chat.
- **New app icon and title:** the CHISEL artwork is the launcher icon, web icon, favicon and splash screen; the CHISEL wordmark replaces the plain "Chisel" title on the chats and sign-in screens. New white chisel status-bar icon for notifications.
- **"CHISEL" everywhere in the app** (app name, screens, messages), since it is an abbreviation.
- **Speech-bubble tails** at the outer corners: bottom-left for pictures you receive, bottom-right for yours.
- **Rounded search bar**, matching the tab bar.
- Web app cache bumped (`chisel-app-v5`) so browsers fetch the new version.

### Android
- Version 1.1.0 (version code 2).
- Adds the notification permission (Android 13+ asks once). Removes the location and exact-alarm permissions the plugins would otherwise add.
- APK grows from about 4 MB to about 10 MB (the background runner's JavaScript engine).

### Docs
- README, walkthrough (now 19 steps) and screenshots retaken on the Android 16 emulator for 1.1.0.

### Tests
- Android 16 emulator: in-place upgrade from 1.0.0, notification permission prompt, background-runner notification ("Bob Martin — Sent you 3 pictures") and tapping it opens CHISEL, pull to refresh, contact safety number matches the sender's own.
- `test_audit.py` expects the CHISEL title and checks the new files are served (79/79 pass).

## [1.0.0] — 2026-11-22

First release: end-to-end encrypted messages (X25519, HKDF-SHA256, AES-256-GCM, Ed25519) hidden at keyed, scattered pixel positions in AI-generated 512×512 PNG covers; FastAPI server on Render with Neon Postgres, Brevo email codes and a server-side cover buffer of 5; Android APK (Capacitor) and web app; 24-hour expiry and daily key rotation.

[1.1.0]: https://github.com/DivyanshKVerma/chisel-msg/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/DivyanshKVerma/chisel-msg/releases/tag/v1.0.0
