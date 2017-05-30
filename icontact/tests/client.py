import os
import unittest

from icontact.client import IContactClient, IContactServerError


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
            url=IContactClient.ICONTACT_SANDBOX_API_URL,
        )

    def test_account(self):
        account = self.client.account()
        self.assertIsNotNone(account, "Did not get account object")
        self.assertTrue(long(account.accountId) > 0, "Did not get valid accountId")

    def test_folder(self):
        account = self.client.account()
        folder = self.client.clientfolder(account.accountId)
        self.assertIsNotNone(folder.clientFolderId, "Did not get clientFolderId")

    def test_find_or_create_contact(self):
        email = 'name@example.com'
        contacts = self.client.search_contacts({'email': email})
        if contacts.total == 0:
            contacts = self.client.create_contact(email, firstName='Firstname', lastName='Lastname')
            self.assertTrue(contacts.contacts[0].email == email, "Contacts=%s" % (contacts,))
        else:
            self.assertTrue(contacts.contacts[0].email == email)

    def test_subscribe(self):
        email = 'name@example.com'
        contacts = self.client.search_contacts({'email': email})
        contact_id = contacts.contacts[0].contactId
        result = self.client.subscriptions(filters={'contactId': contact_id})
        if result.total == 0:
            result = self.client.create_subscription(contact_id, self.ICONTACT_MAIN_LIST_ID)
        self.assertTrue(len(result.subscriptions) == 1)

    def test_unsubscribe(self):
        # note, you can't un-subscribe, you can only move them to a holding list
        email = 'name@example.com'
        contacts = self.client.search_contacts({'email': email})
        contact_id = contacts.contacts[0].contactId
        try:
            result = self.client.move_subscriber(
                self.ICONTACT_MAIN_LIST_ID, contact_id, self.ICONTACT_HOLDING_LIST_ID)
            self.assertTrue(result.subscription.listId == str(self.ICONTACT_HOLDING_LIST_ID))
        except IContactServerError, e:
            if e.http_status == 400 and 'No Changes Made' in e.errors:
                pass
            else:
                raise e


if __name__ == '__main__':
    unittest.main()
