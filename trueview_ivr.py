#!/usr/bin/env python3
"""
TrueView CCTV - inbound IVR customer support line.

Hardware: Raspberry Pi 4B + SIM800L GSM module.
  - SIM800L TXD/RXD -> Pi (USB-TTL adapter or GPIO UART)
  - Pi audio out    -> SIM800L MIC+/MIC- (prompts are played into the call)

Flow for every incoming call (from any number):
  1. Answer, read the caller's number from +CLIP.
  2. Language menu: 1 English, 2 Hindi, 3 Marathi.
  3. Main menu: 1 Cameras, 2 Prices, 3 Storage, 4 Talk to an executive,
                5 Book a site visit, 9 Repeat, 0 Change language.
  4. "Talk to an executive" -> caller hears a confirmation, call ends, and the
     executive gets an SMS with the caller's number so they can call back.
  5. "Book a site visit" -> caller picks 4K or FHD, gets a booking reference.
  After every call, the caller and the owner get an SMS summary of the call
  and any booking.

Prompts are pre-recorded WAV files (8 kHz, mono, 16-bit) in audio/<lang>/.
See README.md for the full list of files to record.
"""
import csv
import datetime
import logging
import os
import re
import time
from collections import deque

import pygame  # to play prompts
import serial  # for serial communication with GSM SIM800L

# _____________________________________________________________________________
# CONFIG - edit these for your setup
# _____________________________________________________________________________

# "/dev/ttyUSB0" for a USB-TTL adapter, "/dev/serial0" if wired to Pi GPIO14/15
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE = 9600

# Business owner's mobile number (gets an SMS summary of every call and booking)
OWNER_NUMBER = "+91XXXXXXXXXX"      # <-- OWNER: fill in

# Support executive's mobile number (gets an SMS for every callback request).
# If it is the same as OWNER_NUMBER, the owner's summary covers it.
EXECUTIVE_NUMBER = "+91XXXXXXXXXX"  # <-- OWNER: fill in

# After every call, send an SMS summary of the call and any booking
SEND_CALLER_SUMMARY_SMS = True
SEND_OWNER_SUMMARY_SMS = True

BUSINESS_NAME = "TrueView"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
CALL_LOG = os.path.join(BASE_DIR, "call_log.csv")
BOOKINGS_LOG = os.path.join(BASE_DIR, "bookings.csv")

DIGIT_TIMEOUT = 8        # seconds to wait for a key press after a prompt ends
MAX_ATTEMPTS = 3         # no-input / invalid-input retries before hanging up
MAX_CALL_SECONDS = 600   # hard limit on one call
IDLE_HEALTH_CHECK = 300  # seconds of silence before checking the modem is alive

LANGUAGES = {"1": "en", "2": "hi", "3": "mr"}
LANGUAGE_NAMES = {"en": "English", "hi": "Hindi", "mr": "Marathi"}

# Menu tree. Each option is (action, argument):
#   ("menu", name)   go to a sub-menu
#   ("play", file)   play an information prompt, then repeat the current menu
#   ("executive", _) callback request to the support executive
#   ("book", what)   book a site visit / installation for that camera type
#   ("back", _)      previous menu
#   ("repeat", _)    play the current menu again
#   ("language", _)  back to language selection
MENUS = {
    "main": {
        "prompt": "main_menu",
        "options": {
            "1": ("menu", "cameras"),
            "2": ("menu", "prices"),
            "3": ("menu", "storage"),
            "4": ("executive", None),
            "5": ("menu", "booking"),
            "9": ("repeat", None),
            "0": ("language", None),
        },
    },
    "booking": {
        "prompt": "booking_menu",
        "options": {
            "1": ("book", "4K camera"),
            "2": ("book", "FHD 1080p camera"),
            "9": ("repeat", None),
            "0": ("back", None),
        },
    },
    "cameras": {
        "prompt": "cameras_menu",
        "options": {
            "1": ("play", "camera_4k"),
            "2": ("play", "camera_fhd"),
            "4": ("executive", None),
            "9": ("repeat", None),
            "0": ("back", None),
        },
    },
    "prices": {
        "prompt": "prices_menu",
        "options": {
            "1": ("play", "price_4k"),
            "2": ("play", "price_fhd"),
            "3": ("play", "price_installation"),
            "4": ("executive", None),
            "9": ("repeat", None),
            "0": ("back", None),
        },
    },
    "storage": {
        "prompt": "storage_menu",
        "options": {
            "1": ("play", "storage_options"),
            "2": ("play", "storage_days"),
            "4": ("executive", None),
            "9": ("repeat", None),
            "0": ("back", None),
        },
    },
}

