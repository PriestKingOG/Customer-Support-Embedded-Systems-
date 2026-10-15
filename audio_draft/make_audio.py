#!/usr/bin/env python3
"""
Makes draft IVR prompts with text-to-speech (espeak-ng), in the format the
SIM800L needs: WAV, 8000 Hz, mono, 16-bit.

    sudo apt install espeak-ng ffmpeg
    python3 make_audio.py

1. Fill in your real prices and numbers in FILL_IN below (they are spoken in
   all three languages), then run this again to rebuild every file.
2. Any file you later record yourself can simply replace the draft in audio/.
"""
import os
import subprocess
import tempfile
import wave

# _____________________________________________________________________________
# FILL_IN - OWNER: replace every "X" with your real figure, then re-run
# _____________________________________________________________________________
FILL_IN = {
    "warranty_years": "X",
    "price_4k_camera": "X",     # rupees per 4K camera
    "price_4k_kit": "X",        # rupees for a 4-camera 4K kit
    "price_fhd_camera": "X",    # rupees per Full HD camera
    "price_fhd_kit": "X",       # rupees for a 4-camera Full HD kit
    "price_install": "X",       # rupees installation per camera
    "price_wiring": "X",         # rupees wiring per metre
    "price_500gb": "X",
    "price_1tb": "X",
    "price_2tb": "X",
    "price_4tb": "X",
    "days_4k_1tb": "X",         # days of recording on 1 TB with 4 cameras
    "days_fhd_1tb": "X",
    "executive_phone": "X",     # spoken digit by digit, e.g. "9 8 7 6 5 4 3 2 1 0"
}

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
AUDIO_DIR = os.path.join(BASE_DIR, "audio")
VOICES = {"en": "en-gb", "hi": "hi", "mr": "mr"}
SPEED = 140  # words per minute; slower is clearer over a phone line

