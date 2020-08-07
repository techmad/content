from datetime import datetime, timezone


class Message(object):
    @staticmethod
    def get_content_type():
        return 'multipart/alternative'


class MailObject(object):
    to = [('to mail 1', 'to@test1.com'), ('to mail 2', 'to@test2.com')]
    cc = [('cc mail 1', 'cc@test1.com')]
    bcc = []
    attachments = []
    from_ = [('from mail 1', 'from@test1.com')]
    text_html = ['html_text']
    text_plain = ['text_plain']
    subject = 'the mail subject'
    headers = {
        "Content-Type": "multipart/alternative; boundary=\"000000000000d30c9205abe4e97e\"",
        "Date": "Sun, 2 Aug 2020 16:22:16 +0300",
        "Delivered-To": "to@test1.com",
        "From": "from@test1.com",
        "MIME-Version": "1.0",
        "To": "to@test1.com",
    }
    body = 'body text'
    date = datetime.fromisoformat('2020-08-02T13:45:45.408520+00:00')
    message = Message


def test_convert_to_incident():
    from MailListenerV2 import Email
    email = Email(MailObject)
    incident = email.convert_to_incident()
    assert incident['attachment'] == []
    assert incident['occurred'] == email.date.isoformat()
    assert incident['details'] == email.text
    assert incident['name'] == email.subject


def test_generate_search_query():
    from MailListenerV2 import generate_search_query
    now = datetime.now(timezone.utc)
    permitted_from_addresses = ['test1@mail.com', 'test2@mail.com']
    permitted_from_domains = ['test1.com', 'domain2.com']
    assert generate_search_query(now, permitted_from_addresses, permitted_from_domains) == ['OR',
                                                                                            'OR',
                                                                                            'OR',
                                                                                            'FROM',
                                                                                            'test1@mail.com',
                                                                                            'FROM',
                                                                                            'test2@mail.com',
                                                                                            'FROM',
                                                                                            'test1.com',
                                                                                            'FROM',
                                                                                            'domain2.com',
                                                                                            'SINCE',
                                                                                            now]
