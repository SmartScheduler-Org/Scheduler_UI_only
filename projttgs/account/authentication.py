from django.contrib.auth.models import User
from django.core.exceptions import MultipleObjectsReturned


class EmailAuthBackend(object):
    """
    Authenticate using an e-mail address.
    """
    def authenticate(self, request, username=None, password=None):
        try:
            user = User.objects.get(email=username)
            if user.check_password(password):
                return user
            return None
        except User.DoesNotExist:
            return None
        except MultipleObjectsReturned:
            # Two accounts share the same email — fail safe instead of 500.
            # The user should contact support or log in with their username.
            return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None