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


class Measurement(BaseModel):
    timestamp: int
    weight: float | None = None
    height: float | None = None
    fat_free_mass: float | None = None
    fat_ratio: float | None = None
    fat_mass_weight: float | None = None
    diastolic_blood_pressure: float | None = None
    systolic_blood_pressure: float | None = None
    heart_pulse: float | None = None
    temperature: float | None = None
    spo2: float | None = None
    body_temperature: float | None = None
    skin_temperature: float | None = None
    muscle_mass: float | None = None
    hydration: float | None = None
    bone_mass: float | None = None
    pulse_wave_velocity: float | None = None
    vo2_max: float | None = None
    vascular_age: float | None = None
    nerve_health_score_feet: float | None = None
    extracellular_water: float | None = None
    intracellular_water: float | None = None
    visceral_fat: float | None = None
    basal_metabolic_rate: float | None = None
    metabolic_age: float | None = None
    electrochemical_skin_conductance: float | None = None
    

    @staticmethod
    def _decimal_places(value: int, unit: int) -> int:
        if unit >= 0:
            return 0

        decimals = -unit
        abs_value = abs(value)
        removable = 0

        while removable < decimals and abs_value != 0 and abs_value % 10 == 0:
            abs_value //= 10
            removable += 1

        return decimals - removable

    @classmethod
    def from_json(cls, timestamp, measures):
        parsed = {'timestamp': timestamp}

        for m in measures:
            key = MeasureType(m['type']).name.lower()
            value = int(m['value'])
            unit = int(m['unit'])
            decimals = cls._decimal_places(value, unit)
            scaled = value * (10 ** unit)
            parsed[key] = round(scaled, decimals)

        return cls(**parsed)


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

    data = client.get_measurements(
        meastypes=list(MeasureType),
        category=1,
    )['body']['measuregrps']

    measurements = [Measurement.from_json(i['created'], i['measures']) for i in data]
    measurements_json = [measurement.model_dump() for measurement in measurements]

    openai = OpenAI()

    response = openai.responses.parse(
        model='gpt-5.6',
        reasoning={'effort': 'max'},
        background=True,
        instructions=("""
            Generate an html email exploring the user's weight loss progress from the data.
            Especially, focus on the last 7 days. But feel free to use all data to put the more recent trends into context.
            Perform your own analysis on the data, feel free to explore patterns using your own data analysis tools of choice.
            Include relevant graphs using inline.
            
            Start the email with evaluation how the user is doing, alongside a summary of key findings (numbers).
            Then, include analysis and figures to support the findings.
            Close the email with some motivational words.

            Use metric system for units.
        """),
        input=[{
            'role': 'user',
            'content': [{
                'type': 'input_text',
                'text': json.dumps(measurements_json),
            }],
        }],
        text_format=Email
    )

    deadline = time.time() + POLL_TIMEOUT_SECONDS
    while response.status in {'queued', 'in_progress'}:
        if time.time() >= deadline:
            raise TimeoutError('OpenAI background response timed out while polling for completion.')

        time.sleep(POLL_INTERVAL_SECONDS)
        response = openai.responses.retrieve(response.id)

    if response.status != 'completed':
        raise RuntimeError(f'OpenAI background response did not complete successfully: {response.status}')

    email = Email.model_validate_json(response.output_text)

    print(email.subject)
    print(email.content)
    send_email(email)

    