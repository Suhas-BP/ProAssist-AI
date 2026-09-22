"""
Email Flow Module for ProAssist AI Phase 2
Handles the multi-turn conversational email flow:
Recipient lookup -> Body -> Subject -> Preview -> Explicit Confirmation -> Send.
"""

from phase2.email.contact_manager import ContactManager
from phase2.email.email_parser import EmailParser
from phase2.email.email_composer import EmailComposer, EmailDraft
from phase2.email.email_sender import EmailSender


def handle_email_flow(
    recipient_name: str,
    contact_manager: ContactManager,
    command_listener,
    responder,
    email_sender: EmailSender,
) -> dict:
    """
    Executes the conversational voice email workflow.
    Returns dictionary with final outcome and draft details.
    """
    parser = EmailParser()
    composer = EmailComposer()

    # 1. Contact lookup
    contact = contact_manager.get_contact(recipient_name)
    if contact:
        recipient_email = contact["email"]
        recipient_disp_name = contact.get("name", recipient_name)
        responder.respond(
            f"I found {recipient_disp_name}'s email address. What should I write in the email?",
            speak=True
        )
    else:
        responder.respond(
            f"I couldn't find that contact. What is their email address?",
            speak=True
        )
        spoken_email = command_listener.listen_and_transcribe()
        cleaned_email = contact_manager.parse_spoken_email(spoken_email)

        if not contact_manager.is_valid_email(cleaned_email):
            msg = "That does not appear to be a valid email address. Canceling email draft."
            responder.respond(msg, speak=True)
            return {"status": "cancelled", "message": msg, "draft": None}

        contact_manager.add_contact(recipient_name, cleaned_email)
        responder.respond("Got it. I'll use that email address.", speak=True)
        recipient_email = cleaned_email
        recipient_disp_name = recipient_name.capitalize()
        responder.respond("What should I write in the email?", speak=True)

    # 2. Capture email body
    body_text = command_listener.listen_and_transcribe()
    if not body_text:
        msg = "No message content detected. Canceling email draft."
        responder.respond(msg, speak=True)
        return {"status": "cancelled", "message": msg, "draft": None}

    # 3. Capture email subject
    responder.respond("What should the subject be?", speak=True)
    subject_text = command_listener.listen_and_transcribe()
    if not subject_text:
        subject_text = "Message from ProAssist"

    # 4. Construct draft
    draft = composer.start_draft(
        recipient_name=recipient_disp_name,
        recipient_email=recipient_email
    )
    composer.set_subject(subject_text)
    composer.set_body(body_text)

    # 5. Review & Explicit confirmation
    print("\n--- EMAIL PREVIEW ---")
    print(draft.format_preview())
    print("---------------------\n")

    responder.respond("I have prepared the email.", speak=True)
    responder.respond("Would you like me to send it?", speak=True)

    # 6. Wait for explicit user confirmation
    confirm_text = command_listener.listen_and_transcribe()

    if parser.is_confirmation(confirm_text):
        draft.confirm()
        result = email_sender.send_email(draft, confirmed=True)
        responder.respond(result["message"], speak=True)
        return {
            "status": result.get("status", "error"),
            "message": result.get("message", ""),
            "draft": draft
        }
    else:
        msg = "Email sending cancelled."
        responder.respond(msg, speak=True)
        return {
            "status": "cancelled",
            "message": msg,
            "draft": draft
        }
