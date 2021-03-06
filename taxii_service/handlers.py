import pytz
from datetime import datetime
from dateutil.parser import parse
from dateutil.tz import tzutc
from StringIO import StringIO
from M2Crypto import BIO, SMIME

import libtaxii as t
import libtaxii.clients as tc
import libtaxii.messages as tm

from django.conf import settings

from . import taxii
from crits.indicators.indicator import Indicator
from crits.standards.parsers import STIXParser
from crits.standards.handlers import import_standards_doc
from crits.service_env import manager

def execute_taxii_agent(hostname=None, feed=None, keyfile=None, certfile=None, start=None, end=None, analyst=None, method=None):
    ret = {
            'events': [],
            'samples': [],
            'emails': [],
            'indicators': [],
            'successes': 0,
            'failures': 0,
            'status': False,
            'reason': ''
          }

    sc = manager.get_config('taxii_service')
    # XXX: Validate these!
    if not hostname:
        hostname = str(sc['hostname'])
    if not keyfile:
        keyfile = str(sc['keyfile'])
    if not certfile:
        certfile = str(sc['certfile'])
    if not feed:
        feed = str(sc['data_feed'])

    # Last document's end time is our start time.
    if not start:
        last = taxii.Taxii.get_last()
        if last:
            start = pytz.utc.localize(last.end)

    # If start is a string, convert it to a datetime
    # YYYY-MM-DD HH:MM:SS
    if isinstance(start, str):
        start = pytz.utc.localize(parse(start, fuzzy=True))

    # store the current time as the time of this request
    runtime = datetime.now(tzutc())

    # End time is always now, unless specified.
    if not end:
        end = runtime

    # If end is a string, convert it to a datetime
    # YYYY-MM-DD HH:MM:SS
    if isinstance(end, str):
        end = pytz.utc.localize(parse(end, fuzzy=True))

    # compare start and end to make sure:
    # 1) start time is before end time
    # 2) end time is not in the future
    if (start != None and start >= end) and end > runtime:
        ret['reason'] = "Bad timestamp(s)"
        return ret 

    client = tc.HttpClient()
    client.setUseHttps(True)
    client.setAuthType(tc.HttpClient.AUTH_CERT)
    client.setAuthCredentials({'key_file': keyfile, 'cert_file': certfile})

    if settings.HTTP_PROXY:
        proxy = settings.HTTP_PROXY
        if not proxy.startswith('http://'):
            proxy = 'http://' + proxy
        client.setProxy(proxy, proxy_type=tc.HttpClient.PROXY_HTTPS)

    crits_taxii = taxii.Taxii()
    crits_taxii.runtime = runtime
    crits_taxii.end = end

    poll_msg = tm.PollRequest(message_id=tm.generate_message_id(),
                              feed_name=feed,
                              exclusive_begin_timestamp_label=start,
                              inclusive_end_timestamp_label=end)
    response = client.callTaxiiService2(hostname, '/poll/', t.VID_TAXII_XML_10,
                                        poll_msg.to_xml())

    if response.getcode() != 200:
        ret['reason'] = "Response is not 200 OK"
        return ret

    taxii_msg = t.get_message_from_http_response(response, poll_msg.message_id)

    valid = tm.validate_xml(taxii_msg.to_xml())
    if valid != True:
        ret['reason'] = valid
        return ret

    if taxii_msg.message_type != tm.MSG_POLL_RESPONSE:
        ret['reason'] = "No poll response"
        return ret

    ret['status'] = True

    if not taxii_msg.content_blocks:
        crits_taxii.save()
        return ret

    mid = taxii_msg.message_id
    for content_block in taxii_msg.content_blocks:
        data = parse_content_block(content_block, keyfile, certfile)
        if not data:
            ret['failures'] += 1
            continue

        objs = import_standards_doc(data, analyst, method, ref=mid, make_event=True)

        ret['successes'] += 1

        for k in ["events", "samples", "emails", "indicators"]:
            for i in objs[k]:
                ret[k].append(i)

    crits_taxii.save()
    return ret

def parse_content_block(content_block, privkey=None, pubkey=None):
    if content_block.content_binding == 'SMIME':
        if not privkey and not pubkey:
            return None

        inbuf = BIO.MemoryBuffer(StringIO(content_block.content).read())
        s = SMIME.SMIME()
        try:
            s.load_key(privkey, pubkey)
            p7, data = SMIME.smime_load_pkcs7_bio(inbuf)
            buf = s.decrypt(p7)
        except SMIME.PKCS7_Error:
            return None
        f = StringIO(buf)
        new_block = f.read()
        f.close()
        return parse_content_block(tm.ContentBlock.from_xml(new_block), privkey, pubkey)
    elif content_block.content_binding == t.CB_STIX_XML_10:
        f = StringIO(content_block.content)
        data = f.read()
        f.close()
        return data
    else:
        return None
