import json
import os
import smtplib
import time
from email.message import EmailMessage

from pydantic import BaseModel
from dotenv import load_dotenv

from openai import OpenAI
from withings_client import MeasureType, WithingsClient


DEFAULT_SMTP_PORT = 587
POLL_INTERVAL_SECONDS = 1
POLL_TIMEOUT_SECONDS = 600


class Email(BaseModel):
    subject: str
    content: str


def decimal_places(value: int, unit: int) -> int:
    if unit >= 0:
        return 0

    decimals = -unit
    abs_value = abs(value)
    removable = 0

    while removable < decimals and abs_value != 0 and abs_value % 10 == 0:
        abs_value //= 10
        removable += 1

    return decimals - removable
    

def get_measurements(*meastypes):
    json = client.get_measurements(meastypes=meastypes, category=1)
    measurements = json['body']['measuregrps']
    
    thing = {'timestamp': [], **{t.name.lower(): [] for t in meastypes}}

    for i in measurements:
        thing['timestamp'].append(i['created'])
        for m in i['measures']:
            key = MeasureType(m['type']).name.lower()
            value = int(m['value'])
            unit = int(m['unit'])
            decimals = decimal_places(value, unit)
            scaled = value * (10 ** unit)
            rounded = round(scaled, decimals)
            thing[key].append(rounded)

    return thing


def send_email(email: Email) -> None:
    smtp_host = os.environ['SMTP_HOST']
    smtp_port = int(os.environ['SMTP_PORT']) if 'SMTP_PORT' in os.environ else DEFAULT_SMTP_PORT
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

if __name__ == '__main__':
    load_dotenv()

    client = WithingsClient()

    measurements = {
        'height': get_measurements(MeasureType.HEIGHT),
        'heart': get_measurements(MeasureType.HEART_PULSE),
        'weight': get_measurements(
            MeasureType.BASAL_METABOLIC_RATE,
            MeasureType.BONE_MASS,
            MeasureType.FAT_FREE_MASS,
            MeasureType.FAT_MASS_WEIGHT,
            MeasureType.FAT_RATIO,
            MeasureType.HYDRATION,
            MeasureType.METABOLIC_AGE,
            MeasureType.METABOLIC_AGE,
            MeasureType.MUSCLE_MASS,
            MeasureType.WEIGHT
        )
    }

    openai = OpenAI()

    response = openai.responses.parse(
        model='gpt-5.6',
        reasoning={'effort': 'medium'},
        background=True,
        max_output_tokens=20_000,
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
        if time.time() >= deadline:\
            raise TimeoutError('OpenAI background response timed out while polling for completion.')

        time.sleep(POLL_INTERVAL_SECONDS)
        response = openai.responses.retrieve(response.id)

    if response.status != 'completed':
        raise RuntimeError(f'OpenAI background response did not complete successfully: {response.status}')

    email = Email.model_validate_json(response.output_text)

    print(email.subject)
    print(email.content)
    send_email(email)

    