TEXTS = {
    "en": {
        "main_menu": "For camera information, press 1. For prices, press 2. For storage options, press 3. "
                     "To talk to our support executive, press 4. To book a free site visit, press 5. "
                     "To repeat, press 9. To change language, press 0.",
        "cameras_menu": "For our 4K Ultra HD camera, press 1. For our Full HD 1080p camera, press 2. "
                        "To talk to an executive, press 4. To repeat, press 9. To go back, press 0.",
        "camera_4k": "The TrueView 4K Ultra HD camera records 8 megapixel video with very sharp detail. "
                     "It works indoors and outdoors, has night vision, and comes with a {warranty_years} year warranty.",
        "camera_fhd": "The TrueView Full HD camera records 2 megapixel, 1080p video, ideal for homes and shops. "
                      "It works indoors and outdoors, has night vision, and comes with a {warranty_years} year warranty.",
        "prices_menu": "For 4K camera prices, press 1. For Full HD camera prices, press 2. "
                       "For installation charges, press 3. To talk to an executive, press 4. "
                       "To repeat, press 9. To go back, press 0.",
        "price_4k": "The 4K camera costs {price_4k_camera} rupees per camera. "
                    "A 4 camera 4K kit costs {price_4k_kit} rupees.",
        "price_fhd": "The Full HD camera costs {price_fhd_camera} rupees per camera. "
                     "A 4 camera Full HD kit costs {price_fhd_kit} rupees.",
        "price_installation": "Installation costs {price_install} rupees per camera, "
                              "and wiring costs {price_wiring} rupees per metre.",
        "storage_menu": "For hard disk options and prices, press 1. To hear how many days of recording "
                        "each size stores, press 2. To talk to an executive, press 4. "
                        "To repeat, press 9. To go back, press 0.",
        "storage_options": "We offer a 500 GB hard disk for {price_500gb} rupees, 1 TB for {price_1tb} rupees, "
                           "2 TB for {price_2tb} rupees, and 4 TB for {price_4tb} rupees.",
        "storage_days": "With 4 cameras, a 1 TB hard disk stores about {days_4k_1tb} days of 4K recording, "
                        "or about {days_fhd_1tb} days of Full HD recording. A 2 TB disk stores twice as long.",
        "booking_menu": "To book a site visit for 4K cameras, press 1. For Full HD cameras, press 2. "
                        "To repeat, press 9. To go back, press 0.",
        "booking_confirmed": "Your site visit is booked. You will receive an SMS with your booking reference, "
                             "and our team will call you to fix the date. Returning to the main menu.",
        "exec_connecting": "Please hold while we connect you to our customer support representative.",
        "exec_unavailable": "Sorry, our representative is not available right now.",
        "exec_request": "Thank you. Our support executive will call you back shortly on this number. Goodbye.",
        "exec_no_caller_id": "Your number is hidden, so we cannot call you back or confirm a booking. "
                             "Please call our executive directly on {executive_phone}. Goodbye.",
        "invalid": "Sorry, that is not a valid choice.",
        "goodbye": "Thank you for calling TrueView. Goodbye.",
    },
    "hi": {
        "main_menu": "कैमरे की जानकारी के लिए 1 दबाएं. कीमतों के लिए 2 दबाएं. स्टोरेज विकल्पों के लिए 3 दबाएं. "
                     "हमारे सपोर्ट एग्ज़ीक्यूटिव से बात करने के लिए 4 दबाएं. मुफ़्त साइट विज़िट बुक करने के लिए 5 दबाएं. "
                     "दोबारा सुनने के लिए 9 दबाएं. भाषा बदलने के लिए 0 दबाएं.",
        "cameras_menu": "फ़ोर के अल्ट्रा एच डी कैमरे के लिए 1 दबाएं. फुल एच डी कैमरे के लिए 2 दबाएं. "
                        "एग्ज़ीक्यूटिव से बात करने के लिए 4 दबाएं. दोबारा सुनने के लिए 9 दबाएं. पीछे जाने के लिए 0 दबाएं.",
        "camera_4k": "ट्रूव्यू फ़ोर के अल्ट्रा एच डी कैमरा 8 मेगापिक्सल का बहुत साफ़ वीडियो रिकॉर्ड करता है. "
                     "यह घर के अंदर और बाहर दोनों जगह काम करता है, इसमें नाइट विज़न है, और {warranty_years} साल की वारंटी है.",
        "camera_fhd": "ट्रूव्यू फुल एच डी कैमरा 2 मेगापिक्सल का वीडियो रिकॉर्ड करता है, जो घरों और दुकानों के लिए बढ़िया है. "
                      "यह घर के अंदर और बाहर दोनों जगह काम करता है, इसमें नाइट विज़न है, और {warranty_years} साल की वारंटी है.",
        "prices_menu": "फ़ोर के कैमरे की कीमत के लिए 1 दबाएं. फुल एच डी कैमरे की कीमत के लिए 2 दबाएं. "
                       "इंस्टॉलेशन चार्ज के लिए 3 दबाएं. एग्ज़ीक्यूटिव से बात करने के लिए 4 दबाएं. "
                       "दोबारा सुनने के लिए 9 दबाएं. पीछे जाने के लिए 0 दबाएं.",
        "price_4k": "फ़ोर के कैमरे की कीमत {price_4k_camera} रुपये प्रति कैमरा है. "
                    "4 कैमरों वाला फ़ोर के किट {price_4k_kit} रुपये का है.",
        "price_fhd": "फुल एच डी कैमरे की कीमत {price_fhd_camera} रुपये प्रति कैमरा है. "
                     "4 कैमरों वाला फुल एच डी किट {price_fhd_kit} रुपये का है.",
        "price_installation": "इंस्टॉलेशन का चार्ज {price_install} रुपये प्रति कैमरा है, "
                              "और वायरिंग {price_wiring} रुपये प्रति मीटर है.",
        "storage_menu": "हार्ड डिस्क के विकल्प और कीमत के लिए 1 दबाएं. हर साइज़ में कितने दिन की रिकॉर्डिंग होती है, "
                        "यह सुनने के लिए 2 दबाएं. एग्ज़ीक्यूटिव से बात करने के लिए 4 दबाएं. "
                        "दोबारा सुनने के लिए 9 दबाएं. पीछे जाने के लिए 0 दबाएं.",
        "storage_options": "500 जी बी हार्ड डिस्क {price_500gb} रुपये, 1 टी बी {price_1tb} रुपये, "
                           "2 टी बी {price_2tb} रुपये, और 4 टी बी {price_4tb} रुपये में उपलब्ध है.",
        "storage_days": "4 कैमरों के साथ, 1 टी बी हार्ड डिस्क में लगभग {days_4k_1tb} दिन की फ़ोर के रिकॉर्डिंग, "
                        "या लगभग {days_fhd_1tb} दिन की फुल एच डी रिकॉर्डिंग होती है. 2 टी बी में दोगुनी रिकॉर्डिंग होती है.",
        "booking_menu": "फ़ोर के कैमरों की साइट विज़िट बुक करने के लिए 1 दबाएं. फुल एच डी कैमरों के लिए 2 दबाएं. "
                        "दोबारा सुनने के लिए 9 दबाएं. पीछे जाने के लिए 0 दबाएं.",
        "booking_confirmed": "आपकी साइट विज़िट बुक हो गई है. आपको बुकिंग नंबर के साथ एक एस एम एस मिलेगा, "
                             "और हमारी टीम तारीख तय करने के लिए आपको कॉल करेगी. अब आप मुख्य मेनू में हैं.",
        "exec_connecting": "कृपया लाइन पर बने रहें, हम आपको हमारे कस्टमर सपोर्ट प्रतिनिधि से जोड़ रहे हैं.",
        "exec_unavailable": "माफ़ कीजिए, हमारे प्रतिनिधि अभी उपलब्ध नहीं हैं.",
        "exec_request": "धन्यवाद. हमारे सपोर्ट एग्ज़ीक्यूटिव जल्द ही आपको इसी नंबर पर कॉल करेंगे. नमस्ते.",
        "exec_no_caller_id": "आपका नंबर छिपा हुआ है, इसलिए हम आपको कॉल नहीं कर सकते या बुकिंग पक्की नहीं कर सकते. "
                             "कृपया हमारे एग्ज़ीक्यूटिव को सीधे {executive_phone} पर कॉल करें. नमस्ते.",
        "invalid": "माफ़ कीजिए, यह सही विकल्प नहीं है.",
        "goodbye": "ट्रूव्यू को कॉल करने के लिए धन्यवाद. नमस्ते.",
    },
    "mr": {
        "main_menu": "कॅमेऱ्यांच्या माहितीसाठी 1 दाबा. किमतींसाठी 2 दाबा. स्टोरेज पर्यायांसाठी 3 दाबा. "
                     "आमच्या सपोर्ट एक्झिक्युटिव्हशी बोलण्यासाठी 4 दाबा. मोफत साइट व्हिजिट बुक करण्यासाठी 5 दाबा. "
                     "पुन्हा ऐकण्यासाठी 9 दाबा. भाषा बदलण्यासाठी 0 दाबा.",
        "cameras_menu": "फोर के अल्ट्रा एच डी कॅमेऱ्यासाठी 1 दाबा. फुल एच डी कॅमेऱ्यासाठी 2 दाबा. "
                        "एक्झिक्युटिव्हशी बोलण्यासाठी 4 दाबा. पुन्हा ऐकण्यासाठी 9 दाबा. मागे जाण्यासाठी 0 दाबा.",
        "camera_4k": "ट्रूव्ह्यू फोर के अल्ट्रा एच डी कॅमेरा 8 मेगापिक्सेलचा अतिशय स्पष्ट व्हिडिओ रेकॉर्ड करतो. "
                     "तो घरात आणि बाहेर दोन्हीकडे चालतो, त्यात नाईट व्हिजन आहे, आणि {warranty_years} वर्षांची वॉरंटी आहे.",
        "camera_fhd": "ट्रूव्ह्यू फुल एच डी कॅमेरा 2 मेगापिक्सेलचा व्हिडिओ रेकॉर्ड करतो, जो घरे आणि दुकानांसाठी उत्तम आहे. "
                      "तो घरात आणि बाहेर दोन्हीकडे चालतो, त्यात नाईट व्हिजन आहे, आणि {warranty_years} वर्षांची वॉरंटी आहे.",
        "prices_menu": "फोर के कॅमेऱ्याच्या किमतीसाठी 1 दाबा. फुल एच डी कॅमेऱ्याच्या किमतीसाठी 2 दाबा. "
                       "इन्स्टॉलेशन शुल्कासाठी 3 दाबा. एक्झिक्युटिव्हशी बोलण्यासाठी 4 दाबा. "
                       "पुन्हा ऐकण्यासाठी 9 दाबा. मागे जाण्यासाठी 0 दाबा.",
        "price_4k": "फोर के कॅमेऱ्याची किंमत प्रति कॅमेरा {price_4k_camera} रुपये आहे. "
                    "4 कॅमेऱ्यांचा फोर के किट {price_4k_kit} रुपयांना आहे.",
        "price_fhd": "फुल एच डी कॅमेऱ्याची किंमत प्रति कॅमेरा {price_fhd_camera} रुपये आहे. "
                     "4 कॅमेऱ्यांचा फुल एच डी किट {price_fhd_kit} रुपयांना आहे.",
        "price_installation": "इन्स्टॉलेशन शुल्क प्रति कॅमेरा {price_install} रुपये आहे, "
                              "आणि वायरिंग प्रति मीटर {price_wiring} रुपये आहे.",
        "storage_menu": "हार्ड डिस्कचे पर्याय आणि किमतींसाठी 1 दाबा. प्रत्येक साइजमध्ये किती दिवसांचे रेकॉर्डिंग राहते "
                        "हे ऐकण्यासाठी 2 दाबा. एक्झिक्युटिव्हशी बोलण्यासाठी 4 दाबा. "
                        "पुन्हा ऐकण्यासाठी 9 दाबा. मागे जाण्यासाठी 0 दाबा.",
        "storage_options": "500 जी बी हार्ड डिस्क {price_500gb} रुपये, 1 टी बी {price_1tb} रुपये, "
                           "2 टी बी {price_2tb} रुपये, आणि 4 टी बी {price_4tb} रुपयांना उपलब्ध आहे.",
        "storage_days": "4 कॅमेऱ्यांसह, 1 टी बी हार्ड डिस्कमध्ये सुमारे {days_4k_1tb} दिवसांचे फोर के रेकॉर्डिंग, "
                        "किंवा सुमारे {days_fhd_1tb} दिवसांचे फुल एच डी रेकॉर्डिंग राहते. 2 टी बी मध्ये दुप्पट रेकॉर्डिंग राहते.",
        "booking_menu": "फोर के कॅमेऱ्यांसाठी साइट व्हिजिट बुक करण्यासाठी 1 दाबा. फुल एच डी कॅमेऱ्यांसाठी 2 दाबा. "
                        "पुन्हा ऐकण्यासाठी 9 दाबा. मागे जाण्यासाठी 0 दाबा.",
        "booking_confirmed": "तुमची साइट व्हिजिट बुक झाली आहे. तुम्हाला बुकिंग क्रमांकासह एक एस एम एस मिळेल, "
                             "आणि आमची टीम तारीख ठरवण्यासाठी तुम्हाला कॉल करेल. आता तुम्ही मुख्य मेनूमध्ये आहात.",
        "exec_connecting": "कृपया लाईनवर थांबा, आम्ही तुम्हाला आमच्या कस्टमर सपोर्ट प्रतिनिधीशी जोडत आहोत.",
        "exec_unavailable": "माफ करा, आमचे प्रतिनिधी सध्या उपलब्ध नाहीत.",
        "exec_request": "धन्यवाद. आमचे सपोर्ट एक्झिक्युटिव्ह लवकरच तुम्हाला याच नंबरवर कॉल करतील. नमस्कार.",
        "exec_no_caller_id": "तुमचा नंबर लपवलेला आहे, त्यामुळे आम्ही तुम्हाला कॉल करू शकत नाही किंवा बुकिंग निश्चित करू शकत नाही. "
                             "कृपया आमच्या एक्झिक्युटिव्हला थेट {executive_phone} वर कॉल करा. नमस्कार.",
        "invalid": "माफ करा, हा योग्य पर्याय नाही.",
        "goodbye": "ट्रूव्ह्यूला कॉल केल्याबद्दल धन्यवाद. नमस्कार.",
    },
}