COMMON_PROMPTS = ["language_select", "invalid", "goodbye"]
LANGUAGE_PROMPTS = [
    "main_menu",
    "cameras_menu", "camera_4k", "camera_fhd",
    "prices_menu", "price_4k", "price_fhd", "price_installation",
    "storage_menu", "storage_options", "storage_days",
    "booking_menu", "booking_confirmed",
    "exec_request", "exec_no_caller_id",
    "invalid", "goodbye",
]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("ivr")

# Lines the modem sends on its own (not as a reply to a command)
URC_PREFIXES = ("RING", "+CLIP", "+DTMF", "NO CARRIER", "BUSY", "NO ANSWER",
                "+CLCC", "+CMTI", "Call Ready", "SMS Ready", "UNDER-VOLTAGE",
                "OVER-VOLTAGE")
FINAL_RESULTS = ("OK", "ERROR", "+CME ERROR", "+CMS ERROR")

CLIP_RE = re.compile(r'\+CLIP:\s*"([^"]*)"')
DTMF_RE = re.compile(r'\+DTMF:\s*([0-9*#A-D])')
CLCC_RE = re.compile(r'\+CLCC:\s*\d+,\d+,(\d+)')
CLCC_NUMBER_RE = re.compile(r'\+CLCC:\s*\d+,\d+,\d+,\d+,\d+,"([^"]*)"')
CREG_RE = re.compile(r'\+CREG:\s*\d+,(\d+)')


class CallEnded(Exception):
    """The caller hung up (or the call hit its time limit)."""


class NoInput(Exception):
    """The caller didn't press a valid key after several attempts."""


# _____________________________________________________________________________
# SIM800L
# _____________________________________________________________________________
class Modem:
    def __init__(self, port, baud):
        self.ser = serial.Serial(port, baudrate=baud, timeout=0.1)
        self.buf = b""
        self.urc = deque()  # unsolicited lines seen while waiting for a command reply
        log.info("Established communication with %s", self.ser.name)

    def close(self):
        self.ser.close()

    def write(self, data):
        self.ser.write(data if isinstance(data, bytes) else data.encode("ascii"))

    def _readline(self, timeout):
        """Next non-empty line from the modem, or None on timeout."""
        deadline = time.monotonic() + timeout
        while True:
            if b"\n" in self.buf:
                raw, self.buf = self.buf.split(b"\n", 1)
                line = raw.decode("ascii", "ignore").strip()
                if line:
                    return line
                continue
            if time.monotonic() >= deadline:
                return None
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if chunk:
                self.buf += chunk

    def next_event(self, timeout):
        """Next unsolicited line (RING, +CLIP, +DTMF, NO CARRIER...), or None."""
        if self.urc:
            return self.urc.popleft()
        return self._readline(timeout)

    def wait_final(self, timeout, finals=FINAL_RESULTS):
        """Collect reply lines until a final result. Returns (final, lines)."""
        lines = []
        deadline = time.monotonic() + timeout
        while True:
            line = self._readline(max(0.0, deadline - time.monotonic()))
            if line is None:
                return None, lines
            if line.startswith(finals):
                return line, lines
            if line.startswith(URC_PREFIXES):
                self.urc.append(line)
            else:
                lines.append(line)

    def command(self, cmd, timeout=2, finals=FINAL_RESULTS):
        """Send an AT command. Returns (ok, final, lines)."""
        self.write(cmd + "\r")
        final, lines = self.wait_final(timeout, finals)
        return final == "OK", final, lines

    def wait_for_prompt(self, char, timeout):
        """Wait for a prompt char that isn't followed by a newline (SMS '>')."""
        deadline = time.monotonic() + timeout
        while char not in self.buf:
            if time.monotonic() >= deadline:
                return False
            chunk = self.ser.read(self.ser.in_waiting or 1)
            if chunk:
                self.buf += chunk
        self.buf = self.buf.split(char, 1)[1]
        return True

    def send_sms(self, number, text):
        text = text[:160]
        self.command("AT+CMGF=1")
        self.write('AT+CMGS="%s"\r' % number)
        if not self.wait_for_prompt(b">", 5):
            self.write(b"\x1b")  # ESC aborts the SMS
            log.error("SMS to %s failed: no '>' prompt", number)
            return False
        self.write(text.encode("ascii", "replace") + bytes([26]))  # Ctrl+Z sends
        final, _ = self.wait_final(60)
        if final == "OK":
            log.info("SMS sent to %s", number)
            return True
        log.error("SMS to %s failed: %s", number, final)
        return False


