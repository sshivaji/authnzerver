#!/usr/bin/env python
# -*- coding: utf-8 -*-
# actions_apikey.py - Waqas Bhatti (wbhatti@astro.princeton.edu) - Aug 2018
# License: MIT - see the LICENSE file for the full text.

'''This contains functions to drive API key related auth actions.

'''

#############
## LOGGING ##
#############

import logging
import json

# get a logger
LOGGER = logging.getLogger(__name__)


#############
## IMPORTS ##
#############

try:

    from datetime import datetime, timezone, timedelta
    utc = timezone.utc

except Exception:

    from datetime import datetime, timedelta, tzinfo
    ZERO = timedelta(0)

    class UTC(tzinfo):
        """UTC"""

        def utcoffset(self, dt):
            return ZERO

        def tzname(self, dt):
            return "UTC"

        def dst(self, dt):
            return ZERO

    utc = UTC()

import secrets
import multiprocessing as mp

from sqlalchemy import select

from .. import authdb
from .session import auth_session_exists


######################
## API KEY HANDLING ##
######################

def issue_new_apikey(payload,
                     raiseonfail=False,
                     override_authdb_path=None):
    '''This issues a new API key.

    payload must have the following keys:

    audience: the service this API key is being issued for
    subject: the specific API endpoint this API key is being issued for
    apiversion: the API version that the API key is valid for

    expires_days: the number of days after which the API key will expire
    not_valid_before: the amount of seconds after utcnow() when the API key
                      becomes valid

    user_id: the user ID of the user requesting the API key
    user_role: the user role of the user requesting the API key
    ip_address: the IP address to tie the API key to
    user_agent: the browser user agent requesting the API key
    session_token: the session token of the user requesting the API key

    API keys are tied to an IP address and client header combination. This will
    return an signed and encrypted Fernet API key that contains the user_id,
    random token, IP address, client header, and expiry date in ISO
    format. We'll then be able to use this info to verify the API key without
    hitting the database all the time.

    '''

    for key in ('user_id',
                'user_role',
                'expires_days',
                'not_valid_before',
                'audience',
                'subject',
                'ip_address',
                'user_agent',
                'session_token',
                'apiversion'):

        if key not in payload:
            return {
                'success':False,
                'apikey':None,
                'expires':None,
                'messages':["Some required keys are missing from payload."]
            }

    # this checks if the database connection is live
    currproc = mp.current_process()
    engine = getattr(currproc, 'authdb_engine', None)

    if override_authdb_path:
        currproc.auth_db_path = override_authdb_path

    if not engine:
        currproc.authdb_engine, currproc.authdb_conn, currproc.authdb_meta = (
            authdb.get_auth_db(
                currproc.auth_db_path,
                echo=raiseonfail
            )
        )

    # check the session
    session_info = auth_session_exists(
        {'session_token':payload['session_token']},
        raiseonfail=raiseonfail,
        override_authdb_path=override_authdb_path
    )

    if not session_info['success']:

        return {
            'success':False,
            'apikey':None,
            'expires':None,
            'messages':([
                "Invalid session token for password reset request."
            ])
        }

    session = session_info['session_info']

    # check if the session info matches what we have in the payload
    session_ok = (
        (session['user_id'] == payload['user_id']) and
        (session['ip_address'] == payload['ip_address']) and
        (session['user_agent'] == payload['user_agent']) and
        (session['user_role'] == payload['user_role'])
    )

    if not session_ok:

        return {
            'success':False,
            'apikey':None,
            'expires':None,
            'messages':([
                "DB session user_id, ip_address, user_agent, "
                "user_role does not match provided session info."
            ])
        }

    #
    # finally, generate the API key
    #
    random_token = secrets.token_urlsafe(32)

    # we'll return this API key dict to the frontend so it can JSON dump it,
    # encode to bytes, then encrypt, then sign it, and finally send back to the
    # client
    issued = datetime.utcnow()
    expires = datetime.utcnow() + timedelta(days=payload['expires_days'])

    notvalidbefore = (
        datetime.utcnow() +
        timedelta(seconds=payload['not_valid_before'])
    )

    apikey_dict = {
        'ver':payload['apiversion'],
        'uid':payload['user_id'],
        'rol':payload['user_role'],
        'clt':payload['user_agent'],
        'aud':payload['audience'],
        'sub':payload['subject'],
        'ipa':payload['ip_address'],
        'tkn':random_token,
        'iat':issued.isoformat(),
        'nbf':notvalidbefore.isoformat(),
        'exp':expires.isoformat()
    }
    apikey_json = json.dumps(apikey_dict)

    # we'll also store this dict in the apikeys table
    apikeys = currproc.authdb_meta.tables['apikeys']

    # NOTE: we store only the random token. this will later be checked for
    # equality against the value stored in the API key dict['tkn'] when we send
    # in this API key for verification later
    ins = apikeys.insert({
        'apikey':random_token,
        'issued':issued,
        'expires':expires,
        'not_valid_before':notvalidbefore,
        'user_id':payload['user_id'],
        'user_role':payload['user_role'],
        'session_token':payload['session_token'],
    })

    result = currproc.authdb_conn.execute(ins)
    result.close()

    #
    # return the API key to the frontend
    #
    messages = (
        "API key generated successfully for user_id = %s, expires: %s." %
        (payload['user_id'],
         expires.isoformat())
    )

    return {
        'success':True,
        'apikey':apikey_json,
        'expires':expires.isoformat(),
        'messages':([
            messages
        ])
    }


def verify_apikey(payload,
                  raiseonfail=False,
                  override_authdb_path=None):
    '''This checks if an API key is valid.

    payload requires the following keys:

    - apikey dict: the decrypted and verified API key info dict from frontend.

    '''
    if 'apikey_dict' not in payload:
        return {
            'success':False,
            'messages':["Some required keys are missing from payload."]
        }
    apikey_dict = payload['apikey_dict']

    # this checks if the database connection is live
    currproc = mp.current_process()
    engine = getattr(currproc, 'authdb_engine', None)

    if override_authdb_path:
        currproc.auth_db_path = override_authdb_path

    if not engine:
        currproc.authdb_engine, currproc.authdb_conn, currproc.authdb_meta = (
            authdb.get_auth_db(
                currproc.auth_db_path,
                echo=raiseonfail
            )
        )

    apikeys = currproc.authdb_meta.tables['apikeys']

    # the apikey sent to us must match the stored apikey's properties:
    # - token
    # - userid
    # - expired must be in the future
    # - issued must be in the past
    # - not_valid_before must be in the past
    sel = select([
        apikeys.c.apikey,
        apikeys.c.expires,
    ]).select_from(apikeys).where(
        apikeys.c.apikey == apikey_dict['tkn']
    ).where(
        apikeys.c.user_id == apikey_dict['uid']
    ).where(
        apikeys.c.user_role == apikey_dict['rol']
    ).where(
        apikeys.c.expires > datetime.utcnow()
    ).where(
        apikeys.c.issued < datetime.utcnow()
    ).where(
        apikeys.c.not_valid_before < datetime.utcnow()
    )
    result = currproc.authdb_conn.execute(sel)
    row = result.fetchone()
    result.close()

    if row is not None and len(row) != 0:

        return {
            'success':True,
            'messages':[(
                "API key verified successfully. Expires: %s." %
                row['expires'].isoformat()
            )]
        }

    else:

        return {
            'success':False,
            'messages':[(
                "API key could not be verified."
            )]
        }
