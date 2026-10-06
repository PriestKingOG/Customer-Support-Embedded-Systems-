# TrueView CCTV IVR (inbound)

`trueview_ivr.py` turns the Raspberry Pi 4B + SIM800L into a support line that answers calls from any number.

## Call flow

```
Incoming call -> answer -> Language: 1 English  2 Hindi  3 Marathi
Main menu
  1 Cameras   -> 1 4K camera   2 FHD 1080p camera              4 Executive  9 Repeat  0 Back
  2 Prices    -> 1 4K price    2 FHD price   3 Installation    4 Executive  9 Repeat  0 Back
  3 Storage   -> 1 HDD sizes & prices   2 Recording days per size   4 Executive  9 Repeat  0 Back
  4 Talk to a support executive -> caller hears confirmation, call ends,
                                   executive gets an SMS with the caller's number
  5 Book a site visit -> 1 4K camera   2 FHD 1080p camera   9 Repeat  0 Back
                         caller hears a confirmation and returns to the main menu
  9 Repeat   0 Change language
```

## SMS after every call

| Who | When | Example |
|---|---|---|
| Owner (`OWNER_NUMBER`) | Every call, including hidden numbers and hang-ups | `TrueView IVR 06-Oct 19:53: +919876543210 (Hindi) 95s, completed. Booking: TV2610061953210 4K camera site visit. Callback: YES. Heard: 4K price` |
| Caller | Every call where their number is visible | `Thanks for calling TrueView CCTV. Site visit booked for 4K camera, ref TV2610061953210. We will call to fix the date. An executive will call you back soon.` |
| Executive (`EXECUTIVE_NUMBER`) | Only on a callback request, and only if it differs from the owner's number | `TrueView IVR: callback request from +919876543210 (Hindi) at 06-Oct 19:53. Booking: none. Heard: 4K price` |

Callers who didn't book or ask for a callback get a thank-you with the owner's number. SMS are in English (Hindi/Marathi script would need Unicode SMS mode) and are cut at 160 characters. Bookings are also saved to `bookings.csv`. A caller with a hidden number can't book; they hear `exec_no_caller_id.wav` instead.

Callers can press a key while a prompt is still playing. No key for 8 s (or a wrong key) replays the menu; after 3 tries the IVR says goodbye and hangs up. Every call is logged to `call_log.csv`.

## Who can call

Anyone who dials the SIM's phone number reaches the IVR. There is no whitelist, and hidden numbers are answered too (they just can't get an SMS or book). At startup the script:

- checks the SIM is unlocked (`AT+CPIN?`) and waits for network registration (`AT+CREG?`), and stops with a clear message if either fails. If it says the SIM needs a PIN, put the SIM in a phone and turn off its PIN lock.
- cancels any call forwarding on the SIM (`AT+CCFC=4,0`) so callers aren't diverted elsewhere.
- turns off call waiting (`AT+CCWA=0,0`). The SIM800L handles one call at a time, so a second caller hears busy and can call again, instead of ringing with no answer.

It re-checks network registration every 5 minutes when idle and reconnects if it was lost. Keep the SIM recharged/active (incoming calls are free on most Indian plans, but SMS summaries cost money).

## Config to edit (top of `trueview_ivr.py`)

| Setting | What to put |
|---|---|
| `OWNER_NUMBER` | Business owner's mobile, e.g. `+919876543210` (**must fill in**). Gets every call summary; also shown to callers in their SMS |
| `EXECUTIVE_NUMBER` | Support executive's mobile (**must fill in**). Can be the same as the owner's |
| `SERIAL_PORT` | `/dev/ttyUSB0` (USB-TTL adapter) or `/dev/serial0` (Pi GPIO UART) |
| `SEND_CALLER_SUMMARY_SMS`, `SEND_OWNER_SUMMARY_SMS` | Set to `False` to stop that SMS. Numbers left as `+91XXXXXXXXXX` are skipped |
| `DIGIT_TIMEOUT`, `MAX_ATTEMPTS`, `MAX_CALL_SECONDS` | Timing, defaults are fine |

Menus live in the `MENUS` dict, so you can add an option (e.g. a 2K camera) by adding a line there and recording its WAV.

## Audio files to record

Format: **WAV, 8000 Hz, mono, 16-bit**. Convert with
`ffmpeg -i input.mp3 -ar 8000 -ac 1 -sample_fmt s16 output.wav`.
The script logs any missing file at startup.

