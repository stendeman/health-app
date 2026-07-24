import argparse
import json
import os
import smtplib
import time
from email.message import EmailMessage

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel

from src.measurements import get_all_measurements


DEFAULT_SMTP_PORT = 587
POLL_INTERVAL_SECONDS = 1
POLL_TIMEOUT_SECONDS = 600
DEFAULT_REASONING_EFFORT = 'none'
DEFAULT_MAX_OUTPUT_TOKENS = 5_000


class Email(BaseModel):
    subject: str
    content: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Generate and send health progress email.')
    parser.add_argument(
        '--reasoning',
        choices=['none', 'low', 'medium', 'high', 'xhigh', 'max'],
        default=DEFAULT_REASONING_EFFORT,
        help='Reasoning effort for OpenAI Responses API.',
    )
    parser.add_argument(
        '--maxtokens',
        type=int,
        default=DEFAULT_MAX_OUTPUT_TOKENS,
        help='Maximum output tokens for OpenAI Responses API.',
    )
    return parser.parse_args()


def send_email(email: Email) -> None:
    smtp_host = os.environ['SMTP_HOST']
    smtp_port = (
        int(os.environ['SMTP_PORT']) if 'SMTP_PORT' in os.environ else DEFAULT_SMTP_PORT
    )
    smtp_username = os.environ['SMTP_USERNAME']
    smtp_password = os.environ['SMTP_PASSWORD']
    email_from = os.environ['EMAIL_FROM'] if 'EMAIL_FROM' in os.environ else smtp_username
    email_to = os.environ['EMAIL_TO']

    message = EmailMessage()
    message['Subject'] = email.subject
    message['From'] = email_from
    message['To'] = email_to
    message.add_alternative(email.content, subtype='html')

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(message)

def main() -> None:
    args = parse_args()

    load_dotenv()

    measurements = get_all_measurements()

    openai = OpenAI()

    response = openai.responses.parse(
        model='gpt-5.6',
        reasoning={'effort': args.reasoning},
        background=True,
        max_output_tokens=args.maxtokens,
        text_format=Email,
        instructions=("""
            Generate an html email exploring the user's weight loss progress from the data.
            Especially, focus on the last 7 days. But feel free to use all data to put the more recent trends into context.
            Perform your own analysis on the data, feel free to explore patterns using your own data analysis tools of choice.
            Include relevant graphs using inline.
            
            Start the email with evaluation how the user is doing, alongside a summary of key findings (numbers).
            Then, include analysis and figures to support the findings.
            Close the email with some motivational words.

            Use metric system for units, and Amsterdam timezone.
        """),
        input=[{
            'role': 'user',
            'content': [{
                'type': 'input_text',
                'text': json.dumps(measurements),
            }],
        }]
    )

    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while response.status in {'queued', 'in_progress'}:
        if time.time() >= deadline:
            raise TimeoutError(
                'OpenAI background response timed out while polling for completion.'
            )

        time.sleep(POLL_INTERVAL_SECONDS)
        response = openai.responses.retrieve(response.id)

    if response.status != 'completed':
        raise RuntimeError(
            f'OpenAI background response did not complete successfully: {response.status}'
        )

    email = Email.model_validate_json(response.output_text)

    print(email.subject)
    print(email.content)
    send_email(email)


if __name__ == '__main__':
    main()

    