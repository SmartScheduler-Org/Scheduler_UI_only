import re
from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _


class StrongPasswordValidator:
    """
    Requires: 8+ chars, uppercase, lowercase, digit, special char.
    Used in AUTH_PASSWORD_VALIDATORS so it applies to registration,
    password change, and password reset automatically.
    """
    SPECIAL = r'[@$!%*?&_\-#]'

    def validate(self, password, user=None):
        errors = []
        if len(password) < 8:
            errors.append(_('at least 8 characters'))
        if not re.search(r'[A-Z]', password):
            errors.append(_('one uppercase letter (A-Z)'))
        if not re.search(r'[a-z]', password):
            errors.append(_('one lowercase letter (a-z)'))
        if not re.search(r'\d', password):
            errors.append(_('one digit (0-9)'))
        if not re.search(self.SPECIAL, password):
            errors.append(_('one special character (@$!%*?&_-#)'))
        if errors:
            raise ValidationError(
                _('Password must contain: %(reqs)s.'),
                code='password_too_weak',
                params={'reqs': ', '.join(errors)},
            )

    def get_help_text(self):
        return _(
            'Your password must be at least 8 characters and include '
            'an uppercase letter, a lowercase letter, a digit, and a '
            'special character (@$!%*?&_-#).'
        )
