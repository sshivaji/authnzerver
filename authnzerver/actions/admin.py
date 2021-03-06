#!/usr/bin/env python
# -*- coding: utf-8 -*-
# actions_admin.py - Waqas Bhatti (wbhatti@astro.princeton.edu) - Aug 2018
# License: MIT - see the LICENSE file for the full text.

'''This contains functions to drive admin related actions (listing users,
editing users, change user roles).

'''

#############
## LOGGING ##
#############

import logging

# get a logger
LOGGER = logging.getLogger(__name__)


#############
## IMPORTS ##
#############

import multiprocessing as mp

from sqlalchemy import select, asc

from .. import authdb
from .session import auth_session_exists


##################
## LISTING USERS ##
###################

def list_users(payload,
               raiseonfail=False,
               override_authdb_path=None):
    '''
    This lists users.

    Parameters
    ----------

    payload : dict
        This is the input payload dict. Required items:

        - user_id: int or None. If None, all users will be returned

    raiseonfail : bool
        If True, will raise an Exception if something goes wrong.

    override_authdb_path : str or None
        If given as a str, is the alternative path to the auth DB.

    Returns
    -------

    dict
        The dict returned is of the form::

            {'success': True or False,
             'user_info': list of dicts, one per user,
             'messages': list of str messages if any}

        The dicts per user will contain the following items::

            {'user_id','full_name', 'email',
             'is_active','created_on','user_role',
             'last_login_try','last_login_success'}

    '''

    if 'user_id' not in payload:
        LOGGER.error('no user_id provided')

        return {
            'success':False,
            'user_info':None,
            'messages':["No user_id provided."],
        }

    user_id = payload['user_id']

    try:

        # this checks if the database connection is live
        currproc = mp.current_process()
        engine = getattr(currproc, 'authdb_engine', None)

        if override_authdb_path:
            currproc.auth_db_path = override_authdb_path

        if not engine:
            (currproc.authdb_engine,
             currproc.authdb_conn,
             currproc.authdb_meta) = (
                authdb.get_auth_db(
                    currproc.auth_db_path,
                    echo=raiseonfail
                )
            )

        users = currproc.authdb_meta.tables['users']

        if user_id is None:

            s = select([
                users.c.user_id,
                users.c.full_name,
                users.c.email,
                users.c.is_active,
                users.c.last_login_try,
                users.c.last_login_success,
                users.c.created_on,
                users.c.user_role,
            ]).order_by(asc(users.c.user_id)).select_from(users)

        else:

            s = select([
                users.c.user_id,
                users.c.full_name,
                users.c.email,
                users.c.is_active,
                users.c.last_login_try,
                users.c.last_login_success,
                users.c.created_on,
                users.c.user_role,
            ]).order_by(asc(users.c.user_id)).select_from(users).where(
                users.c.user_id == user_id
            )

        result = currproc.authdb_conn.execute(s)
        rows = result.fetchall()
        result.close()

        try:

            serialized_result = [dict(x) for x in rows]

            return {
                'success':True,
                'user_info':serialized_result,
                'messages':["User look up successful."],
            }

        except Exception:

            if raiseonfail:
                raise

            return {
                'success':False,
                'user_info':None,
                'messages':["User look up failed."],
            }

    except Exception:

        if raiseonfail:
            raise

        LOGGER.warning('user info not found or '
                       'could not check if it exists')

        return {
            'success':False,
            'user_info':None,
            'messages':["User look up failed."],
        }


###################
## EDITING USERS ##
###################

