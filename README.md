# Health App

Small Python automation that:

1. Reads body measurements from Withings.
2. Uses OpenAI to generate a short progress summary.
3. Sends that summary as an email.

## What It Does

- Fetches these measurement types:
  - Weight
  - Fat ratio
  - Muscle mass
  - Bone mass
  - Visceral fat
- Converts measurement payloads into a typed `Measurement` model.
- Prompts the OpenAI Responses API to produce an `Email` object.
- Sends the generated email through SMTP.

## Project Structure

- `main.py`: Entry point. Fetches data, calls OpenAI, sends email.
- `measurement.py`: Pydantic model and parser for Withings measurements.
- `requirements.txt`: Python dependencies.

## Requirements

- Python 3.10+
- A Withings account and API access (handled by `withings_client` package)
- OpenAI API key
- SMTP credentials for sending email

## Setup

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create your env file from the template:

   ```bash
   copy .env.example .env
   ```

4. Fill in all values in `.env`.

## Environment Variables

Required by `main.py`:

- `OPENAI_API_KEY`
- `SMTP_HOST`
- `SMTP_PORT` (optional default in code is `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `EMAIL_FROM` (falls back to `SMTP_USERNAME` if omitted)
- `EMAIL_TO`

## Run

```bash
python main.py
```

The script prints the generated subject/content and sends the email.

## Notes

- The app sends health-related data by email. Use trusted recipients and secure mailbox settings.
- Consider adding logging and error handling around API/network failures for production use.
