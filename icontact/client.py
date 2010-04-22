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
try:
    from django.utils import simplejson
except ImportError:
    import simplejson
import md5
import random
import time
import httplib
import urllib
import urllib2
import urlparse
import logging

from datetime import datetime, tzinfo, timedelta
from xml.etree import ElementTree
from xml.etree.ElementTree import Element, SubElement

from dateutil.parser import parse
from dateutil.relativedelta import relativedelta


class ExcessiveRetriesException(Exception):
    """
    A standard exception that represents a potentially transient fault 
    where an an iContact API client fails to perform an operation more
    than `self.max_retry_count` times.
    """
    pass


class ClientException(Exception):
    """
    A standard exception that represents an unrecoverable fault
    during an iContact API operation.
    """
    pass

class IContactClient(object):
    """Perform operations on the iContact API."""
    
    #ICONTACT_API_URL = 'https://app.icontact.com/icp/'
    ICONTACT_API_URL = 'https://app.sandbox.icontact.com/icp/'
    NAMESPACE = 'http://www.w3.org/1999/xlink'
                
    def __init__(self, api_key, username, password, 
        auth_handler=None, max_retry_count=5):
        """
        - api_key: the API Key assigned for the OA iContact client
        - username: the iContact web site login username
        - password: 
          This is the password registered for the API client, also known 
          as the "API Application Password". It is *not* the standard 
          web site login password.
        - max_retry_count: (Optional) Retry limit for logins or 
          rate-limited operations.
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
        self.api_version = "2.2"
        self.username = username
        self.password = password
        self.auth_handler = auth_handler
        self.log = logging.getLogger('icontact')
        self.max_retry_count = max_retry_count

        self.account_id = None
        self.client_folder_id = None
        
        # Track number of retries we have performed
        self.retry_count = 0

    def _get_account_id(self):
        self.account_id = self.account()['accountId']
        return self.account_id

    def _get_client_folder_id(self):
        self.client_folder_id = self.clientfolder(self.account_id)['clientFolderId']
        return self.client_folder_id

    def _do_request(self, call_path, parameters={},method='get',type='json'):
        """
        Performs an API request and returns the resultant json object.
        If type='xml' is passed in, returns XML document as an
        xml.etree.ElementTree node. An Exception is thrown if the operation 
        results in an error response from iContact, or if there is no
        authentication information available (ie login has not been called)        
                
        This method does all the hard work for API operations: building the 
        URL path; adding auth headers; sending the request to iContact; 
        evaluating the response; and parsing the respones to an XML node.
        """
        # Check whether this method call was a retry that exceeds the retry limit
        if self.retry_count > self.max_retry_count:
            raise ExcessiveRetriesException("Exceeded maximum retry count (%d)" % self.max_retry_count)
        params = dict(parameters)
        data = None

        if method.lower() == 'get' and len(params) > 0:
            url = "%s%s?%s" % (self.ICONTACT_API_URL, call_path, urllib.urlencode(params))
        else:
            url = "%s%s" % (self.ICONTACT_API_URL, call_path)
            data = simplejson.dumps(params)

        self.log.debug(u"Invoking API method %s with URL: %s" % (method, url))

        if type == 'xml':
            type_header = 'text/xml'
        else:
            type_header = 'application/json'
        headers = {'Accept':type_header,
                   'Content-Type':type_header,
                   'Api-Version':self.api_version,
                   'Api-AppId':self.api_key,
                   'Api-Username':self.username, 
                   'API-Password':self.password }
                
        # TODO: try request for urllib2.HTTPError for 503 to do rate limit retry

        if method.lower() != 'get':
            # Perform a PUT request
            self.log.debug(u'%s Request %s body: %s' % (method, url, data))
            scheme, host, path, params, query, fragment = urlparse.urlparse(url)
            conn = httplib.HTTPSConnection(host, 443)            
            conn.request(method.upper(), path , data, headers)
            response = conn.getresponse()
            self.log.debug("response.msg=%s headers=%s" % (response.msg, response.getheaders(),))
        else:
            # Perform a GET request
            req = urllib2.Request(url, None, headers)
            self.log.debug("GET headers=%s url=%s" % (req.headers,url))
            response = urllib2.urlopen(req)

        if type == 'xml':
            xml = ElementTree.fromstring(response.read())
            self.log.debug(u'Response body:\n%s' % (ElementTree.tostring(xml),))
        else:
            # type is json
            jsondata = response.read()
            self.log.debug(u"json response=\n%s" % (jsondata,))
            xml = simplejson.loads(jsondata)

        # Reset retry count to 0 since we have a successful response
        self.retry_count = 0                
        return xml        

    def _parse_stats(self, node):
        """
        Parses statistics information from a 'stats' XML node that will
        be present in an iContact API response to the 
        message_delivery_details and message_stats methods. The parsed
        information is returned as a dictionary of dictionaries.        
        """
        def summary_to_dict(stats_node):
            if stats_node == None:
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
        contacts=[]
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
        accountobj = self._do_request('a', type='json')

        return accountobj['accounts'][index]

    def clientfolders(self, account_id):
        """
        Returns the clientfolders object.
        Url: /icp/a/{accountId}/c
        """
        result = self._do_request('a/%s/c' % (account_id,), type='json')
        self.log.debug("clientfolders: %s" % (result,))
        return result

    def clientfolder(self, account_id, index=0):
        """ 
        Returns the first clientfolder, or the provided index.
        """
        return self.clientfolders(account_id)['clientfolders'][index]
        

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


    def search_contacts(self, params, account_id=None, client_folder_id=None):
        """
        If account_id or client_folder_id is None, then use the default (first) one.
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        p = ""
        for k in params:
            if len(p) > 0:
                p += "&"
            p += "%s=%s" % (k,params[k])

        result = self._do_request('a/%s/c/%s/contacts/?%s' % (account_id, client_folder_id, p), type='json')
        self.log.debug("search_contacts(%s)=%s" % (p, result))
        return result


    def lists(self, params=None, account_id=None, client_folder_id=None):
        """
        Returns iContact Lists
        params is a dictionary
          * method = get|delete|post|put
          * account_id
          * client_folder_id
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        result = self._do_request('a/%s/c/%s/lists/' % (account_id,client_folder_id))

        return result
    
    def list(self, list_id, account_id=None, client_folder_id=None):
        """
        Returns a dictionary of information about the iContact List 
        identified by the given id number.
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)

        result = self._do_request('a/%s/c/%s/lists/%s/' % (account_id,client_folder_id, list_id))

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

        result = self._do_request('a/%s/c/%s/lists' % (account_id,client_folder_id), 
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

    def create_contact(self, name, account_id=None, client_folder_id=None, **kwargs):
        """
        Creates the contact and returns the contact object.
        """
        account_id, client_folder_id = self._required_values(account_id, client_folder_id)
        params = dict(contact=kwargs)
        params['contact']['email']=name
        if 'status' not in params['contact']:
            params['contact']['status'] = 'normal'
        
        result = self._do_request('a/%s/c/%s/contacts/' % (account_id, client_folder_id),
                                  parameters=params,
                                  method='post')

        return result 


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