def edit_user(payload,
              raiseonfail=False,
              override_authdb_path=None):
    '''This edits users.

    Parameters
    ----------

    payload : dict
        This is the input payload dict. Required items:

        - user_id: int, user ID of an admin user or == target_userid
        - user_role: str, == 'superuser' or == target_userid user_role
        - session_token: str, session token of admin or target_userid token
        - target_userid: int, the user to edit
        - update_dict: dict, the update dict

        Only these items can be edited::

            {'full_name', 'email',     <- by user and superuser
             'is_active','user_role', 'email_verified'}  <- by superuser only

        User IDs 2 and 3 are reserved for the system-wide anonymous and locked
        users respectively, and can't be edited.

    raiseonfail : bool
        If True, will raise an Exception if something goes wrong.

    override_authdb_path : str or None
        If given as a str, is the alternative path to the auth DB.

    Returns
    -------

    dict
        The dict returned is of the form::

            {'success': True or False,
             'user_info': dict, with new user info,
             'messages': list of str messages if any}

    '''

    for key in ('user_id',
                'user_role',
                'session_token',
                'target_userid',
                'update_dict'):

        if key not in payload:

            LOGGER.error('no %s provided for edit_user' % key)
            return {
                'success':False,
                'user_info':None,
                'messages':["No %s provided." % key],
            }

    user_id = payload['user_id']
    user_role = payload['user_role']
    session_token = payload['session_token']
    target_userid = payload['target_userid']
    update_dict = payload['update_dict']

    if not isinstance(update_dict, dict):
        LOGGER.error('no update_dict provided for edit_user' % key)
        return {
            'success':False,
            'user_info':None,
            'messages':["No update_dict provided."],
        }

    if target_userid in (2,3):

        LOGGER.error('Editing anonymous/locked user accounts not allowed')
        return {
            'success':False,
            'user_info':None,
            'messages':["Editing anonymous/locked user accounts not allowed."],
        }

    try:

        # this checks if the database connection is live
        currproc = mp.current_process()
        engine = getattr(currproc, 'authdb_engine', None)

        if override_authdb_path:
            currproc.auth_db_path = override_authdb_path

        if not engine:
            (currproc.authdb_engine,
             currproc.authdb_conn,
             currproc.authdb_meta) = (
                authdb.get_auth_db(
                    currproc.auth_db_path,
                    echo=raiseonfail
                )
            )

        # the case where the user updates their own info
        if target_userid == user_id and user_role in ('authenticated','staff'):

            # check if the user_id == target_userid
            # if so, check if session_token is valid and belongs to user_id
            session_info = auth_session_exists(
                {'session_token':session_token},
                raiseonfail=raiseonfail,
                override_authdb_path=override_authdb_path
            )

            # check if the session info user_id matches the provided user_id and
            # role
            if (session_info and
                session_info['success'] and
                session_info['session_info']['is_active'] is True and
                session_info['session_info']['user_id'] == user_id and
                session_info['session_info']['user_role'] == user_role):

                editeable_elements = {'full_name','email'}
                update_check = set(update_dict.keys()) - editeable_elements

                # check if the update keys are valid
                if len(update_check) > 0:

                    LOGGER.warning('extra elements in update_dict not allowed')
                    return {
                        'success':False,
                        'user_info':None,
                        'messages':["extra elements in "
                                    "update_dict not allowed"],
                    }

            else:

                LOGGER.warning('no existing user matching session '
                               'for user edit attempt')
                return {
                    'success':False,
                    'user_info':None,
                    'messages':["User session info not available "
                                "for this user edit attempt."],
                }

        # the case where the superuser updates a user's info (or their own info)
        elif user_role == 'superuser':

            # check if the user_id == target_userid
            # if so, check if session_token is valid and belongs to user_id
            session_info = auth_session_exists(
                {'session_token':session_token},
                raiseonfail=raiseonfail,
                override_authdb_path=override_authdb_path
            )

            # check if the session info user_id matches the provided user_id and
            # role
            if (session_info and
                session_info['success'] and
                session_info['session_info']['is_active'] is True and
                session_info['session_info']['user_id'] == user_id and
                session_info['session_info']['user_role'] == user_role):

                editeable_elements = {'full_name','email',
                                      'is_active','user_role',
                                      'email_verified'}
                update_check = set(update_dict.keys()) - editeable_elements

                # check if the update keys are valid
                if len(update_check) > 0:
                    LOGGER.warning('extra elements in update_dict not allowed')
                    return {
                        'success':False,
                        'user_info':None,
                        'messages':["extra elements in "
                                    "update_dict not allowed"],
                    }

                # check if the roles provided are valid
                if ('user_role' in update_dict and
                    (update_dict['user_role'] not in
                     ('superuser','staff','authenticated','locked'))):

                    LOGGER.warning('unknown role change request in update_dict')
                    return {
                        'success':False,
                        'user_info':None,
                        'messages':["unknown role change "
                                    "request in update_dict"],
                    }

            else:

                LOGGER.warning('no existing superuser matching session '
                               'for user edit attempt')
                return {
                    'success':False,
                    'user_info':None,
                    'messages':["Superuser session info not available "
                                "for this user edit attempt."],
                }

        # any other case is a failure
        else:

            LOGGER.warning('no existing matching session or user_id'
                           'for user edit attempt')
            return {
                'success':False,
                'user_info':None,
                'messages':["user_id or session info not available "
                            "for this user edit attempt."],
            }

        #
        # all update checks, passed, do the update
        #

        users = currproc.authdb_meta.tables['users']

        # execute the update
        upd = users.update(
        ).where(
            users.c.user_id == target_userid
        ).values(update_dict)
        result = currproc.authdb_conn.execute(upd)

        # check the update and return new values
        sel = select([
            users.c.user_id,
            users.c.user_role,
            users.c.full_name,
            users.c.email,
            users.c.is_active
        ]).select_from(users).where(
            users.c.user_id == target_userid
        )
        result = currproc.authdb_conn.execute(sel)
        rows = result.fetchone()
        result.close()

        try:

            serialized_result = dict(rows)

            return {
                'success':True,
                'user_info':serialized_result,
                'messages':["User update successful."],
            }

        except Exception:

            if raiseonfail:
                raise

            return {
                'success':False,
                'user_info':None,
                'messages':["User update failed."],
            }

    except Exception:

        if raiseonfail:
            raise

        LOGGER.error('user update not found or '
                     'could not check if it exists')

        return {
            'success':False,
            'user_info':None,
            'messages':["User update failed."],
        }


