# CHISEL walkthrough

A screen-by-screen tour of the Android app, from installing it to reading a hidden message. All screenshots come from CHISEL 1.1.0 running on an Android 16 phone emulator. What changed since 1.0.0 is in the [changelog](../CHANGELOG.md).

> These screenshots were taken against a local test server. That's why step 3 shows a "Demo server" box and Settings shows `localhost:8000`. On the live server the code arrives **only by email**.

---

## 1. Open CHISEL

<img src="images/android/01-app-drawer.png" width="260" align="right" alt="CHISEL icon in the Android app drawer">

After installing the APK, CHISEL appears in the app drawer with its blue CHISEL icon. Tap it to open.

The first launch can take up to a minute if the server has been idle (it sleeps on the free hosting plan). After that it's quick.

<br clear="right">

---

## 2. Sign in with your email

<img src="images/android/02-sign-in.png" width="260" align="right" alt="Sign in to CHISEL">

Enter your email address and tap **Continue**. There's no password: CHISEL emails you a 6-digit code.

<br clear="right">

## 3. Enter the code

<img src="images/android/03-check-email.png" width="260" align="right" alt="Check your email">

Open the email from **CHISEL** (check *Spam* or *Promotions* if it isn't in your inbox), type the 6-digit code and tap **Continue**. Codes expire after 5 minutes; tap *Send a new code* if needed.

At this moment your phone creates your encryption keys. The private keys stay on the phone; only the public halves are sent to the server.

<br clear="right">

## 4. Choose your name

<img src="images/android/04-your-name.png" width="260" align="right" alt="What should people call you?">

New accounts pick the name other people will see, next to your email. You can change it later in **Settings**.

<br clear="right">

## 5. Allow notifications

<img src="images/android/05-allow-notifications.png" width="260" align="right" alt="Allow CHISEL to send you notifications?">

On Android 13 and newer, CHISEL asks once whether it may send notifications. Tap **Allow** to be told when a picture arrives. A notification only says who sent it, never what it says. You can turn them off later in **Settings**.

<br clear="right">

---

## 6. Your chats

<img src="images/android/06-chats-empty.png" width="260" align="right" alt="Empty chat list">

The **Chats** tab lists your conversations under the CHISEL title. The glass bar at the bottom switches between **Info**, **Chats** and **Settings**.

To start a conversation, tap the round **new chat** button at the bottom right.

<br clear="right">

## 7. Start a new chat

<img src="images/android/07-new-chat.png" width="260" align="right" alt="New chat">

Type the email address of someone who has already signed up to CHISEL and tap **Start chat**. CHISEL fetches their public key and checks it's genuinely theirs.

<br clear="right">

## 8. Write a message

<img src="images/android/08-compose.png" width="260" align="right" alt="Typing a message">

The chat shows their name and email at the top. Type your message (up to 2,000 characters) in the box at the bottom and tap the send button.

<br clear="right">

## 9. It's sent as a picture

<img src="images/android/09-sent.png" width="260" align="right" alt="Sent picture with timestamp">

Your phone encrypts the message, signs it, gets a fresh AI-painted picture from the server and hides the message inside it. Only the picture is uploaded. Sent pictures appear on the right, in blue, with the bubble's tail at the bottom-right corner, and the date and time.

<br clear="right">

---

## 10. A reply arrives

<img src="images/android/10-reply-arrives.png" width="260" align="right" alt="Received picture with Tap to read">

Pictures sent to you appear on the left, in grey, with the tail at the bottom-left corner, within about 15 seconds while the chat is open. New ones are marked **Tap to read**.

<br clear="right">

## 11. Tap to read

<img src="images/android/11-reveal.png" width="260" align="right" alt="Revealed message over a blurred chat">

Tap the picture. Your phone finds the hidden bits with your private key, checks the sender's signature and decrypts the message. Everything except the sender's name is blurred while it's shown. Tap outside the card, or press back, to close it.

If anyone altered even one dot of the picture, CHISEL refuses to open it.

<br clear="right">

## 12. Check their safety number

<img src="images/android/12-contact-safety-number.png" width="260" align="right" alt="Contact sheet with both safety numbers">

Tap the contact's name at the top of the chat to see **their safety number** next to **yours**. Ask them to open *Settings → Your safety number* on their phone: if the digits match on both phones, nobody is secretly in the middle.

<br clear="right">

---

## 13. Pull down to refresh

<img src="images/android/13-pull-to-refresh.png" width="260" align="right" alt="Pull to refresh the chat list">

The chat list checks for new pictures by itself every 15 seconds while it's open. To check right away, pull the list down until it says **Release to refresh**, then let go.

<br clear="right">

## 14. Notifications

<img src="images/android/14-notification.png" width="260" align="right" alt="Notification: Bob Martin sent you a picture">

When a picture arrives and CHISEL isn't on screen, you get a notification with the sender's name and a white chisel icon. It never shows the message: that stays locked in the picture until you tap it in the app. Tap the notification to open CHISEL.

While CHISEL is closed, Android lets it check about every 15 minutes, so a notification can take that long to appear.

<br clear="right">

## 15. Back to your chats

<img src="images/android/15-chats-list.png" width="260" align="right" alt="Chat list with an unread picture">

Conversations are listed newest first, with a badge for unread pictures. Everything vanishes **24 hours** after it was sent.

<br clear="right">

---

## 16. Settings: your account

<img src="images/android/16-settings-account.png" width="260" align="right" alt="Account settings and safety number">

**Settings** shows your name (tap *Change* to edit it), email, how old your daily key is, and **your safety number**.

<br clear="right">

## 17. Settings: appearance and notifications

<img src="images/android/17-settings-notifications.png" width="260" align="right" alt="Theme and notification settings">

Choose **System default**, **Light** or **Dark** under *Appearance*, and turn notifications on or off under *Notifications*.

<br clear="right">

## 18. Settings: privacy and account

<img src="images/android/18-settings-actions.png" width="260" align="right" alt="Privacy, chats and sign-out settings">

- **Verified contacts**: the safety numbers of people you've messaged.
- **Renew daily key now**: replaces your encryption key early. Unread pictures become unreadable.
- **Delete all chats**: removes pictures sent to you and everything stored for your chats on this phone.
- **Sign out**: your keys stay on the phone for next time.
- **Remove keys from this phone** and **Delete my account** (confirmed with an email code).

<br clear="right">

## 19. Dark mode

<img src="images/android/19-dark-mode.png" width="260" align="right" alt="Chat in dark mode">

The same chat in dark mode.

<br clear="right">

---

## Good to know

- **One phone per account.** Your keys live on the phone that created them. Signing in on a new phone (or after clearing CHISEL's data) creates new keys; your contacts will see that your safety number changed.
- **Messages are temporary.** Pictures disappear after 24 hours, and your phone renews its key daily, so old messages can never be decrypted again.
- **"Safety number changed" warning.** If a contact's keys change, CHISEL stops and shows the old and new numbers. Check with them before tapping *trust*.
- **Notifications are private.** They name the sender, never the message.
