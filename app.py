import json

import streamlit as st
from google import genai
from google.genai import types
from twilio.rest import Client as TwilioClient

from prompts import (
    SUMMARY_REQUEST_PROMPT,
    SYSTEM_PROMPT,
    WELCOME_MESSAGE_TEMPLATE,
)

st.set_page_config(
    page_title="MacroSnap",
    page_icon="🥗",
    layout="centered",
)

MODEL_NAME = "gemini-3.5-flash"

GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

TWILIO_ACCOUNT_SID = st.secrets["TWILIO_ACCOUNT_SID"]
TWILIO_AUTH_TOKEN = st.secrets["TWILIO_AUTH_TOKEN"]
TWILIO_WHATSAPP_FROM = st.secrets["TWILIO_WHATSAPP_FROM"]
TWILIO_CONTENT_SID = st.secrets["TWILIO_CONTENT_SID"]


@st.cache_resource
def get_gemini_client():
    return genai.Client(api_key=GEMINI_API_KEY)


@st.cache_resource
def get_twilio_client():
    return TwilioClient(
        TWILIO_ACCOUNT_SID,
        TWILIO_AUTH_TOKEN,
    )


gemini_client = get_gemini_client()
twilio_client = get_twilio_client()


def initialize_session_state():
    defaults = {
        "onboarded": False,
        "messages": [],
        "chat": None,
        "name": "",
        "whatsapp_number": "",
    }

    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


initialize_session_state()


def render_message(message):
    with st.chat_message(message["role"]):
        kind = message.get("kind")
        content = message.get("content")

        if kind == "text":
            st.write(content)
        elif kind == "image":
            st.image(content)
        else:
            st.write(content)


def add_message(role, kind, content):
    message = {
        "role": role,
        "kind": kind,
        "content": content,
    }

    st.session_state.messages.append(message)
    render_message(message)


def ask_gemini(parts):
    if not st.session_state.chat:
        return "Please restart the app and try again."

    try:
        response = st.session_state.chat.send_message(parts)

        if not response or not response.text:
            return "Sorry, I couldn't generate a response."

        return response.text

    except Exception as error:
        return f"Sorry, something went wrong: {error}"


def clean_whatsapp_text(text):
    if not text:
        return "No nutrition summary available."

    cleaned = " ".join(str(text).split())
    max_length = 1500

    if len(cleaned) > max_length:
        return cleaned[:max_length] + "..."

    return cleaned


def normalize_whatsapp_number(number):
    return (
        number.strip()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )


def send_whatsapp(to_number, user_name, summary):
    try:
        phone_number = normalize_whatsapp_number(to_number)

        content_variables = json.dumps(
            {
                "1": user_name,
                "2": clean_whatsapp_text(summary),
            },
            ensure_ascii=False,
        )

        message = twilio_client.messages.create(
            from_=TWILIO_WHATSAPP_FROM,
            to=f"whatsapp:{phone_number}",
            content_sid=TWILIO_CONTENT_SID,
            content_variables=content_variables,
        )

        return True, message.sid

    except Exception as error:
        return False, str(error)


def show_onboarding():
    st.title("🥗 MacroSnap")
    st.caption("Snap it. Track it. Text yourself the results.")

    with st.form("onboarding_form"):
        name = st.text_input(
            "Your name",
            placeholder="Enter your name",
        )

        whatsapp_number = st.text_input(
            "WhatsApp number",
            placeholder="+91XXXXXXXXXX",
            help="Enter the WhatsApp number that should receive your nutrition summary.",
        )

        submitted = st.form_submit_button(
            "Let's go 🚀",
            use_container_width=True,
        )

    if not submitted:
        return

    name = name.strip()
    whatsapp_number = normalize_whatsapp_number(whatsapp_number)

    if not name:
        st.warning("Please enter your name.")
        return

    if not whatsapp_number:
        st.warning("Please enter your WhatsApp number.")
        return

    if not whatsapp_number.startswith("+"):
        st.warning(
            "Please include your country code, for example +91XXXXXXXXXX."
        )
        return

    try:
        chat = gemini_client.chats.create(
            model=MODEL_NAME,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
            ),
        )

        st.session_state.name = name
        st.session_state.whatsapp_number = whatsapp_number
        st.session_state.chat = chat
        st.session_state.messages = []
        st.session_state.onboarded = True

        st.rerun()

    except Exception as error:
        st.error(f"Could not start MacroSnap: {error}")


def show_chat():
    header_col, button_col = st.columns(
        [5, 2],
        vertical_alignment="center",
    )

    with header_col:
        st.title("🥗 MacroSnap")

    with button_col:
        has_user_messages = any(
            message["role"] == "user"
            for message in st.session_state.messages
        )

        if st.button(
            "📤 Send to WhatsApp",
            disabled=not has_user_messages,
            use_container_width=True,
        ):
            with st.spinner("Summarizing your day..."):
                summary = ask_gemini(
                    [SUMMARY_REQUEST_PROMPT]
                )

            success, info = send_whatsapp(
                st.session_state.whatsapp_number,
                st.session_state.name,
                summary,
            )

            if success:
                st.success("Sent! Check your WhatsApp 📲")
            else:
                st.error(
                    f"Couldn't send the summary: {info}"
                )

    st.caption(
        f"Logged in as {st.session_state.name} · "
        f"Updates go to {st.session_state.whatsapp_number}"
    )

    if not st.session_state.messages:
        welcome_message = WELCOME_MESSAGE_TEMPLATE.format(
            name=st.session_state.name
        )

        add_message(
            "assistant",
            "text",
            welcome_message,
        )
    else:
        for message in st.session_state.messages:
            render_message(message)

    user_input = st.chat_input(
        "Ask a question, or attach a photo of your meal",
        accept_file=True,
        file_type=["jpg", "jpeg", "png"],
    )

    if not user_input:
        return

    photo = (
        user_input.files[0]
        if user_input.files
        else None
    )

    text = user_input.text.strip()
    parts = []

    if photo is not None:
        photo_bytes = photo.getvalue()

        add_message(
            "user",
            "image",
            photo_bytes,
        )

        parts.append(
            types.Part.from_bytes(
                data=photo_bytes,
                mime_type=photo.type,
            )
        )

    if text:
        add_message(
            "user",
            "text",
            text,
        )

        parts.append(text)

    elif photo is not None:
        parts.append(
            "Analyze this meal. Identify the food, "
            "estimate calories, protein, carbohydrates, "
            "and fat. Clearly mention that the values "
            "are estimates."
        )

    if not parts:
        return

    with st.spinner("Crunching the numbers..."):
        answer = ask_gemini(parts)

    add_message(
        "assistant",
        "text",
        answer,
    )


if not st.session_state.onboarded:
    show_onboarding()
    st.stop()

show_chat()