def internal_toggle_user_lock(payload,
                              raiseonfail=False,
                              override_authdb_path=None):
    '''This locks/unlocks user accounts. Can only be run internally.

    The use-case is automatically locking user accounts if there are too many
    incorrect password attempts. The lock can be permanent or temporary.

    Parameters
    ----------

    payload : dict
        This is the input payload dict. Required items:

        - target_userid: int, the user to lock/unlock
        - action: str {'unlock','lock'}

    raiseonfail : bool
        If True, will raise an Exception if something goes wrong.

    override_authdb_path : str or None
        If given as a str, is the alternative path to the auth DB.

    Returns
    -------

    dict
        The dict returned is of the form::

            {'success': True or False,
             'user_info': dict, with new user info,
             'messages': list of str messages if any}

    '''

    from .session import auth_delete_sessions_userid

    for key in ('target_userid',
                'action'):

        if key not in payload:

            LOGGER.error('no %s provided for toggle_user_lock' % key)
            return {
                'success':False,
                'user_info':None,
                'messages':["No %s provided for toggle_user_lock" % key],
            }

    target_userid = payload['target_userid']
    action = payload['action']

    if action not in ('unlock','lock'):
        LOGGER.error('Unknown action requested for toggle_user_lock')
        return {
            'success':False,
            'user_info':None,
            'messages':["Unknown action requested for toggle_user_lock."],
        }

    if target_userid in (2,3):

        LOGGER.error('Editing anonymous/locked user accounts not allowed')
        return {
            'success':False,
            'user_info':None,
            'messages':["Editing anonymous/locked user accounts not allowed."],
        }

    try:

        # this checks if the database connection is live
        currproc = mp.current_process()
        engine = getattr(currproc, 'authdb_engine', None)

        if override_authdb_path:
            currproc.auth_db_path = override_authdb_path

        if not engine:
            (currproc.authdb_engine,
             currproc.authdb_conn,
             currproc.authdb_meta) = (
                authdb.get_auth_db(
                    currproc.auth_db_path,
                    echo=raiseonfail
                )
            )

        #
        # all update checks, passed, do the update
        #

        users = currproc.authdb_meta.tables['users']

        if payload['action'] == 'lock':
            update_dict = {'is_active': False,
                           'user_role': 'locked'}
        elif payload['action'] == 'unlock':
            update_dict = {'is_active': True,
                           'user_role': 'authenticated'}

        # execute the update
        upd = users.update(
        ).where(
            users.c.user_id == target_userid
        ).values(update_dict)
        result = currproc.authdb_conn.execute(upd)

        # check the update and return new values
        sel = select([
            users.c.user_id,
            users.c.user_role,
            users.c.full_name,
            users.c.email,
            users.c.is_active
        ]).select_from(users).where(
            users.c.user_id == target_userid
        )
        result = currproc.authdb_conn.execute(sel)
        rows = result.fetchone()
        result.close()

        # delete all the sessions belonging to this user if the action to
        # perform is 'lock'
        if payload['action'] == 'lock':

            auth_delete_sessions_userid(
                {'user_id':target_userid,
                 'session_token':None,
                 'keep_current_session':False},
                raiseonfail=raiseonfail,
                override_authdb_path=override_authdb_path
            )

        try:

            serialized_result = dict(rows)

            return {
                'success':True,
                'user_info':serialized_result,
                'messages':["User lock toggle successful."],
            }

        except Exception:

            if raiseonfail:
                raise

            return {
                'success':False,
                'user_info':None,
                'messages':["User lock toggle failed."],
            }

    except Exception:

        if raiseonfail:
            raise

        LOGGER.error('User lock toggle not found or '
                     'could not check if it exists')

        return {
            'success':False,
            'user_info':None,
            'messages':["User lock toggle failed."],
        }


