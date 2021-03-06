# Copyright 2008 Online Agility (www.onlineagility.com)
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.
import logging
import requests

from datetime import tzinfo, timedelta

# python 2.5+ has ElementTree included in it's core
try:
    from xml.etree import ElementTree
    from xml.etree.ElementTree import Element, SubElement
except ImportError:
    from elementtree import ElementTree
    from elementtree.ElementTree import Element, SubElement

from dateutil.parser import parse


def json_to_obj(json_data):
    if isinstance(json_data, list):
        json_data = [json_to_obj(x) for x in json_data]
    if not isinstance(json_data, dict):
        return json_data

    class Object(object):
        def __repr__(self):
            return 'icontact.client.Object(%s)' % repr(self.__dict__)

    o = Object()
    for k in json_data:
        o.__dict__[k] = json_to_obj(json_data[k])
    return o


class IContactServerError(Exception):
    def __init__(self, http_status, errors):
        self.http_status = http_status
        self.errors = errors

    def __str__(self):
        return '%s: %s' % (self.http_status, '\n'.join(self.errors))


class IContactClient(object):
    """Perform operations on the iContact API."""

    ICONTACT_API_URL = 'https://app.icontact.com/icp/'
    ICONTACT_SANDBOX_API_URL = 'https://app.sandbox.icontact.com/icp/'
    NAMESPACE = 'http://www.w3.org/1999/xlink'

    def __init__(self, api_key, username, password, auth_handler=None,
                 account_id=None, client_folder_id=None,
                 url=ICONTACT_API_URL, api_version='2.2', log_enabled=False):
        """
        - api_key: the API Key assigned for the OA iContact client
        - username: the iContact web site login username
        - password:
          This is the password registered for the API client, also known
          as the "API Application Password". It is *not* the standard
          web site login password.
        - auth_handler: (Optional) An object that implements two callback
          methods that this client will invoke when it generates, or
          requires, authentication credentials. The authentication handler
          object can be used to easily share credentials among multiple
          IContactClient instances.

        The authentication handler object must implement credential
        getter and setter methods::
          get_credentials() => (token,sequence)
          set_credentials(token,sequence)
        """
        self.api_key = api_key
        self.api_version = api_version
        self.username = username
        self.password = password
        self.auth_handler = auth_handler

        self.account_id = account_id
        self.client_folder_id = client_folder_id

        self.url = url

        self.log = logging.getLogger('icontact')
        self.log_enabled = log_enabled

    def _get_account_id(self):
        self.account_id = self.account().accountId
        return self.account_id

    def _get_client_folder_id(self):
        self.client_folder_id = self.clientfolder(self.account_id).clientFolderId
        return self.client_folder_id

    def _perform_request(self, method, url, **kwargs):
        return requests.request(method.upper(), url, **kwargs)

    def _do_request(self, call_path, parameters=None, method='get', response_type='json', params_as_json=False):
        """
        Performs an API request and returns the resultant json object.
        If type='xml' is passed in, returns XML document as an
        xml.etree.ElementTree node. An Exception is thrown if the operation
        results in an error response from iContact, or if there is no
        authentication information available (ie login has not been called)

        This method does all the hard work for API operations: building the
        URL path; adding auth headers; sending the request to iContact;
        evaluating the response; and parsing the response to an XML node.
        """
        if parameters is None:
            parameters = {}

        url = '%s%s' % (self.url, call_path)

        type_header = 'text/xml' if response_type == 'xml' else 'application/json'
        headers = {
            'Accept': type_header,
            'Content-Type': type_header,
            'Api-Version': self.api_version,
            'Api-AppId': self.api_key,
            'Api-Username': self.username,
            'API-Password': self.password,
        }

        req_params = {
            'headers': headers,
        }

        if parameters:
            if method.lower() == 'get':
                req_params['params'] = parameters
            else:
                if params_as_json or method.lower() == 'put':
                    req_params['json'] = parameters
                else:
                    req_params['data'] = parameters

        self.log_me(u'Invoking API method %s with URL: %s' % (method, url))
        req = self._perform_request(method, url, **req_params)
        self.log_me('response.status=%s headers=%s' % (req.status_code, req.headers,))
        response_status = req.status_code

        if response_type == 'xml':
            result = ElementTree.fromstring(req.content)
            self.log_me(u'Response body:\n%s' % (ElementTree.tostring(result),))
        else:
            # type is json
            result = req.json()
            self.log_me(u'json response=\n%s' % (result,))
            result = json_to_obj(result)

        if response_status >= 400:
            raise IContactServerError(response_status, result.errors)

        return result

    def _parse_stats(self, node):
        """
        Parses statistics information from a 'stats' XML node that will
        be present in an iContact API response to the
        message_delivery_details and message_stats methods. The parsed
        information is returned as a dictionary of dictionaries.
        """
        def summary_to_dict(stats_node):
            if stats_node is None:
                return None
            summary = dict(
                count=int(stats_node.get('count') or '0'),
                percent=float(stats_node.get('percent')),
                href=stats_node.get('{%s}href' % self.NAMESPACE))
            if stats_node.get('unique'):
                summary['unique'] = int(stats_node.get('unique'))
            return summary

        results = dict(
            released=summary_to_dict(node.find('released')),
            bounces=summary_to_dict(node.find('bounces')),
            unsubscribes=summary_to_dict(node.find('unsubscribes')),
            opens=summary_to_dict(node.find('opens')),
            clicks=summary_to_dict(node.find('clicks')),
            forwards=summary_to_dict(node.find('forwards')),
            comments=summary_to_dict(node.find('comments')),
            complaints=summary_to_dict(node.find('complaintss'))
        )
        contacts = []
        for c in node.findall('*/contact'):
            contact = dict(
                email=c.get('email'),
                name=c.get('name'),
                href=c.get('{%s}href' % self.NAMESPACE))
            dates = []
            for date_node in c.findall('*'):
                dates.append(parse(date_node.get('date')))
            contact['dates'] = dates
            contacts.append(contact)
        results['contacts'] = contacts
        return results

    def account(self, index=0):
        """
        Returns the first account object in the accounts dictionary.
        Url: /icp/a/
        """
        accountobj = self._do_request('a')

        return accountobj.accounts[index]

    def clientfolders(self, account_id, filters=None):
        """
        Returns the clientfolders object.
        Url: /icp/a/{accountId}/c
        """
        result = self._do_request('a/%s/c/' % account_id, parameters=filters)
        self.log_me("clientfolders: %s" % (result,))
        return result

    def clientfolder(self, account_id, index=0):
        """
        Returns the first clientfolder, or the provided index.
        """
        return self.clientfolders(account_id).clientfolders[index]

    def _required_values(self, account_id, client_folder_id):
        if account_id is None:
            if self.account_id is None:
                self.account_id = self._get_account_id()
            account_id = self.account_id
        if client_folder_id is None:
            if self.client_folder_id is None:
                self.client_folder_id = self._get_client_folder_id()
            client_folder_id = self.client_folder_id
        return account_id, client_folder_id

    def search_contacts(self, params=None, account_id=None, client_folder_id=None, **kwarg_params):
        """
        If account_id or client_folder_id is None, then use the default (first) one.
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        if params is None:
            params = {}
        params.update(kwarg_params)

        result = self._do_request('a/%s/c/%s/contacts/' % (account_id, client_folder_id), parameters=params)
        return result

    def lists(self, account_id=None, client_folder_id=None, filters=None):
        """
        Returns iContact Lists
        params is a dictionary
          * method = get|delete|post|put
          * account_id
          * client_folder_id
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        result = self._do_request('a/%s/c/%s/lists/' % (account_id, client_folder_id), parameters=filters)

        return result

    def list(self, list_id, account_id=None, client_folder_id=None):
        """
        Returns an object representing the iContact List identified by the given id number.
        In the json returned below, and object is created with attributes for each key.
        Example:
          {'list':{'listId':'123123', 'name':'name', 'description':'', 'emailOwnerOnChange':'',
                   'welcomeOnManualAdd':'', 'welcomeOnSignupAdd':'', 'welcomeMessageId':'123123'}}
          >>> client = IContactClient()
          >>> mylist = client.list(123123)
          >>> mylist.list.listId
          u'123123'
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        result = self._do_request('a/%s/c/%s/lists/%s/' % (account_id, client_folder_id, list_id))

        return result

    def create_list(self, name, email_owner_on_change, welcome_on_manual_add,
                    welcome_on_signup_add, welcome_message_id, description=None,
                    account_id=None, client_folder_id=None):
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        params = dict(name=name,
                      emailOwnerOnChange=email_owner_on_change,
                      welcomeOnManualAdd=welcome_on_manual_add,
                      welcomeOnSignupAdd=welcome_on_signup_add,
                      welcomeMessageId=welcome_message_id)
        if description:
            params['description'] = description

        result = self._do_request('a/%s/c/%s/lists/' % (account_id, client_folder_id),
                                  parameters=params, method='post')

        return result

    def segments(self, account_id=None, client_folder_id=None, filters=None):
        """
        Returns iContact Segments
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        result = self._do_request('a/%s/c/%s/segments/' % (account_id, client_folder_id), parameters=filters)

        return result

    def create_segment(self, name, list_id, description=None, account_id=None,
                       client_folder_id=None):
        """Creates segment"""

        """ TODO: this is just a temporarily note that segment creation is not
        working with icontact.com remote API, this is confirmed issue and we're
        waiting for icontact.com support team to fix this. They promissed us
        to fix it as soon as possible ;)
        """

        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        params = dict(name=name, listId=list_id)
        if description:
            params['description'] = description

        result = self._do_request('a/%s/c/%s/segments/' % (account_id, client_folder_id),
                                  parameters=params, method='post')

        return result

    def create_criterion(self, segment_id, field_name, operator, values,
                         account_id=None, client_folder_id=None):
        """Creates single criterion for a given segment"""
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        params = dict(fieldName=field_name, operator=operator, values=values)

        result = self._do_request('a/%s/c/%s/segments/%s/criteria/' % (
            account_id, client_folder_id, segment_id),
            parameters=params, method='post')

        return result

    def move_subscriber(self, old_list, contact_id, new_list, account_id=None, client_folder_id=None):
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        params = dict(listId=new_list)

        result = self._do_request('a/%s/c/%s/subscriptions/%s_%s' % (account_id, client_folder_id,
                                                                     old_list, contact_id),
                                  parameters=params,
                                  method='put')

        return result

    def create_or_update_contact(self, account_id=None, client_folder_id=None, data=None):
        """
        Create or Update the contact
        :param data: List of dicts holding multiple contacts data
        """
        account_id, client_folder_id = self._required_values(account_id,
                                                             client_folder_id)
        if data and type(data) != list:
            data = [data]

        result = self._do_request('a/%s/c/%s/contacts/' %
                                  (account_id, client_folder_id),
                                  parameters=data,
                                  method='post',
                                  params_as_json=True)
        return result

    def create_contact(self, email, account_id=None, client_folder_id=None, **kwargs):
        """
        Creates the contact and returns the contact object.
        email - required
        kwargs - prefix, firstName, lastName, suffix, street, street2, city, state, postalCode
               - phone, fax, business, status
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        params = dict(contact=kwargs)
        params['contact']['email'] = email
        if 'status' not in params['contact']:
            params['contact']['status'] = 'normal'

        result = self._do_request('a/%s/c/%s/contacts/' % (account_id, client_folder_id),
                                  parameters=params,
                                  method='post')

        return result

    def update_contact(self, contact_id, account_id=None, client_folder_id=None, **kwargs):
        """
        Updates a contact and returns the contact object
        contact_id - required
        kwargs - prefix, firstName, lastName, suffix, street, street2, city, state, postalCode
               - phone, fax, business, status
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        params = dict(contact=kwargs)
        params['contact']['contactId'] = contact_id
        return self._do_request('a/%s/c/%s/contacts/' % (account_id, client_folder_id),
                                parameters=params,
                                method='post')

    def delete_contact(self, contact_id, account_id=None, client_folder_id=None):
        """
        Deletes the contact and returns the result (an empty list)
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        result = self._do_request('a/%s/c/%s/contacts/%s' % (account_id, client_folder_id,
                                  contact_id), method='delete')

        return result

    def contact_history(self, contact_id, account_id=None, client_folder_id=None, filters=None):
        """
        Returns action history for a contact
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        result = self._do_request('a/%s/c/%s/contacts/%s/actions/' % (account_id, client_folder_id,
                                  contact_id), parameters=filters)
        return result

    def create_subscription(self, contact_id, list_id, status='normal', account_id=None, client_folder_id=None):
        """
        Creates the subscription for the contact.
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        data = dict(subscription=dict(contactId=contact_id, listId=list_id, status=status))
        result = self._do_request('a/%s/c/%s/subscriptions/' % (account_id, client_folder_id),
                                  parameters=data,
                                  method='post')
        return result

    def subscriptions(self, account_id=None, client_folder_id=None, filters=None):
        """
        Returns iContact Subscriptions
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        result = self._do_request('a/%s/c/%s/subscriptions/' % (account_id, client_folder_id), parameters=filters)

        return result

    def create_or_update_subscription(self, account_id=None, client_folder_id=None, data=None):
        """
        Create or Update the subscription for the contact.
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        if data and type(data) != list:
            data = [data]

        result = self._do_request('a/%s/c/%s/subscriptions/' %
                                  (account_id, client_folder_id),
                                  parameters=data,
                                  method='post',
                                  params_as_json=True)
        return result

    def create_message(self, subject, message_type, account_id=None, client_folder_id=None, **kwargs):
        """
        Creates a message.  Note, the campaignId is required.
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        message = dict(subject=subject, messageType=message_type)
        message.update(kwargs)
        data = dict(message=message)

        result = self._do_request('a/%s/c/%s/messages/' % (account_id, client_folder_id),
                                  parameters=data,
                                  method='post')
        return result

    def messages(self, account_id=None, client_folder_id=None, filters=None):
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        result = self._do_request('a/%s/c/%s/messages/' % (account_id, client_folder_id), parameters=filters)
        return result

    def get_message(self, message_id, account_id=None, client_folder_id=None):
        """
        Gets message.
        """
        account_id, client_folder_id = self._required_values(account_id,
                                                             client_folder_id)

        result = self._do_request('a/%s/c/%s/messages/%s' %
                                  (account_id, client_folder_id, message_id),
                                  method='get')
        return result

    def create_send(self, message_id, include_list_ids, account_id=None,
                    client_folder_id=None, **kwargs):
        """
        Creates a send.
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        alert = dict(messageId=message_id, includeListIds=','.join(include_list_ids))
        alert.update(kwargs)
        data = dict(send=alert)

        result = self._do_request('a/%s/c/%s/sends/' % (account_id, client_folder_id),
                                  parameters=data,
                                  method='post')
        return result

    def delete_send(self, send_id, account_id=None, client_folder_id=None):
        """
        Deletes send.
        """
        account_id, client_folder_id = self._required_values(account_id,
                                                             client_folder_id)

        result = self._do_request('a/%s/c/%s/sends/%s' %
                                  (account_id, client_folder_id, send_id),
                                  method='delete')
        return result

    def get_send(self, send_id, account_id=None, client_folder_id=None):
        """
        Gets send.
        """
        account_id, client_folder_id = self._required_values(account_id,
                                                             client_folder_id)

        result = self._do_request('a/%s/c/%s/sends/%s' %
                                  (account_id, client_folder_id, send_id),
                                  method='get')
        return result

    def create_or_update_custom_object(self, custom_object_id, account_id=None, client_folder_id=None, data=None):
        """
        Create or Update the custom object data
        :param data: List of dicts holding multiple custom objects data
        """
        account_id, client_folder_id = self._required_values(account_id,
                                                             client_folder_id)
        if data and type(data) != list:
            data = [data]

        result = self._do_request('a/%s/c/%s/customobjects/%s/data/' %
                                  (account_id, client_folder_id, custom_object_id),
                                  parameters=data,
                                  method='post',
                                  params_as_json=True)
        return result

    def delete_custom_object_data(self, custom_object_id, custom_object_field_definition_id,
                                  account_id=None, client_folder_id=None):
        """
        Deletes the custom object data record for custom object specified via `custom_object_id`
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        result = self._do_request('a/%s/c/%s/customobjects/%s/data/%s/' % (
            account_id, client_folder_id, custom_object_id, custom_object_field_definition_id), method='delete')

        return result

    def get_custom_object_data(self, custom_object_id, account_id=None, client_folder_id=None, **kwargs):
        """
        Get all records of a custom object defined by `custom_object_id`
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        result = self._do_request('a/%s/c/%s/customobjects/%s/data/' % (
            account_id, client_folder_id, custom_object_id), parameters=kwargs)

        return result

    def log_me(self, msg):
        if self.log_enabled:
            self.log.debug(msg)


class FixedOffset(tzinfo):
    """
    Fixed offset value that extends the `datetime.tzinfo` object to
    calculate a time relative to UTC.

    This class is taken directly from the django module
    `django.utils.tzinfo`
    """
    def __init__(self, offset):
        """
        Represent a time offset from UTC by a given number of minutes.

        For example, to represent the iContact timezone (UTC -04:00)::

            utc_datetime = datetime.utcnow()
            ic_datetime = utc_datetime.astimezone(FixedOffset(-4 * 60))
        """
        self.__offset = timedelta(minutes=offset)
        self.__name = u"%+03d%02d" % (offset // 60, offset % 60)

    def __repr__(self):
        return self.__name

    def utcoffset(self, dt):
        return self.__offset

    def tzname(self, dt):
        return self.__name

    def dst(self, dt):
        return timedelta(0)
