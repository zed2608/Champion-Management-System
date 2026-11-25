import unittest
import bcrypt
from auth_helpers import verify_password

class AuthTests(unittest.TestCase):
    def test_valid_and_wrong(self):
        h = bcrypt.hashpw(b"private-demo-password", bcrypt.gensalt(rounds=4)).decode()
        self.assertTrue(verify_password("private-demo-password", h))
        self.assertFalse(verify_password("incorrect", h))
    def test_fail_closed(self):
        for h in (None, "", "invalid"):
            self.assertFalse(verify_password("password", h))
        self.assertFalse(verify_password("x"*73, "invalid"))
