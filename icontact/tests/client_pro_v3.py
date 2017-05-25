import os
import unittest

from icontact.client import IContactClient


class ClientTestCase(unittest.TestCase):

    def setUp(self):
        self.ICONTACT_API_KEY = os.environ['ICONTACT_API_KEY']
        self.ICONTACT_USERNAME = os.environ['ICONTACT_USERNAME']
        self.ICONTACT_PASSWORD = os.environ['ICONTACT_PASSWORD']
        self.ICONTACT_ACCOUNT_ID = os.environ.get('ICONTACT_ACCOUNT_ID', None)
        self.ICONTACT_CLIENT_FOLDER_ID = os.environ.get('ICONTACT_CLIENT_FOLDER_ID', None)
        self.ICONTACT_MAIN_LIST_ID = os.environ.get('ICONTACT_MAIN_LIST_ID', None)
        self.ICONTACT_HOLDING_LIST_ID = os.environ.get('ICONTACT_HOLDING_LIST_ID', None)

        self.client = IContactClient(
            self.ICONTACT_API_KEY,
            self.ICONTACT_USERNAME,
            self.ICONTACT_PASSWORD,
            account_id=self.ICONTACT_ACCOUNT_ID,
            client_folder_id=self.ICONTACT_CLIENT_FOLDER_ID,
            url='https://api.icpro.co/icp/',
            api_version='2.3',
        )

    def test_account(self):
        account = self.client.account()
        self.assertIsNotNone(account, "Did not get account object")
        self.assertTrue(long(account.accountId) > 0, "Did not get valid accountId")

    def test_folder(self):
        account = self.client.account()
        folder = self.client.clientfolder(account.accountId)
        self.assertIsNotNone(folder.clientFolderId, "Did not get clientFolderId")

    def TEST_CONTACT(self):
        email = 'name5@example.com'
        contact = {'email': email, 'firstName': 'Firstname', 'lastName': 'Lastname'}
        contacts = self.client.create_or_update_contact(data=[contact])
        self.assertTrue(contacts.contacts[0].email == email, "Contacts=%s" % (contacts,))

    def TEST_SUBSCRIPTION(self):
        email = 'name5@example.com'
        contacts = self.client.search_contacts({'email': email})
        contact_id = contacts.contacts[0].contactId
        subscription = {'contactId': contact_id, 'listId': self.ICONTACT_MAIN_LIST_ID, 'status': 'normal'}

        subscriptions = self.client.subscriptions(filters={'contactId': contact_id})
        if subscriptions.total == 0:
            # test `create_or_update_subscription`
            result = self.client.create_or_update_subscription(data=[subscription])
            self.assertTrue(len(result.subscriptions) == 1, "Subscriptions=%s" % (result,))
        else:
            self.assertTrue(subscriptions.subscriptions[0].contactId == contact_id)

        '''
        # @TODO: fix me, API returns error as "No changes detected"
        # test `move_subscriber`
        result = self.client.move_subscriber(
            self.ICONTACT_MAIN_LIST_ID, contact_id, self.ICONTACT_HOLDING_LIST_ID)
        self.assertTrue(result.subscription.listId == str(self.ICONTACT_HOLDING_LIST_ID))
        '''

        # test delete contact
        result = self.client.delete_contact(contact_id)

    def test_contact_and_subscription(self):
        self.TEST_CONTACT()
        self.TEST_SUBSCRIPTION()

if __name__ == '__main__':
    unittest.main()
