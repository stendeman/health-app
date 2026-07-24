# Health App

Health App is a small Python automation script that:

1. Reads body measurements from Withings.
2. Uses OpenAI to generate an HTML progress summary.
3. Sends that summary by email.

## Basic Use

1. Create and activate a virtual environment.
2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Create your env file:

   ```bash
   copy .env.example .env
   ```

4. Fill in all required values in `.env`.
5. Run:

   ```bash
   python run.py
   ```

The script prints the generated email subject/body and then sends the email.

## CLI Options

You can override OpenAI generation settings from the command line:

```bash
python run.py --reasoning medium --maxtokens 20000
```

Available options:

- `--reasoning`: `none`, `low`, `medium`, `high`, `xhigh`, `max`
- `--maxtokens`: integer token limit

Current defaults (from code):

- `--reasoning none`
- `--maxtokens 5000`

## What It Does

- Fetches these measurement types:
  - Weight
  - Fat ratio
  - Muscle mass
  - Bone mass
  - Visceral fat
- Prompts the OpenAI Responses API to produce an `Email` object.
- Sends the generated email through SMTP.

## Project Structure

- `run.py`: Top-level launcher script.
- `src/main.py`: Main application workflow. Fetches data, calls OpenAI, sends email.
- `src/measurements.py`: Fetching and converting Withings measurements.
- `requirements.txt`: Python dependencies.

## Requirements

- Python 3.10+
- A Withings account and API access (handled by `withings_client` package)
- OpenAI API key (paid API usage)
- SMTP credentials for sending email

## Environment Variables

Required by `src/main.py`:

- `OPENAI_API_KEY`
- `WITHINGS_CLIENT_ID`
- `WITHINGS_CLIENT_SECRET`
- `WITHINGS_REDIRECT_URI`
- `SMTP_HOST`
- `SMTP_PORT` (optional default in code is `587`)
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `EMAIL_FROM` (falls back to `SMTP_USERNAME` if omitted)
- `EMAIL_TO`

## Notes

- The app sends health-related data by email. Use trusted recipients and secure mailbox settings.
- Each run calls the OpenAI API and may incur cost.
- Consider adding logging and error handling around API/network failures for production use.
