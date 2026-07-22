import json
import os
import smtplib
from email.message import EmailMessage

from pydantic import BaseModel
from dotenv import load_dotenv

from openai import OpenAI
from withings_client import MeasureType, WithingsClient

from measurement import Measurement


class Email(BaseModel):
    subject: str
    content: str


def send_email(email: Email) -> None:
    smtp_host = os.environ.get('SMTP_HOST')
    smtp_port = int(os.environ.get('SMTP_PORT', '587'))
    smtp_username = os.environ.get('SMTP_USERNAME')
    smtp_password = os.environ.get('SMTP_PASSWORD')
    email_from = os.environ.get('EMAIL_FROM', smtp_username)
    email_to = os.environ.get('EMAIL_TO')

    missing = [
        name for name, value in {
            'SMTP_HOST': smtp_host,
            'SMTP_USERNAME': smtp_username,
            'SMTP_PASSWORD': smtp_password,
            'EMAIL_FROM': email_from,
            'EMAIL_TO': email_to,
        }.items() if not value
    ]
    if missing:
        raise ValueError(f"Missing required environment variables: {', '.join(missing)}")

    message = EmailMessage()
    message['Subject'] = email.subject
    message['From'] = email_from
    message['To'] = email_to
    message.set_content(email.content)

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        server.starttls()
        server.login(smtp_username, smtp_password)
        server.send_message(message)

if __name__ == '__main__':
    load_dotenv()

    client = WithingsClient()

    data = client.get_measurements(
        meastypes=[
            MeasureType.WEIGHT,
            MeasureType.FAT_RATIO,
            MeasureType.MUSCLE_MASS,
            MeasureType.BONE_MASS,
            MeasureType.VISCERAL_FAT,
        ],
        category=1,
    )['body']['measuregrps']

    measurements = [Measurement.from_json(i['measures']) for i in data]
    measurements_json = [measurement.model_dump() for measurement in measurements]

    openai = OpenAI()

    response = openai.responses.parse(
        model='gpt-5.6',
        instructions=('Generate an email summarizing the progress in weight loss given the data'),
        input=[{
            'role': 'user',
            'content': [{
                'type': 'input_text',
                'text': json.dumps(measurements_json),
            }],
        }],
        text_format=Email
    )

    email = Email.model_validate_json(response.output_text)

    print(email.subject)
    print(email.content)
    send_email(email)

    