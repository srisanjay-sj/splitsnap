import re
import time
import urllib.parse

import streamlit as st
from google import genai
from google.genai import types

from prompts import SYSTEM_PROMPT, WELCOME_MESSAGE_TEMPLATE, SUMMARY_REQUEST_PROMPT
from style import CSS

st.set_page_config(page_title="SplitSnap", page_icon="🧾")
st.markdown(CSS, unsafe_allow_html=True)

GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
MODEL_NAME = "gemini-3.5-flash-lite"


@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)


gemini_client = get_gemini_client()


def render_message(message):
    avatar = "🧾" if message["role"] == "assistant" else "🙂"
    with st.chat_message(message["role"], avatar=avatar):
        if message["kind"] == "text":
            st.write(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"])


def add_message(role, kind, content):
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})
    render_message(st.session_state.messages[-1])


def ask_gemini(parts):
    """Returns (text, ok). Retries on 503 and on empty replies."""
    last_error = None
    for attempt in range(6):
        try:
            response = st.session_state.chat.send_message(parts)
            if response.text:
                return response.text, True
            reason = (
                response.candidates[0].finish_reason
                if response.candidates
                else "no candidates"
            )
            print("Empty reply, finish_reason:", reason)
            last_error = f"Empty reply from the model ({reason})"
            time.sleep(1)
            continue
        except Exception as error:
            last_error = error
            if "503" in str(error) or "UNAVAILABLE" in str(error):
                time.sleep(2 * (attempt + 1))
                continue
            break
    return f"Sorry, something went wrong: {last_error}", False


# ---------- Onboarding ----------
if "onboarded" not in st.session_state:
    st.markdown(
        '<div class="hero">'
        '<span class="pill">AI bill splitter</span>'
        '<h1>Snap your bill. <span class="accent">Split it</span> in seconds.</h1>'
        '<p style="color:#9CA0B8 !important;">SplitSnap reads a photo or a '
        'description of your bill, works out the total, and splits it between '
        'friends, then sends the breakdown to WhatsApp.</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    with st.form("onboarding_form"):
        name = st.text_input("Your name")
        whatsapp_number = st.text_input(
            "WhatsApp number (with country code)",
            placeholder="+91XXXXXXXXXX",
            help="This is the number SplitSnap will send your summary to.",
        )
        submitted = st.form_submit_button("Start splitting 🚀")

    if submitted:
        number = whatsapp_number.replace(" ", "")
        if not name.strip() or not number:
            st.warning("Please fill in both your name and WhatsApp number.")
        elif not re.fullmatch(r"\+\d{10,15}", number):
            st.warning("Number must start with + and country code, e.g. +919876543210")
        else:
            st.session_state.name = name.strip()
            st.session_state.whatsapp_number = number
            st.session_state.chat = gemini_client.chats.create(
                model=MODEL_NAME,
                config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
            )
            st.session_state.messages = []
            st.session_state.onboarded = True
            st.rerun()
    st.stop()

# ---------- Chat screen ----------
header_col, button_col = st.columns([5, 2], vertical_alignment="center")

with header_col:
    st.markdown(
        '<h1 class="brand">Split<span class="accent">Snap</span></h1>',
        unsafe_allow_html=True,
    )

with button_col:
    send_disabled = len(st.session_state.messages) <= 1
    if st.button("📤 Send to WhatsApp", disabled=send_disabled, use_container_width=True):
        with st.spinner("Summarizing your bills..."):
            summary, ok = ask_gemini([SUMMARY_REQUEST_PROMPT])
        if not ok:
            st.error(summary)
        else:
            text = f"Hi {st.session_state.name}, here is your SplitSnap summary:\n\n{summary}"
            number = st.session_state.whatsapp_number.lstrip("+")
            st.session_state.wa_link = (
                f"https://wa.me/{number}?text={urllib.parse.quote(text[:1500])}"
            )
    if st.session_state.get("wa_link"):
        st.link_button(
            "📲 Open in WhatsApp", st.session_state.wa_link, use_container_width=True
        )

st.caption(
    f"Logged in as {st.session_state.name} - updates go to {st.session_state.whatsapp_number}"
)

if not st.session_state.messages:
    add_message(
        "assistant", "text", WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name)
    )
else:
    for message in st.session_state.messages:
        render_message(message)

user_input = st.chat_input(
    "Ask a question, or attach a photo of your bill",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)

if user_input:
    st.session_state.wa_link = None
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text
    parts = []

    if photo is not None:
        photo_bytes = photo.getvalue()
        add_message("user", "image", photo_bytes)
        parts.append(types.Part.from_bytes(data=photo_bytes, mime_type=photo.type))
    if text:
        add_message("user", "text", text)
        parts.append(text)
    elif photo is not None:
        parts.append("What is this bill? List the items and the total.")

    with st.spinner("Reading the bill..."):
        answer, _ = ask_gemini(parts)
    add_message("assistant", "text", answer)
    st.rerun()