def init_modem(modem):
    """Checks SIM800L status and configures it for incoming calls."""
    for _ in range(10):
        if modem.command("AT")[0]:
            break
        time.sleep(1)
    else:
        raise serial.SerialException("SIM800 Module not responding")

    setup = [
        ("ATE0", 2),               # no command echo
        ("ATS0=0", 2),             # never auto-answer, the Pi answers with ATA
        ("AT+CLIP=1", 2),          # caller number on incoming calls
        ("AT+CLCC=1", 2),          # call status reports (catches hang-ups)
        ("AT+DDET=1", 2),          # DTMF key press detection
        ("AT+CMGF=1", 2),          # SMS text mode
        ("AT+CSMP=17,167,0,0", 2),
        ("AT+CNMI=0,0,0,0,0", 2),  # don't push incoming SMS to the serial port
    ]
    for cmd, timeout in setup:
        ok, final, _ = modem.command(cmd, timeout)
        if not ok:
            log.warning("%s -> %s", cmd, final)

    # Calls only reach the IVR if the SIM is unlocked and registered on the network
    ok, _, lines = modem.command("AT+CPIN?", 5)
    if "READY" not in " ".join(lines):
        raise serial.SerialException("SIM not ready (%s). Remove the SIM PIN using a phone"
                                     % " ".join(lines))
    deadline = time.monotonic() + 60
    while not is_registered(modem):
        if time.monotonic() > deadline:
            raise serial.SerialException("SIM not registered on the network")
        log.info("Waiting for network registration...")
        time.sleep(3)

    # Make sure the network doesn't divert or queue callers away from the IVR
    for cmd in ("AT+CCFC=4,0",   # cancel any call forwarding on the SIM
                "AT+CCWA=0,0"):  # no call waiting: a 2nd caller hears busy, not endless ringing
        ok, final, _ = modem.command(cmd, 15)
        if not ok:
            log.warning("%s -> %s", cmd, final)
    log.info("SIM800 Module -> Active and Ready, answering calls from any number")


def is_registered(modem):
    ok, _, lines = modem.command("AT+CREG?")
    m = CREG_RE.search(" ".join(lines))
    return bool(m) and m.group(1) in ("1", "5")  # 1 = home network, 5 = roaming


# _____________________________________________________________________________
# Audio
# _____________________________________________________________________________
def prompt_path(lang, name):
    return os.path.join(AUDIO_DIR, lang or "common", name + ".wav")


def check_audio_files():
    missing = [prompt_path(None, n) for n in COMMON_PROMPTS]
    missing += [prompt_path(l, n) for l in LANGUAGES.values() for n in LANGUAGE_PROMPTS]
    missing = [p for p in missing if not os.path.isfile(p)]
    for p in missing:
        log.warning("Missing audio file: %s", p)
    return missing


class Player:
    def __init__(self):
        # 8 kHz mono audio works best on SIM800L
        pygame.mixer.pre_init(frequency=8000, size=-16, channels=1)
        pygame.mixer.init()

    def play(self, path):
        if not os.path.isfile(path):
            log.warning("Cannot play missing file %s", path)
            return False
        pygame.mixer.music.load(path)
        pygame.mixer.music.play()
        return True

    def busy(self):
        return pygame.mixer.music.get_busy()

    def stop(self):
        pygame.mixer.music.stop()


