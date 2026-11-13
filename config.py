"""Run configuration. Defaults match the existing automation."""
import re
from urllib.parse import urlparse

CREDENTIALS_FILE = "credentials.json"
SPREADSHEET_URL = "https://docs.google.com/spreadsheets/d/1ZmU9BO7uX8BDpOrdEylbhnNmxUSuZjm7rlsWlNk5LwI/edit?pli=1&gid=0#gid=0"
SEARCH_PAGE_URL = "https://affiliate.tiktok.com/affiliate/creator"


def resolve_spreadsheet_url(value=None):
    """An empty override uses config; accept only a standard native Google Sheets URL."""
    url = (value or '').strip() or SPREADSHEET_URL
    parsed = urlparse(url)
    if (parsed.scheme != 'https' or parsed.netloc != 'docs.google.com'
            or re.search(r'\s', url)
            or not re.fullmatch(r'/spreadsheets/d/[A-Za-z0-9_-]+(?:/(?:edit|view|copy|preview|htmlview))?/?', parsed.path)):
        raise ValueError('Link phải có dạng https://docs.google.com/spreadsheets/d/<ID>/edit')
    return url


def spreadsheet_id_from_url(value=None):
    return urlparse(resolve_spreadsheet_url(value)).path.split('/')[3]
