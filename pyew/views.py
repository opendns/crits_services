import json

from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import HttpResponse
from django.utils.crypto import get_random_string

from crits.core.user import CRITsUser
from crits.core.user_tools import user_can_view_data
from crits.service_env import manager

@user_passes_test(user_can_view_data)
def pyew_port(request):

    sc = manager.get_config('Pyew')
    port = str(sc['port'])
    secure = str(sc['secure'])
    data = {'port': port,
            'secure': secure}
    return HttpResponse(json.dumps(data), mimetype="application/json")

@user_passes_test(user_can_view_data)
def pyew_tokenize(request):

    user = CRITsUser.objects(username=request.user.username).first()
    if not user:
        data = {'token': None}
    allowed_chars = ('abcdefghijklmnopqrstuvwxyz'
                     'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789')
    token = get_random_string(128, allowed_chars=allowed_chars)
    user.pyew_token = token
    try:
        user.save()
        data = {'token': token}
    except:
        data = {'token': None}
    return HttpResponse(json.dumps(data), mimetype="application/json")
