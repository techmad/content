from typing import Dict, Any

from imapclient import IMAPClient
from imap_tools import OR
import mailparser
import demistomock as demisto
from CommonServerPython import *  # noqa: E402 lgtm [py/polluting-import]
import dateparser
from datetime import timezone

# CONSTS
INCLUDE_RAW_BODY = demisto.params().get('Include_raw_body', False)
PERMITTED_FROM_ADDRESSES = demisto.params().get('permittedFromAdd', '')
PERMITTED_FROM_DOMAINS = demisto.params().get('permittedFromDomain', '')
DELETE_PROCESSED = demisto.params().get("delete_processed", False)


class Email(object):
    def __init__(self, email_object):
        self.to = [mail_addresses for _, mail_addresses in email_object.to]
        self.cc = [mail_addresses for _, mail_addresses in email_object.cc]
        self.bcc = [mail_addresses for _, mail_addresses in email_object.bcc]
        self.attachments = email_object.attachments
        self.from_ = [mail_addresses for _, mail_addresses in email_object.from_][0]
        self.format = email_object.message.get_content_type()
        self.html = email_object.text_html[0] if email_object.text_html else ''
        self.text = email_object.text_plain[0] if email_object.text_plain else ''
        self.subject = email_object.subject
        self.headers = email_object.headers
        self.raw_body = email_object.body if INCLUDE_RAW_BODY else None
        # According to the mailparser documentation the datetime object is in utc
        self.date = email_object.date.replace(tzinfo=timezone.utc)
        self.raw_json = self.generate_raw_json()

    def parse_attachment(self):
        file_names = []
        for attachment in self.attachments:
            payload = attachment.get('payload')

            file_data = base64.b64decode(payload) if attachment.get('binary') else payload

            # save the attachment
            file_result = fileResult(attachment.get('filename'), file_data, attachment.get('mail_content_type'))

            # check for error
            if file_result['Type'] == entryTypes['error']:
                demisto.error(file_result['Contents'])
                raise Exception(file_result['Contents'])

            file_names.append({
                'path': file_result['FileID'],
                'name': attachment.get('filename')
            })
        return file_names

    def convert_to_incident(self) -> Dict[str, Any]:
        """
        Convert an Email class instance to a demisto incident
        Returns:
            A dict with all relevant fields for an incident
        """
        return {
            'occurred': self.date.isoformat(),
            'created': datetime.now(timezone.utc).isoformat(),
            'details': self.text or self.html,
            'name': self.subject,
            'attachment': self.parse_attachment(),
            'rawJSON': json.dumps(self.raw_json)
        }

    def generate_raw_json(self):
        raw_json = {
            'to': self.to,
            'cc': self.cc,
            'from': self.from_,
            'format': self.format,
            'text': self.text,
            'subject': self.subject,
            'attachments': ','.join([attachment['filename'] for attachment in self.attachments]),
            'rawHeaders': self.headers
        }
        if self.html:
            raw_json['html'] = self.html
        if self.raw_body:
            raw_json['rawBody'] = self.raw_body
        return raw_json


def fetch_incidents(client,
                    last_run,
                    first_fetch_time):
    """
    This function will execute each interval (default is 1 minute).

    Args:
        client (Client): HelloWorld client
        last_run (dateparser.time): The greatest incident created_time we fetched from last fetch
        first_fetch_time (dateparser.time): If last_run is None then fetch all incidents since first_fetch_time

    Returns:
        next_run: This will be last_run in the next fetch-incidents
        incidents: Incidents that will be created in Demisto
    """
    # Get the last fetch time, if exists
    last_fetch = last_run.get('last_fetch')

    # Handle first time fetch
    if last_fetch is None:
        latest_created_time = dateparser.parse(f'{first_fetch_time} UTC')
    else:
        latest_created_time = datetime.fromisoformat(last_fetch)
    messages_query = generate_search_query(latest_created_time, PERMITTED_FROM_ADDRESSES, PERMITTED_FROM_DOMAINS)
    messages = client.search(messages_query)
    messages = messages[:50]
    mails_fetched = []
    for uid, message_data in client.fetch(messages, 'RFC822').items():
        message_bytes = message_data.get(b'RFC822')
        if not message_bytes:
            continue
        email_message = mailparser.parse_from_bytes(message_bytes)
        # The search query filters emails by day, not by exact date
        email_message_object = Email(email_message)
        if email_message_object.date > latest_created_time:
            mails_fetched.append(email_message_object)
    if mails_fetched:
        latest_created_time = max(mails_fetched, key=lambda x: x.date).date
    incidents = [mail.convert_to_incident() for mail in mails_fetched]
    next_run = {'last_fetch': latest_created_time.isoformat()}
    if DELETE_PROCESSED:
        client.delete_messages(messages)
    return next_run, incidents


def generate_search_query(latest_created_time, permitted_from_addresses, permitted_from_domains):
    permitted_from_addresses_list = argToList(permitted_from_addresses)
    permitted_from_domains_list = argToList(permitted_from_domains)
    messages_query = ''
    if permitted_from_addresses_list + permitted_from_domains_list:
        messages_query = OR(from_=permitted_from_addresses_list + permitted_from_domains_list).format()
        # Removing Parenthesis and quotes
        messages_query = messages_query.strip('()').replace('"', '')
        # Creating a list of the OR query words
    messages_query = messages_query.split()
    messages_query = messages_query + ['SINCE', latest_created_time]
    return messages_query


def test_module(client: IMAPClient) -> str:
    client.search()
    return 'ok'


def main():
    """
        PARSE AND VALIDATE INTEGRATION PARAMS
    """
    params = demisto.params()
    mail_server_url = params.get('MailServerURL')
    port = int(params.get('port'))
    folder = params.get('folder')
    username = demisto.params().get('credentials').get('identifier')
    password = demisto.params().get('credentials').get('password')
    verify_ssl = not params.get("insecure", False)

    first_fetch_time = demisto.params().get('fetch_time', '3 days').strip()

    LOG(f'Command being called is {demisto.command()}')
    try:
        with IMAPClient(mail_server_url, ssl=verify_ssl, timeout=20, port=port) as client:
            client.login(username, password)
            client.select_folder(folder)
            if demisto.command() == 'test-module':
                # This is the call made when pressing the integration Test button.
                result = test_module(client)
                demisto.results(result)

            elif demisto.command() == 'fetch-incidents':
                # Set and define the fetch incidents command to run after activated via integration settings.
                next_run, incidents = fetch_incidents(
                    client=client,
                    last_run=demisto.getLastRun(),
                    first_fetch_time=first_fetch_time)

                demisto.setLastRun(next_run)
                demisto.incidents(incidents)
    # Log exceptions
    except Exception as e:
        LOG(e)
        return_error(f'Failed to execute {demisto.command()} command. Error: {str(e)}')


if __name__ in ('__main__', '__builtin__', 'builtins'):
    main()