# _____________________________________________________________________________
# One answered call
# _____________________________________________________________________________
class Call:
    def __init__(self, modem, player, caller):
        self.modem = modem
        self.player = player
        self.caller = caller
        self.lang = None
        self.path = []
        self.executive_requested = False
        self.heard = []       # information prompts the caller listened to
        self.booking = None   # (booking id, camera type)
        self.started = time.monotonic()

    def _event(self, timeout):
        """Next key press (or None). Raises CallEnded when the caller hangs up."""
        if time.monotonic() - self.started > MAX_CALL_SECONDS:
            raise CallEnded("time limit")
        line = self.modem.next_event(timeout)
        if line is None:
            return None
        if line.startswith(("NO CARRIER", "BUSY", "NO ANSWER")):
            raise CallEnded(line)
        m = CLCC_RE.match(line)
        if m and m.group(1) == "6":  # call status 6 = disconnected
            raise CallEnded(line)
        m = DTMF_RE.match(line)
        if m:
            log.info("Key pressed: %s", m.group(1))
            return m.group(1)
        return None

    def play(self, name, interruptible=True):
        """Play a prompt. Returns the key pressed during it (barge-in), else None."""
        if not self.player.play(prompt_path(self.lang, name)):
            return None
        try:
            while self.player.busy():
                digit = self._event(0.1)
                if digit and interruptible:
                    return digit
        finally:
            self.player.stop()
        return None

    def wait_digit(self, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            digit = self._event(min(0.5, max(0.0, deadline - time.monotonic())))
            if digit:
                return digit
        return None

    def ask(self, prompt, valid):
        """Play a menu prompt and return a valid key, retrying on silence/invalid keys."""
        for _ in range(MAX_ATTEMPTS):
            digit = self.play(prompt) or self.wait_digit(DIGIT_TIMEOUT)
            if digit in valid:
                return digit
            if digit is not None:
                self.play("invalid", interruptible=False)
        raise NoInput()

    def choose_language(self):
        self.lang = None
        digit = self.ask("language_select", LANGUAGES)
        self.lang = LANGUAGES[digit]
        self.path.append(self.lang)
        log.info("Language: %s", LANGUAGE_NAMES[self.lang])

    def run(self):
        """Returns when the call should be hung up."""
        self.choose_language()
        stack = ["main"]
        while True:
            menu = MENUS[stack[-1]]
            digit = self.ask(menu["prompt"], menu["options"])
            action, arg = menu["options"][digit]
            self.path.append(stack[-1] + ":" + digit)
            if action == "menu":
                stack.append(arg)
            elif action == "play":
                if arg not in self.heard:
                    self.heard.append(arg)
                digit = self.play(arg)
                if digit in menu["options"]:
                    # Caller pressed a key while info played: treat it as a menu choice
                    self.modem.urc.appendleft("+DTMF: " + digit)
            elif action == "back":
                stack.pop()
            elif action == "language":
                self.choose_language()
                stack = ["main"]
            elif action == "book":
                if not self.caller:
                    self.play("exec_no_caller_id", interruptible=False)
                    return
                booking_id = "TV" + datetime.datetime.now().strftime("%y%m%d%H%M") + self.caller[-3:]
                self.booking = (booking_id, arg)
                log.info("Booking %s: %s site visit for %s", booking_id, arg, self.caller)
                self.play("booking_confirmed", interruptible=False)
                stack = ["main"]
            elif action == "executive":
                self.executive_requested = True
                if self.caller:
                    self.play("exec_request", interruptible=False)
                else:
                    self.play("exec_no_caller_id", interruptible=False)
                return
            # "repeat" just plays the menu again


TOPIC_NAMES = {
    "camera_4k": "4K camera", "camera_fhd": "FHD camera",
    "price_4k": "4K price", "price_fhd": "FHD price",
    "price_installation": "installation", "storage_options": "storage",
    "storage_days": "recording days",
}


def is_set(number):
    return bool(number) and "X" not in number


def send_summaries(modem, call, duration, outcome):
    """After every call: SMS to the caller, the owner and (on request) the executive."""
    now = datetime.datetime.now().strftime("%d-%b %H:%M")
    lang = LANGUAGE_NAMES.get(call.lang, "-")
    caller = call.caller or "hidden number"
    heard = ", ".join(TOPIC_NAMES.get(t, t) for t in call.heard) or "menu only"
    booking = "%s %s site visit" % call.booking if call.booking else "none"
    callback = "YES" if call.executive_requested else "no"

    if SEND_OWNER_SUMMARY_SMS and is_set(OWNER_NUMBER):
        modem.send_sms(OWNER_NUMBER,
                       "%s IVR %s: %s (%s) %ds, %s. Booking: %s. Callback: %s. Heard: %s"
                       % (BUSINESS_NAME, now, caller, lang, duration, outcome,
                          booking, callback, heard))

    if (call.executive_requested and call.caller and is_set(EXECUTIVE_NUMBER)
            and EXECUTIVE_NUMBER != OWNER_NUMBER):
        modem.send_sms(EXECUTIVE_NUMBER,
                       "%s IVR: callback request from %s (%s) at %s. Booking: %s. Heard: %s"
                       % (BUSINESS_NAME, call.caller, lang, now, booking, heard))

    if SEND_CALLER_SUMMARY_SMS and call.caller:
        parts = ["Thanks for calling %s CCTV." % BUSINESS_NAME]
        if call.booking:
            parts.append("Site visit booked for %s, ref %s. We will call to fix the date."
                         % (call.booking[1], call.booking[0]))
        if call.executive_requested:
            parts.append("An executive will call you back soon.")
        if not call.booking and not call.executive_requested and is_set(OWNER_NUMBER):
            parts.append("For bookings or help call %s." % OWNER_NUMBER)
        modem.send_sms(call.caller, " ".join(parts))


def log_booking(call):
    new = not os.path.isfile(BOOKINGS_LOG)
    with open(BOOKINGS_LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "booking_id", "caller", "language", "camera"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"),
                    call.booking[0], call.caller, LANGUAGE_NAMES.get(call.lang, ""),
                    call.booking[1]])


