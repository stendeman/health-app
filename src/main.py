import argparse
import json
import os
import re
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import make_msgid
from html import unescape
from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

from src.measurements import get_all_measurements


DEFAULT_SMTP_PORT = 587
POLL_INTERVAL_SECONDS = 1
POLL_TIMEOUT_SECONDS = 6000
DEFAULT_REASONING_EFFORT = 'none'
DEFAULT_MAX_OUTPUT_TOKENS = 20_000

CONTAINER_FILES_PAGE_SIZE = 100
LOCAL_CONTAINER_SCHEMES = {'', 'container', 'file', 'sandbox'}
SUPPORTED_IMAGE_SUFFIXES = {'.gif', '.jpeg', '.jpg', '.png', '.webp'}
IMAGE_SRC_PATTERN = re.compile(
    r'''(?P<prefix><img\b[^>]*?\s+src\s*=\s*)'''
    r'''(?:'''
    r'''(?P<quote>["'])(?P<quoted_src>.*?)(?P=quote)'''
    r'''|'''
    r'''(?P<unquoted_src>[^\s>]+)'''
    r''')''',
    flags=re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class ContainerFile:
    container_id: str
    file_id: str
    path: str
    created_at: int


@dataclass(frozen=True)
class InlineImage:
    content: bytes
    subtype: str
    cid: str
    filename: str


class Email(BaseModel):
    subject: str = Field(
        description='A concise subject describing the most important result.'
    )
    html: str = Field(
        description=(
            'Complete, email-safe HTML. Any figure generated with the Python '
            'tool must be included with a quoted img src that exactly matches '
            'its /mnt/data path.'
        )
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description='Generate and send health progress email.'
    )
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


def get_container_ids(response) -> list[str]:
    container_ids: list[str] = []

    for item in response.output:
        if getattr(item, 'type', None) != 'code_interpreter_call':
            continue

        container_id = getattr(item, 'container_id', None)
        if container_id and container_id not in container_ids:
            container_ids.append(container_id)

    if not container_ids:
        raise RuntimeError('The response contains no Code Interpreter call.')

    return container_ids


def list_container_files(client: OpenAI, response) -> list[ContainerFile]:
    container_files: list[ContainerFile] = []

    for container_id in get_container_ids(response):
        after: str | None = None

        while True:
            list_options = {
                'container_id': container_id,
                'limit': CONTAINER_FILES_PAGE_SIZE,
                'order': 'asc',
            }
            if after is not None:
                list_options['after'] = after

            page = client.containers.files.list(**list_options)
            for file in page.data:
                container_files.append(
                    ContainerFile(
                        container_id=container_id,
                        file_id=file.id,
                        path=file.path,
                        created_at=file.created_at,
                    )
                )

            if len(page.data) < CONTAINER_FILES_PAGE_SIZE:
                break

            next_after = page.data[-1].id
            if next_after == after:
                raise RuntimeError(
                    f'Container file pagination stalled for {container_id}.'
                )
            after = next_after

    return container_files


def normalize_container_path(value: str) -> str | None:
    value = unescape(value.strip())
    parsed = urlsplit(value)

    if parsed.scheme.lower() not in LOCAL_CONTAINER_SCHEMES:
        return None

    path = unquote(parsed.path)
    if path.startswith('mnt/data/'):
        path = f'/{path}'

    pure_path = PurePosixPath(path)
    if '..' in pure_path.parts:
        raise ValueError(f'Unsafe container image path in HTML: {value}')

    if pure_path.parts[:3] != ('/', 'mnt', 'data'):
        return None

    return pure_path.as_posix()


def detect_image_subtype(content: bytes, path: str) -> str:
    if content.startswith(b'\x89PNG\r\n\x1a\n'):
        return 'png'
    if content.startswith(b'\xff\xd8\xff'):
        return 'jpeg'
    if content.startswith((b'GIF87a', b'GIF89a')):
        return 'gif'
    if (
        len(content) >= 12
        and content.startswith(b'RIFF')
        and content[8:12] == b'WEBP'
    ):
        return 'webp'

    raise RuntimeError(
        f'HTML references a file that is not a supported raster image: {path}'
    )


def resolve_container_file(
    requested_path: str,
    container_files: list[ContainerFile],
) -> ContainerFile | None:
    exact_matches = [
        file
        for file in container_files
        if normalize_container_path(file.path) == requested_path
    ]
    if exact_matches:
        return max(exact_matches, key=lambda file: file.created_at)

    requested_name = PurePosixPath(requested_path).name
    basename_matches = [
        file
        for file in container_files
        if PurePosixPath(file.path).name == requested_name
    ]
    if len(basename_matches) == 1:
        return basename_matches[0]
    if len(basename_matches) > 1:
        raise RuntimeError(
            f'Container image path is ambiguous: {requested_path}'
        )

    return None


def embed_container_images(
    client: OpenAI,
    response,
    html: str,
) -> tuple[str, list[InlineImage]]:
    container_files = list_container_files(client, response)
    inline_images_by_file: dict[tuple[str, str], InlineImage] = {}
    unresolved_paths: set[str] = set()

    def replace_image_src(match: re.Match[str]) -> str:
        source = match.group('quoted_src')
        if source is None:
            source = match.group('unquoted_src')
        requested_path = normalize_container_path(source)
        if requested_path is None:
            return match.group(0)

        container_file = resolve_container_file(
            requested_path,
            container_files,
        )
        if container_file is None:
            unresolved_paths.add(requested_path)
            return match.group(0)

        file_key = (container_file.container_id, container_file.file_id)
        inline_image = inline_images_by_file.get(file_key)
        if inline_image is None:
            content = client.containers.files.content.retrieve(
                container_file.file_id,
                container_id=container_file.container_id,
            ).read()
            subtype = detect_image_subtype(content, container_file.path)
            inline_image = InlineImage(
                content=content,
                subtype=subtype,
                cid=make_msgid(),
                filename=PurePosixPath(container_file.path).name,
            )
            inline_images_by_file[file_key] = inline_image

        cid_source = f'cid:{inline_image.cid[1:-1]}'
        quote = match.group('quote')
        if quote:
            return f'{match.group("prefix")}{quote}{cid_source}{quote}'
        return f'{match.group("prefix")}"{cid_source}"'

    embedded_html = IMAGE_SRC_PATTERN.sub(replace_image_src, html)

    if unresolved_paths:
        available_images = sorted(
            file.path
            for file in container_files
            if PurePosixPath(file.path).suffix.lower()
            in SUPPORTED_IMAGE_SUFFIXES
        )
        raise RuntimeError(
            'The HTML references container images that were not found: '
            f'{sorted(unresolved_paths)}. '
            f'Available container images: {available_images or "none"}'
        )

    return embedded_html, list(inline_images_by_file.values())


def send_email(
    email: Email,
    embedded_html: str,
    inline_images: list[InlineImage],
) -> None:
    smtp_host = os.environ['SMTP_HOST']
    smtp_port = int(os.environ.get('SMTP_PORT', DEFAULT_SMTP_PORT))
    smtp_username = os.environ['SMTP_USERNAME']
    smtp_password = os.environ['SMTP_PASSWORD']
    email_from = os.environ.get('EMAIL_FROM', smtp_username)
    email_to = os.environ['EMAIL_TO']

    message = EmailMessage()
    message['Subject'] = email.subject
    message['From'] = email_from
    message['To'] = email_to
    message.set_content(
        'This message contains an HTML weight-progress report.'
    )
    message.add_alternative(embedded_html, subtype='html')

    html_part = message.get_payload()[-1]
    for image in inline_images:
        html_part.add_related(
            image.content,
            maintype='image',
            subtype=image.subtype,
            cid=image.cid,
            filename=image.filename,
            disposition='inline',
        )

    tls_context = ssl.create_default_context()
    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls(context=tls_context)
        server.login(smtp_username, smtp_password)
        server.send_message(message)


def wait_for_response(client: OpenAI, response):
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS

    while response.status in {'queued', 'in_progress'}:
        if time.monotonic() >= deadline:
            raise TimeoutError(
                'OpenAI background response timed out while polling for completion.'
            )

        time.sleep(POLL_INTERVAL_SECONDS)
        response = client.responses.retrieve(response.id)

    if response.status != 'completed':
        raise RuntimeError(
            'OpenAI background response did not complete successfully: '
            f'{response.status}'
        )

    return response


def main() -> None:
    args = parse_args()
    load_dotenv()

    measurements = get_all_measurements()
    client = OpenAI()

    response = client.responses.parse(
        model='gpt-5.6',
        reasoning={'effort': args.reasoning},
        background=True,
        max_output_tokens=args.maxtokens,
        text_format=Email,
        tools=[
            {
                'type': 'code_interpreter',
                'container': {
                    'type': 'auto',
                    'memory_limit': '4g',
                },
            }
        ],
        tool_choice='required',
        instructions="""
            Generate an HTML email analysing the user's weight-loss progress.

            Use the python tool to perform the data analysis. Focus especially
            on the last seven days, while using all available data to provide
            context.

            Independently determine which analyses and visualizations are useful.
            Prefer including at least one meaningful visualization when the available
            data supports it, but do not create misleading charts when there is
            insufficient data. You may include zero, one, or multiple figures.

            Return an Email object with a subject and complete email-safe HTML.
            For every final figure you decide to include:
            - Save it below /mnt/data with a unique, descriptive filename.
            - Prefer PNG; JPEG, GIF, and WebP are also supported.
            - Insert it at the relevant position in the HTML using a quoted
              <img src="/mnt/data/your_filename.png" alt="useful description">
              tag whose src exactly matches the saved file path.
            - Use inline CSS to make it responsive and email-safe.

            Do not include a generated figure unless its img tag is present in
            the HTML. Do not use Markdown images, external image URLs, data
            URLs, SVG, scripts, or visible download links. The application will
            download each referenced container image and embed it in the email.

            Start with an evaluation of how the user is doing and a numerical
            summary of the key findings. Then provide the analysis and place any
            figures beside the relevant discussion. Close with a short,
            encouraging message.

            Use metric units and Europe/Amsterdam local time.
        """,
        input=[
            {
                'role': 'user',
                'content': [
                    {
                        'type': 'input_text',
                        'text': json.dumps(measurements),
                    }
                ],
            }
        ],
    )

    response = wait_for_response(client, response)
    email = Email.model_validate_json(response.output_text)
    embedded_html, inline_images = embed_container_images(
        client,
        response,
        email.html,
    )

    print(email.subject)
    print(email.html)
    send_email(email, embedded_html, inline_images)


if __name__ == '__main__':
    main()