`audio/common/` (recorded once, in all three languages back to back)

| File | Suggested script |
|---|---|
| `language_select.wav` | "Welcome to TrueView CCTV. For English press 1. हिंदी के लिए 2 दबाएं. मराठीसाठी 3 दाबा." |
| `invalid.wav` | "Invalid choice" in all three languages |
| `goodbye.wav` | "Thank you for calling TrueView" in all three languages |

`audio/en/`, `audio/hi/`, `audio/mr/` (same 17 file names in each folder, 51 files total)

Prices and storage sizes below are **placeholders**: replace every `[____]` with your real figures when recording.

| File | Suggested script (English) |
|---|---|
| `main_menu.wav` | "For camera information press 1. For prices press 2. For storage options press 3. To talk to our support executive press 4. To book a free site visit press 5. To repeat press 9. To change language press 0." |
| `cameras_menu.wav` | "For our 4K Ultra HD camera press 1. For our Full HD 1080p camera press 2. For an executive press 4. To repeat press 9. To go back press 0." |
| `camera_4k.wav` | Features of the TrueView 4K camera (resolution, night vision, indoor/outdoor, warranty [____]) |
| `camera_fhd.wav` | Features of the TrueView FHD 1080p camera (same points) |
| `prices_menu.wav` | "For 4K camera prices press 1. For Full HD prices press 2. For installation charges press 3. For an executive press 4. To repeat press 9. To go back press 0." |
| `price_4k.wav` | "The 4K camera costs ₹[____] per camera. A 4-camera 4K kit costs ₹[____]." |
| `price_fhd.wav` | "The Full HD 1080p camera costs ₹[____] per camera. A 4-camera kit costs ₹[____]." |
| `price_installation.wav` | "Installation costs ₹[____] per camera, wiring ₹[____] per metre." |
| `storage_menu.wav` | "For hard disk options and prices press 1. To hear how many days of recording each size stores press 2. For an executive press 4. To repeat press 9. To go back press 0." |
| `storage_options.wav` | "We offer [500 GB] for ₹[____], [1 TB] for ₹[____], [2 TB] for ₹[____] and [4 TB] for ₹[____]." |
| `storage_days.wav` | "With 4 cameras, 1 TB stores about [__] days of 4K or [__] days of Full HD recording..." |
| `booking_menu.wav` | "To book a site visit for 4K cameras press 1. For Full HD 1080p cameras press 2. To repeat press 9. To go back press 0." |
| `booking_confirmed.wav` | "Your site visit is booked. You will receive an SMS with your booking reference, and our team will call you to fix the date. Returning to the main menu." |
| `exec_request.wav` | "Thank you. Our support executive will call you back shortly on this number. Goodbye." |
| `exec_no_caller_id.wav` | "Your number is hidden, so we can't call you back or confirm a booking. Please call our executive directly on [number]. Goodbye." |
| `invalid.wav` | "Sorry, that is not a valid choice." |
| `goodbye.wav` | "Thank you for calling TrueView. Goodbye." |

## Install and run

```
sudo apt install python3-serial python3-pygame
python3 trueview_ivr.py
```

To start it at boot, add a systemd service with `ExecStart=/usr/bin/python3 /home/pi/ivr/trueview_ivr.py` and `Restart=always`.

## Hardware notes

- Pi headphone jack goes to SIM800L `MIC+`/`MIC-` through a 1 to 10 µF capacitor; if callers hear distortion, lower the Pi volume (`alsamixer`).
- SIM800L needs its own 3.7 to 4.2 V supply that can deliver 2 A bursts. Powering it from the Pi's 5 V or 3.3 V pin causes resets mid-call.
- If `SERIAL_PORT` is the GPIO UART, enable it with `raspi-config` (Serial: login shell No, hardware Yes).

## What changed from the original script

- Answers incoming calls (`ATA`) instead of dialling out; never auto-answers (`ATS0=0`).
- Reads the caller's number from `+CLIP` instead of slicing a fixed string position.
- Detects hang-up via `NO CARRIER` / `+CLCC` disconnect status, so the IVR stops instead of waiting on a dead call.
- Echo turned off (`ATE0`) and replies parsed up to `OK`/`ERROR`, so commands no longer depend on 1 s sleeps.
- Fixed `AT+CNMI =0,...` (stray space) and SMS now waits for the `>` prompt and the send confirmation.
- Serial errors reconnect automatically instead of crashing the loop.