def log_call(call, duration, outcome):
    new = not os.path.isfile(CALL_LOG)
    with open(CALL_LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["time", "caller", "language", "path", "executive_requested",
                        "booking_id", "duration_s", "outcome"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"),
                    call.caller or "", LANGUAGE_NAMES.get(call.lang, ""),
                    " > ".join(call.path), call.executive_requested,
                    call.booking[0] if call.booking else "",
                    int(duration), outcome])


def handle_call(modem, player, caller):
    log.info("Incoming call from %s", caller or "hidden number")
    ok, final, _ = modem.command("ATA", timeout=10, finals=FINAL_RESULTS + ("NO CARRIER",))
    if not ok:
        log.info("Could not answer (%s)", final)
        return
    log.info("**ANSWERED**")
    time.sleep(0.5)  # let the voice path open before the first prompt

    call = Call(modem, player, caller)
    outcome = "completed"
    try:
        call.run()
    except CallEnded as e:
        outcome = "caller hung up"
        log.info("Call ended: %s", e)
    except NoInput:
        outcome = "no input"
        try:
            call.play("goodbye", interruptible=False)
        except CallEnded:
            pass
    finally:
        player.stop()
        modem.command("ATH", timeout=5)
        duration = time.monotonic() - call.started
        log.info("_____________________IVR END (%s, %ds)___________________", outcome, duration)

    try:
        log_call(call, duration, outcome)
        if call.booking:
            log_booking(call)
    except OSError as e:
        log.warning("Could not write call log: %s", e)
    send_summaries(modem, call, int(duration), outcome)
    # Drop leftovers from this call, but keep a new caller's RING
    pending = [l for l in modem.urc if l == "RING" or l.startswith("+CLIP")]
    modem.urc.clear()
    modem.urc.extend(pending)


def serve(modem, player):
    """Waits for incoming calls forever."""
    last_activity = time.monotonic()
    while True:
        line = modem.next_event(1.0)
        if line is None:
            if time.monotonic() - last_activity > IDLE_HEALTH_CHECK:
                if not modem.command("AT")[0]:
                    raise serial.SerialException("SIM800 stopped responding")
                if not is_registered(modem):
                    raise serial.SerialException("SIM lost network registration")
                last_activity = time.monotonic()
            continue
        last_activity = time.monotonic()

        # Any incoming call is answered: no whitelist, hidden numbers included.
        # RING, +CLIP or an incoming +CLCC (status 4) all mean someone is calling.
        clcc = CLCC_RE.match(line)
        incoming_clcc = bool(clcc) and clcc.group(1) == "4"
        if line == "RING" or line.startswith("+CLIP") or incoming_clcc:
            m = CLIP_RE.match(line) or CLCC_NUMBER_RE.match(line)
            # +CLIP normally arrives right after RING
            deadline = time.monotonic() + 3
            while m is None and time.monotonic() < deadline:
                nxt = modem.next_event(0.5)
                if nxt:
                    m = CLIP_RE.match(nxt) or CLCC_NUMBER_RE.match(nxt)
            caller = (m.group(1) or None) if m else None
            print("_____________________IVR START___________________")
            handle_call(modem, player, caller)


def main():
    print("Setting up Raspberry PI IVR")
    check_audio_files()
    player = Player()
    while True:
        modem = None
        try:
            modem = Modem(SERIAL_PORT, BAUD_RATE)
            init_modem(modem)
            serve(modem, player)
        except serial.SerialException as e:
            log.error("------->ERROR -> %s, retrying in 5s", e)
            time.sleep(5)
        finally:
            if modem:
                try:
                    modem.close()
                except Exception:
                    pass


if __name__ == "__main__":
    main()