def toggle_user_lock(payload,
                     raiseonfail=False,
                     override_authdb_path=None):
    '''This locks/unlocks user accounts. Can only be run by superusers.

    Parameters
    ----------

    payload : dict
        This is the input payload dict. Required items:

        - user_id: int, user ID of a superuser
        - user_role: str, == 'superuser'
        - session_token: str, session token of superuser
        - target_userid: int, the user to lock/unlock
        - action: str {'unlock','lock'}

    raiseonfail : bool
        If True, will raise an Exception if something goes wrong.

    override_authdb_path : str or None
        If given as a str, is the alternative path to the auth DB.

    Returns
    -------

    dict
        The dict returned is of the form::

            {'success': True or False,
             'user_info': dict, with new user info,
             'messages': list of str messages if any}

    '''

    for key in ('user_id',
                'user_role',
                'session_token',
                'target_userid',
                'action'):

        if key not in payload:

            LOGGER.error('no %s provided for toggle_user_lock' % key)
            return {
                'success':False,
                'user_info':None,
                'messages':["No %s provided for toggle_user_lock" % key],
            }

    user_id = payload['user_id']
    user_role = payload['user_role']
    session_token = payload['session_token']
    target_userid = payload['target_userid']
    action = payload['action']

    if action not in ('unlock','lock'):
        LOGGER.error('Unknown action requested for toggle_user_lock')
        return {
            'success':False,
            'user_info':None,
            'messages':["Unknown action requested for toggle_user_lock."],
        }

    if target_userid in (2,3):

        LOGGER.error('Editing anonymous/locked user accounts not allowed')
        return {
            'success':False,
            'user_info':None,
            'messages':["Editing anonymous/locked user accounts not allowed."],
        }

    try:

        # this checks if the database connection is live
        currproc = mp.current_process()
        engine = getattr(currproc, 'authdb_engine', None)

        if override_authdb_path:
            currproc.auth_db_path = override_authdb_path

        if not engine:
            (currproc.authdb_engine,
             currproc.authdb_conn,
             currproc.authdb_meta) = (
                authdb.get_auth_db(
                    currproc.auth_db_path,
                    echo=raiseonfail
                )
            )

        # the case where the superuser updates a user's info (or their own info)
        if user_role == 'superuser':

            # check if the user_id == target_userid
            # if so, check if session_token is valid and belongs to user_id
            session_info = auth_session_exists(
                {'session_token':session_token},
                raiseonfail=raiseonfail,
                override_authdb_path=override_authdb_path
            )

            # check if the session info user_id matches the provided user_id and
            # role
            if (session_info and
                session_info['success'] and
                session_info['session_info']['is_active'] is True and
                session_info['session_info']['user_id'] == user_id and
                session_info['session_info']['user_role'] == user_role):

                update_ok = True

            else:
                update_ok = False

                LOGGER.warning('no existing superuser matching session '
                               'for user edit attempt')
                return {
                    'success':False,
                    'user_info':None,
                    'messages':["Superuser session info not available "
                                "for this user edit attempt."],
                }

            if not update_ok:

                return {
                    'success':False,
                    'user_info':None,
                    'messages':["Superuser session info not available "
                                "for this user edit attempt."],
                }

        # any other case is a failure
        else:

            LOGGER.warning('no existing matching session or user_id'
                           'for user lock toggle attempt')
            return {
                'success':False,
                'user_info':None,
                'messages':["user_id or session info not available "
                            "for this user lock toggle attempt."],
            }

        #
        # all update checks passed, do the update
        #
        res = internal_toggle_user_lock(
            payload,
            raiseonfail=raiseonfail,
            override_authdb_path=override_authdb_path
        )
        return res

    except Exception:

        if raiseonfail:
            raise

        LOGGER.error('User lock toggle not found or '
                     'could not check if it exists')

        return {
            'success':False,
            'user_info':None,
            'messages':["User lock toggle failed."],
        }