# common/ files: one segment per language, played back to back
COMMON = {
    "language_select": [
        ("en", "Welcome to TrueView CCTV. For English, press 1."),
        ("hi", "हिंदी के लिए 2 दबाएं."),
        ("mr", "मराठीसाठी 3 दाबा."),
    ],
    "invalid": [("en", TEXTS["en"]["invalid"]), ("hi", TEXTS["hi"]["invalid"]),
                ("mr", TEXTS["mr"]["invalid"])],
    "goodbye": [("en", TEXTS["en"]["goodbye"]), ("hi", TEXTS["hi"]["goodbye"]),
                ("mr", TEXTS["mr"]["goodbye"])],
}

GAP_SECONDS = 0.4  # pause between language segments


def speak(lang, text, out_path):
    """Text -> WAV at 8000 Hz, mono, 16-bit."""
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        raw = tmp.name
    try:
        subprocess.run(["espeak-ng", "-v", VOICES[lang], "-s", str(SPEED), "-w", raw,
                        text.format(**FILL_IN)], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", raw,
                        "-ar", "8000", "-ac", "1", "-sample_fmt", "s16", out_path], check=True)
    finally:
        os.remove(raw)


def join_wavs(parts, out_path):
    frames = []
    for p in parts:
        with wave.open(p) as w:
            params = w.getparams()
            frames.append(w.readframes(w.getnframes()))
    silence = b"\x00\x00" * int(8000 * GAP_SECONDS)
    with wave.open(out_path, "wb") as out:
        out.setparams(params)
        out.writeframes(silence.join(frames))


def main():
    missing = [k for k, v in FILL_IN.items() if v == "X"]
    if missing:
        print("Note: still placeholders (spoken as 'X'): " + ", ".join(missing))

    count = 0
    for lang, texts in TEXTS.items():
        os.makedirs(os.path.join(AUDIO_DIR, lang), exist_ok=True)
        for name, text in texts.items():
            speak(lang, text, os.path.join(AUDIO_DIR, lang, name + ".wav"))
            count += 1

    common_dir = os.path.join(AUDIO_DIR, "common")
    os.makedirs(common_dir, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        for name, segments in COMMON.items():
            parts = []
            for i, (lang, text) in enumerate(segments):
                part = os.path.join(tmp, "%s_%d.wav" % (name, i))
                speak(lang, text, part)
                parts.append(part)
            join_wavs(parts, os.path.join(common_dir, name + ".wav"))
            count += 1
    print("Wrote %d WAV files to %s" % (count, AUDIO_DIR))


if __name__ == "__main__":
    main()
